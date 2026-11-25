from __future__ import annotations

import re
from pathlib import Path

from .git_tools import GitError, GitRunner


class CheckEngine:
    BASELINE_FALLBACKS = {
        "assessment_start": "assessment-start",
        "main": "main",
        "fix_validation": "fix/validation",
        "initial_head": "HEAD",
    }
    BASELINE_TOKEN_RE = re.compile(r"\{baseline:([A-Za-z0-9_]+)\}")
    CONFLICT_PREFIXES = ("<<<<<<<", "=======", ">>>>>>>", "|||||||")

    def __init__(self, git: GitRunner):
        self.git = git

    def run_all(
        self,
        repo: Path,
        checks: list[dict],
        baseline: dict[str, str] | None = None,
        context: dict | None = None,
    ) -> list[dict]:
        resolved_baseline = baseline or {}
        resolved_context = context or {}
        return [self.run_one(repo, check, resolved_baseline, resolved_context) for check in checks]

    def run_one(
        self,
        repo: Path,
        check: dict,
        baseline: dict[str, str] | None = None,
        context: dict | None = None,
    ) -> dict:
        try:
            passed, success, failure = self._evaluate(repo, check, baseline or {}, context or {})
            message = success if passed else failure
        except (GitError, OSError, ValueError, re.error) as exc:
            passed = False
            message = f"無法完成檢查：{exc}"
        return {
            "check_id": check["id"],
            "passed": passed,
            "label": check["label"],
            "message": message,
            "required": check.get("required", True),
        }

    def _resolve_ref(self, value: str | None, baseline: dict[str, str]) -> tuple[str | None, str | None]:
        if value is None:
            return None, None
        missing_key: str | None = None

        def replace(match: re.Match[str]) -> str:
            nonlocal missing_key
            key = match.group(1)
            val = baseline.get(key)
            if val:
                return val
            if key in self.BASELINE_FALLBACKS:
                return self.BASELINE_FALLBACKS[key]
            missing_key = key
            return ""

        resolved = self.BASELINE_TOKEN_RE.sub(replace, value)
        if missing_key is not None:
            return None, missing_key
        return resolved, None

    def _read_content(self, repo: Path, check: dict, baseline: dict[str, str]) -> tuple[bool, str, str | None]:
        if check.get("revision"):
            revision, missing = self._resolve_ref(str(check["revision"]), baseline)
            if revision is None:
                return False, "", "缺少伺服器端基準紀錄，請重設本題後再試"
            result = self.git.run(repo, "show", f"{revision}:{check['file']}", check=False)
            if result.returncode != 0:
                return False, "", None
            return True, result.stdout, None
        path = self._safe_file(repo, check["file"])
        if not path.exists():
            return False, "", None
        return True, path.read_text(encoding="utf-8", errors="replace"), None

    @staticmethod
    def _is_exam(context: dict) -> bool:
        return context.get("mode") == "exam"

    @staticmethod
    def _normalize_porcelain_path(row: str) -> str:
        return row[3:].strip().strip('"').replace("\\", "/")

    def _evaluate(
        self, repo: Path, check: dict, baseline: dict[str, str], context: dict
    ) -> tuple[bool, str, str]:
        kind = check["type"]
        expected = check.get("expected")
        exam = self._is_exam(context)

        if kind == "current_branch":
            actual = self.git.run(repo, "branch", "--show-current").stdout
            if actual == expected:
                return True, f"目前位於 {actual}", ""
            actual_desc = actual or "detached HEAD（尚未位於任何分支）"
            hint = "" if exam else f"；請確認切換至 {expected}"
            return False, "", f"目前位於 {actual_desc}，預期應位於 {expected}{hint}"

        if kind == "branch_exists":
            result = self.git.run(repo, "show-ref", "--verify", f"refs/heads/{expected}", check=False)
            if result.returncode == 0:
                return True, "指定分支存在", ""
            hint = "" if exam else "；請先執行 git fetch origin 再建立本機分支"
            return False, "", f"尚未找到本機分支 {expected}{hint}"

        if kind == "branch_tracks_remote":
            branch_name = str(expected)
            remote_name = str(check.get("remote", "origin"))
            remote_branch = str(check.get("remote_branch", branch_name))
            exists = self.git.run(repo, "show-ref", "--verify", f"refs/heads/{branch_name}", check=False)
            if exists.returncode != 0:
                hint = "" if exam else f"；請先 git fetch {remote_name} 後建立追蹤分支"
                return False, "", f"尚未建立本機分支 {branch_name}{hint}"
            cfg_remote = self.git.run(repo, "config", "--get", f"branch.{branch_name}.remote", check=False).stdout
            cfg_merge = self.git.run(repo, "config", "--get", f"branch.{branch_name}.merge", check=False).stdout
            expected_merge = f"refs/heads/{remote_branch}"
            if cfg_remote == remote_name and cfg_merge == expected_merge:
                return True, f"已建立追蹤 {remote_name}/{remote_branch} 的分支", ""
            hint = "" if exam else f"；請使用 git switch --track {remote_name}/{remote_branch}"
            return False, "", f"本機分支 {branch_name} 尚未設定追蹤 {remote_name}/{remote_branch}{hint}"

        if kind == "commit_message":
            revision, missing = self._resolve_ref(str(check.get("revision", "HEAD")), baseline)
            if revision is None:
                return False, "", f"缺少基準版本（{missing}）"
            res = self.git.run(repo, "log", "-1", "--format=%s", revision, check=False)
            if res.returncode != 0:
                return False, "", "尚未找到可用的 commit"
            actual = res.stdout
            match_mode = check.get("match", "exact")
            passed = actual == expected if match_mode == "exact" else str(expected) in actual
            if passed:
                return True, "Commit message 正確", ""
            if match_mode == "exact":
                return False, "", f"目前最新 commit 訊息為「{actual}」，必須完全等於「{expected}」"
            return False, "", f"目前最新 commit 訊息為「{actual}」，需包含「{expected}」"

        if kind == "commit_count":
            range_expr, _ = self._resolve_ref(check["range"], baseline)
            if range_expr is None:
                return False, "", "缺少起始基準紀錄，請重設本題後再試"
            res = self.git.run(repo, "rev-list", "--count", range_expr, check=False)
            if res.returncode != 0:
                return False, "", "無法計算指定範圍的 commit 數量，請確認分支與基準是否正確"
            actual = int(res.stdout)
            target = int(expected)
            if actual == target:
                return True, f"Commit 數量正確（{actual}）", ""
            hint = "" if exam or actual != 0 else "；尚未建立新的 commit"
            return False, "", f"目前共有 {actual} 筆 commit，題目限制為 {target} 筆{hint}"

        if kind == "file_contains":
            exists, actual, err = self._read_content(repo, check, baseline)
            if err:
                return False, "", err
            if not exists:
                return False, "", f"找不到檔案 {check['file']}"
            if str(expected) in actual:
                return True, "檔案內容正確", ""
            return False, "", f"{check['file']} 的內容尚未符合要求（缺少預期設定）"

        if kind == "file_equals":
            exists, actual, err = self._read_content(repo, check, baseline)
            if err:
                return False, "", err
            if not exists:
                return False, "", f"找不到檔案 {check['file']}"
            actual_norm = actual.replace("\r\n", "\n").strip()
            expected_norm = str(expected).replace("\r\n", "\n").strip()
            if actual_norm == expected_norm:
                return True, "檔案完整內容正確", ""
            return False, "", f"{check['file']} 的完整內容與預期不符"

        if kind == "file_matches":
            exists, actual, err = self._read_content(repo, check, baseline)
            if err:
                return False, "", err
            if not exists:
                return False, "", f"找不到檔案 {check['file']}"
            matched = re.search(str(expected), actual.replace("\r\n", "\n"), flags=re.MULTILINE) is not None
            if matched:
                return True, "檔案內容格式正確", ""
            return False, "", f"{check['file']} 尚未包含符合條件的設定行"

        if kind == "file_not_contains":
            exists, actual, err = self._read_content(repo, check, baseline)
            if err:
                return False, "", err
            if not exists:
                return True, "未殘留禁止的設定內容", ""
            normalized = actual.replace("\r\n", "\n")
            if check.get("regex"):
                found = re.search(str(expected), normalized, flags=re.MULTILINE) is not None
            else:
                found = str(expected) in normalized
            if not found:
                return True, "未殘留衝突前的舊設定值", ""
            return False, "", f"{check['file']} 仍殘留不應保留的舊設定或衝突內容"

        if kind == "file_not_exists":
            if check.get("revision"):
                rev, _ = self._resolve_ref(str(check["revision"]), baseline)
                if rev is None:
                    return False, "", "缺少基準版本"
                exists = self.git.run(repo, "cat-file", "-e", f"{rev}:{check['file']}", check=False).returncode == 0
            else:
                exists = self._safe_file(repo, check["file"]).exists()
            if not exists:
                return True, "未帶入不相關檔案", ""
            return False, "", f"偵測到不應出現的檔案 {check['file']}（可能誤合併了整個來源分支）"

        if kind == "no_conflict_markers":
            exists, actual, err = self._read_content(repo, check, baseline)
            if err:
                return False, "", err
            if not exists:
                return False, "", f"找不到檔案 {check['file']}"
            has_markers = any(
                line.startswith(self.CONFLICT_PREFIXES)
                for line in actual.replace("\r\n", "\n").splitlines()
            )
            if not has_markers:
                return True, "已清除所有 conflict 標記", ""
            return (
                False,
                "",
                f"{check['file']} 仍包含 conflict 標記（<<<<<<< / ======= / >>>>>>>），請手動整理並移除標記後再提交",
            )

        if kind in {"file_at_revision_contains", "file_at_revision_not_contains"}:
            revision, _ = self._resolve_ref(str(check["revision"]), baseline)
            if revision is None:
                return False, "", "缺少指定的基準版本"
            result = self.git.run(repo, "show", f"{revision}:{check['file']}", check=False)
            contains = result.returncode == 0 and str(expected) in result.stdout
            passed = contains if kind == "file_at_revision_contains" else result.returncode == 0 and not contains
            if kind == "file_at_revision_contains":
                if passed:
                    return True, "Commit 中的檔案內容正確", ""
                return False, "", f"{revision} 中的 {check['file']} 尚未包含指定修改"
            if passed:
                return True, "指定分支未包含本題修改", ""
            return False, "", f"{revision} 中的 {check['file']} 包含了不應出現的修改"

        if kind in {"file_in_commit", "file_not_in_commit"}:
            return self._evaluate_file_in_commit(repo, check, baseline, exam)

        if kind in {"working_tree_modified", "untracked_file"}:
            return self._evaluate_working_tree_file(repo, check, exam)

        if kind == "working_tree_clean":
            rows = self.git.run(repo, "status", "--porcelain=v1").stdout.splitlines()
            if not rows:
                return True, "Working tree 乾淨", ""
            files = ", ".join(self._normalize_porcelain_path(row) for row in rows[:3])
            suffix = " 等" if len(rows) > 3 else ""
            return False, "", f"Working tree 仍有未處理的修改（{files}{suffix}）"

        if kind == "stash_count":
            output = self.git.run(repo, "stash", "list").stdout
            actual = len(output.splitlines()) if output else 0
            target = int(expected)
            if actual == target:
                return True, "暫存紀錄狀態正確", ""
            hint = "" if exam else "；請確認使用 git stash pop 取出並移除暫存"
            return False, "", f"目前仍有 {actual} 筆 stash 紀錄，需要清理為 {target} 筆{hint}"

        if kind == "no_operation_in_progress":
            git_dir = Path(self.git.run(repo, "rev-parse", "--absolute-git-dir").stdout)
            op_map = [
                ("rebase-merge", "rebase"),
                ("rebase-apply", "rebase"),
                ("MERGE_HEAD", "merge"),
                ("CHERRY_PICK_HEAD", "cherry-pick"),
            ]
            active = next((label for marker, label in op_map if (git_dir / marker).exists()), None)
            if active is None:
                return True, "沒有進行中的 Git 操作", ""
            return False, "", f"仍有未完成的 {active} 操作，請先完成（--continue）或取消（--abort）"

        if kind == "ref_equals":
            expected_ref, missing_key = self._resolve_ref(str(expected), baseline)
            if expected_ref is None:
                if missing_key == "remote_pending_main":
                    return False, "", "缺少模擬遠端基準紀錄，請重設本題後再試"
                return False, "", "缺少伺服器端基準紀錄"
            ref_name = str(check["ref"])
            actual_res = self.git.run(repo, "rev-parse", "--verify", ref_name, check=False)
            if actual_res.returncode != 0:
                return False, "", f"找不到 ref：{ref_name}"
            actual_sha = actual_res.stdout.strip()
            if actual_sha == expected_ref:
                return True, "分支／遠端追蹤版本正確", ""
            if ref_name == "refs/remotes/origin/main":
                if not context.get("remote_updated"):
                    return False, "", "尚未按下「模擬遠端 main 更新」並執行 git fetch origin"
                return False, "", "遠端 main 已有新 commit，但本機 origin/main 尚未更新，請執行 git fetch origin"
            if ref_name == "refs/heads/main":
                return False, "", "main 分支指向的 commit 已被移動，請保持 main 在題目起始位置"
            return False, "", f"{ref_name} 目前指向 {actual_sha[:7]}，與預期（{expected_ref[:7]}）不符"

        if kind in {"is_ancestor", "not_is_ancestor"}:
            anc_raw = str(check["ancestor"])
            desc_raw = str(check["descendant"])
            uses_baseline = "{baseline:" in anc_raw or "{baseline:" in desc_raw
            anc, _ = self._resolve_ref(anc_raw, baseline)
            desc, _ = self._resolve_ref(desc_raw, baseline)
            if anc is None or desc is None:
                return False, "", "缺少遠端更新基準紀錄，請先重設本題後再試"
            result = self.git.run(repo, "merge-base", "--is-ancestor", anc, desc, check=False)
            if result.returncode not in {0, 1}:
                if uses_baseline:
                    return False, "", "本機尚未取得遠端最新 commit，請先按「模擬遠端 main 更新」並執行 git fetch origin"
                detail = result.stderr or result.stdout or "指定的 revision 不存在"
                raise GitError(detail)
            is_ancestor = result.returncode == 0
            passed = is_ancestor if kind == "is_ancestor" else not is_ancestor
            if passed:
                return True, "Commit 關係符合要求", ""
            if kind == "is_ancestor":
                short = anc[:7] if len(anc) == 40 else anc
                return False, "", f"目前分支尚未基於最新的 {short}，請先完成 fetch 與 rebase"
            return False, "", f"偵測到來源分支 {anc} 已成為目前分支的祖先（請改用 cherry-pick，不可 merge）"

        if kind == "no_merge_commit":
            range_expr, _ = self._resolve_ref(check["range"], baseline)
            if range_expr is None:
                return False, "", "缺少遠端更新基準紀錄，請先建立遠端更新並 fetch"
            res = self.git.run(repo, "rev-list", "--merges", range_expr, check=False)
            if res.returncode != 0:
                return False, "", "本機尚未取得遠端最新 commit，請先執行 git fetch origin"
            if res.stdout == "":
                return True, "沒有多餘的 merge commit", ""
            return False, "", "偵測到 merge commit；本題必須使用 rebase 完成整合，不可使用 merge"

        if kind in {"reflog_contains", "reflog_contains_action"}:
            output = self.git.run(repo, "reflog", "--format=%gs", check=False).stdout
            if str(expected) in output:
                success_msg = "已完成指定的 Git 操作紀錄" if kind == "reflog_contains_action" else "已完成指定的分支切換"
                return True, success_msg, ""
            if kind == "reflog_contains_action":
                exp = str(expected)
                if "amend" in exp:
                    return False, "", "在操作紀錄中未找到 commit (amend)，請使用 git commit --amend 更新最新 commit"
                if "rebase" in exp:
                    return False, "", "在操作紀錄中未找到完成的 rebase 紀錄，請使用 git rebase"
                if "cherry-pick" in exp:
                    return False, "", "在操作紀錄中未找到 cherry-pick 紀錄，請使用 git cherry-pick 套用修正"
                return False, "", f"在 reflog 中尚未看到指定操作（{exp}）"
            return False, "", f"在 reflog 中尚未看到切換至 {expected} 的紀錄"

        if kind == "patch_equivalent":
            expected_pid, _ = self._resolve_ref(str(expected), baseline)
            revision, _ = self._resolve_ref(str(check.get("revision", "HEAD")), baseline)
            if revision is None:
                return False, "", "缺少指定的 commit 版本"
            diff_res = self.git.run(repo, "diff-tree", "-p", revision, check=False)
            if diff_res.returncode != 0 or not diff_res.stdout:
                return False, "", "最新 commit 沒有包含任何程式碼 diff"
            if expected_pid is None:
                return True, "Commit 變更內容已包含修正", ""
            pid_res = self.git.run(repo, "patch-id", "--stable", check=False, input_text=diff_res.stdout + "\n")
            actual_pid = pid_res.stdout.split()[0] if pid_res.stdout else ""
            if actual_pid == expected_pid:
                return True, "Commit patch 與來源修正一致", ""
            return False, "", "最新 commit 的變更內容（patch）與指定修正 commit 不一致，請使用 cherry-pick 套用"

        raise ValueError(f"不支援的檢查類型：{kind}")

    def _evaluate_file_in_commit(
        self, repo: Path, check: dict, baseline: dict[str, str], exam: bool
    ) -> tuple[bool, str, str]:
        kind = check["type"]
        wanted = check["file"].replace("\\", "/")
        revision, _ = self._resolve_ref(str(check.get("revision", "HEAD")), baseline)
        if revision is None:
            return False, "", "缺少基準版本"

        after_sha = ""
        if check.get("after"):
            after_ref, _ = self._resolve_ref(str(check["after"]), baseline)
            if after_ref:
                after_res = self.git.run(repo, "rev-parse", "--verify", after_ref, check=False)
                if after_res.returncode == 0:
                    after_sha = after_res.stdout.strip()

        rev_res = self.git.run(repo, "rev-parse", "--verify", revision, check=False)
        rev_sha = rev_res.stdout.strip() if rev_res.returncode == 0 else ""

        if kind == "file_in_commit":
            if after_sha and rev_sha == after_sha:
                hint = "" if exam else f"；請先將 {wanted} 加入 staging area 並建立 commit"
                return False, "", f"尚未建立新的 commit（目前仍停在起始 commit）{hint}"
            names = [
                n.replace("\\", "/")
                for n in self.git.run(
                    repo, "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", revision
                ).stdout.splitlines()
            ]
            if wanted in names:
                return True, "Commit 包含狀態正確", ""
            actual_files = ", ".join(names[:4]) if names else "（無檔案）"
            return False, "", f"最新 commit 尚未包含 {wanted}（目前包含：{actual_files}）"

        # file_not_in_commit
        if after_sha:
            if rev_sha and rev_sha == after_sha:
                return True, "Commit 包含狀態正確", ""
            log_res = self.git.run(
                repo, "log", "--format=", "--name-only", f"{after_sha}..{revision}", check=False
            )
            if log_res.returncode == 0:
                names = [n.strip().replace("\\", "/") for n in log_res.stdout.splitlines() if n.strip()]
                if wanted in names:
                    hint = "" if exam else "；請重設本題或撤回 commit 後重新只提交指定檔案"
                    return False, "", f"{wanted} 已被加入新建立的 commit，違反題目限制{hint}"
                return True, "Commit 包含狀態正確", ""

        names = [
            n.replace("\\", "/")
            for n in self.git.run(
                repo, "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", revision
            ).stdout.splitlines()
        ]
        if wanted not in names:
            return True, "Commit 包含狀態正確", ""
        return False, "", f"最新 commit 不應包含 {wanted}"

    def _evaluate_working_tree_file(self, repo: Path, check: dict, exam: bool) -> tuple[bool, str, str]:
        kind = check["type"]
        wanted = check["file"].replace("\\", "/")
        rows = self.git.run(repo, "status", "--porcelain=v1").stdout.splitlines()
        matched_rows = [row for row in rows if len(row) >= 4 and self._normalize_porcelain_path(row) == wanted]

        if kind == "untracked_file":
            if any(row.startswith("?? ") for row in matched_rows):
                return True, "Working tree 狀態正確", ""
            if matched_rows:
                hint = "" if exam else f"（可用 git restore --staged {wanted} 取消暫存）"
                return False, "", f"{wanted} 已被加入 staging area，必須維持未追蹤狀態{hint}"
            if not self._safe_file(repo, wanted).exists():
                return False, "", f"找不到 {wanted}，不可刪除或移動該檔案"
            return False, "", f"{wanted} 已被追蹤或提交，必須保持為未追蹤檔案"

        # working_tree_modified: require unstaged modification (" M"), not staged ("M ") or deleted (" D"/"D ")
        if any(row[0] == " " and row[1] == "M" for row in matched_rows):
            return True, "Working tree 狀態正確", ""
        if matched_rows:
            row = matched_rows[0]
            if row[0] == "M":
                hint = "" if exam else f"（可用 git restore --staged {wanted} 取消暫存）"
                return False, "", f"{wanted} 目前已進入 staging area（暫存區），必須保留在 working tree（工作目錄）{hint}"
            if "D" in row[:2]:
                return False, "", f"{wanted} 已被刪除，請還原並保留原本的未提交修改"
        return False, "", f"{wanted} 目前沒有未提交的修改（可能已被錯誤提交或還原）"

    @staticmethod
    def _safe_file(repo: Path, relative: str) -> Path:
        root = repo.resolve()
        candidate = (root / relative).resolve()
        if candidate != root and root not in candidate.parents:
            raise ValueError("檔案路徑超出 repository")
        return candidate
