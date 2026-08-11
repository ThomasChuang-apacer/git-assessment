from __future__ import annotations

from pathlib import Path

from .git_tools import GitError, GitRunner


class CheckEngine:
    def __init__(self, git: GitRunner):
        self.git = git

    def run_all(self, repo: Path, checks: list[dict]) -> list[dict]:
        return [self.run_one(repo, check) for check in checks]

    def run_one(self, repo: Path, check: dict) -> dict:
        try:
            passed, success, failure = self._evaluate(repo, check)
            message = success if passed else failure
        except (GitError, OSError, ValueError) as exc:
            passed = False
            message = f"無法完成檢查：{exc}"
        return {
            "check_id": check["id"],
            "passed": passed,
            "label": check["label"],
            "message": message,
            "required": check.get("required", True),
        }

    def _evaluate(self, repo: Path, check: dict) -> tuple[bool, str, str]:
        kind = check["type"]
        expected = check.get("expected")

        if kind == "current_branch":
            actual = self.git.run(repo, "branch", "--show-current").stdout
            return actual == expected, f"目前位於 {actual}", "目前所在分支不符合任務要求"

        if kind == "branch_exists":
            result = self.git.run(repo, "show-ref", "--verify", f"refs/heads/{expected}", check=False)
            return result.returncode == 0, "指定分支存在", "尚未找到指定分支"

        if kind == "commit_message":
            revision = check.get("revision", "HEAD")
            actual = self.git.run(repo, "log", "-1", "--format=%s", revision).stdout
            match = check.get("match", "exact")
            passed = actual == expected if match == "exact" else str(expected) in actual
            return passed, "Commit message 正確", "尚未找到符合要求的 commit message"

        if kind == "commit_count":
            actual = int(self.git.run(repo, "rev-list", "--count", check["range"]).stdout)
            target = int(expected)
            return actual == target, f"Commit 數量正確（{actual}）", "Commit 數量不符合任務限制"

        if kind == "file_contains":
            path = self._safe_file(repo, check["file"])
            actual = path.read_text(encoding="utf-8") if path.exists() else ""
            return str(expected) in actual, "檔案內容正確", "檔案內容尚未符合要求"

        if kind in {"file_at_revision_contains", "file_at_revision_not_contains"}:
            result = self.git.run(repo, "show", f"{check['revision']}:{check['file']}", check=False)
            contains = result.returncode == 0 and str(expected) in result.stdout
            passed = contains if kind == "file_at_revision_contains" else result.returncode == 0 and not contains
            if kind == "file_at_revision_contains":
                return passed, "Commit 中的檔案內容正確", "指定修改尚未包含在 commit 中"
            return passed, "指定分支未包含本題修改", "指定分支包含了不應出現的修改"

        if kind in {"file_in_commit", "file_not_in_commit"}:
            revision = check.get("revision", "HEAD")
            names = self.git.run(
                repo, "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", revision
            ).stdout.splitlines()
            present = check["file"] in names
            passed = present if kind == "file_in_commit" else not present
            return passed, "Commit 包含狀態正確", "Commit 包含的檔案不符合要求"

        if kind in {"working_tree_modified", "untracked_file"}:
            rows = self.git.run(repo, "status", "--porcelain=v1").stdout.splitlines()
            wanted = check["file"].replace("\\", "/")
            if kind == "untracked_file":
                passed = any(row.startswith("?? ") and row[3:].replace("\\", "/") == wanted for row in rows)
            else:
                passed = any(
                    not row.startswith("?? ") and row[3:].replace("\\", "/") == wanted
                    for row in rows
                )
            return passed, "Working tree 狀態正確", "指定修改未保留在 working tree"

        if kind == "working_tree_clean":
            passed = self.git.run(repo, "status", "--porcelain=v1").stdout == ""
            return passed, "Working tree 乾淨", "Working tree 仍有未處理的修改"

        if kind == "stash_count":
            output = self.git.run(repo, "stash", "list").stdout
            actual = len(output.splitlines()) if output else 0
            return actual == int(expected), "暫存紀錄狀態正確", "暫存紀錄尚未完成清理"

        if kind == "no_operation_in_progress":
            git_dir = Path(self.git.run(repo, "rev-parse", "--absolute-git-dir").stdout)
            markers = ["rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD"]
            passed = not any((git_dir / marker).exists() for marker in markers)
            return passed, "沒有進行中的 Git 操作", "Git 操作尚未完成或取消"

        if kind in {"is_ancestor", "not_is_ancestor"}:
            result = self.git.run(
                repo, "merge-base", "--is-ancestor", check["ancestor"], check["descendant"], check=False
            )
            if result.returncode not in {0, 1}:
                detail = result.stderr or result.stdout or "指定的 revision 不存在"
                raise GitError(detail)
            is_ancestor = result.returncode == 0
            passed = is_ancestor if kind == "is_ancestor" else not is_ancestor
            return passed, "Commit 關係符合要求", "Commit 關係尚未符合要求"

        if kind == "no_merge_commit":
            output = self.git.run(repo, "rev-list", "--merges", check["range"]).stdout
            return output == "", "沒有多餘的 merge commit", "偵測到不符合限制的 merge commit"

        if kind == "reflog_contains":
            output = self.git.run(repo, "reflog", "--format=%gs").stdout
            return str(expected) in output, "已完成指定的分支切換", "尚未看到完整的分支切換紀錄"

        raise ValueError(f"不支援的檢查類型：{kind}")

    @staticmethod
    def _safe_file(repo: Path, relative: str) -> Path:
        root = repo.resolve()
        candidate = (root / relative).resolve()
        if candidate != root and root not in candidate.parents:
            raise ValueError("檔案路徑超出 repository")
        return candidate
