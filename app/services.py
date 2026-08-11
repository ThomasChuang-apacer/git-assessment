from __future__ import annotations

import json
import hashlib
import logging
import os
import re
import shutil
import stat
import time
import unicodedata
import uuid
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .check_engine import CheckEngine
from .git_tools import GitRunner
from .template_builder import TemplateBuilder


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class AssessmentService:
    SESSION_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
    SCHEMA_VERSION = 3

    def __init__(self, questions_path: Path, template_root: Path, data_root: Path, git_timeout: int = 5):
        self.questions_path = questions_path
        self.template_root = template_root
        self.data_root = data_root
        self.workspace_root = data_root / "workspaces"
        self.result_root = data_root / "results"
        self.archive_root = data_root / "archive"
        self.quarantine_root = data_root / "quarantine"
        self.git = GitRunner(git_timeout)
        self.checker = CheckEngine(self.git)
        self.template_builder = TemplateBuilder(self.template_root)
        self.questions: list[dict] = []
        self._locks_guard = threading.Lock()
        self._locks: dict[str, threading.RLock] = {}
        self._request_cache: dict[str, object] = {}
        self.log = logging.getLogger("git_assessment.service")

    def prepare(self) -> None:
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.result_root.mkdir(parents=True, exist_ok=True)
        self.archive_root.mkdir(parents=True, exist_ok=True)
        self.quarantine_root.mkdir(parents=True, exist_ok=True)
        self.questions = self._load_questions()
        git_ok, _ = self.git.available()
        if git_ok:
            self.template_builder.ensure()
        self._validate_questions()
        self._normalize_storage()
        self._repair_incomplete_corrupt_tasks()

    def environment_status(self) -> dict:
        git_ok, git_message = self.git.available()
        templates_ok, template_message = self.template_builder.validate(deep=False) if git_ok else (False, "Git 無法使用")
        health = self.runtime_health()
        return {
            "git_ok": git_ok,
            "git_message": git_message,
            "templates_ok": templates_ok,
            "template_message": template_message,
            "runtime_issue_count": health["issue_count"],
            "ready": git_ok and templates_ok,
        }

    def idempotent(self, operation_key: str, request_id: str | None, callback):
        """Run a browser action once when the same request is retried."""
        if not request_id or not re.fullmatch(r"[A-Za-z0-9._-]{8,100}", request_id):
            return callback()
        key = f"{operation_key}:{request_id}"
        with self._locked(f"request:{key}"):
            if key in self._request_cache:
                return json.loads(json.dumps(self._request_cache[key], ensure_ascii=False))
            outcome = callback()
            self._request_cache[key] = outcome
            if len(self._request_cache) > 256:
                self._request_cache.pop(next(iter(self._request_cache)))
            return json.loads(json.dumps(outcome, ensure_ascii=False))

    def create_session(self, candidate_name: str) -> dict:
        display_name = candidate_name.strip()
        if not display_name:
            raise ValueError("請輸入姓名或識別代碼")
        candidate_id = self._candidate_id(display_name)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        session_id = f"{stamp}-{uuid.uuid4().hex[:6]}"
        with self._locked(f"candidate:{candidate_id.casefold()}"):
            candidate_root = self._candidate_root(candidate_id)
            stage = candidate_root / f".session-stage-{uuid.uuid4().hex}"
            try:
                stage.mkdir(parents=True)
                for question in self.questions:
                    self._copy_task(question, stage)
                self._validate_workspace(stage)
                current = candidate_root / "current"
                result = {
                    "schema_version": self.SCHEMA_VERSION,
                    "session_id": session_id,
                    "candidate_id": candidate_id,
                    "candidate_key": self._candidate_key(display_name),
                    "candidate_name": display_name,
                    "slot": "current",
                    "workspace": self._workspace_reference(candidate_id, "current"),
                    "started_at": now_iso(),
                    "completed_at": None,
                    "tasks": [
                        {"task_id": q["id"], "status": "not_started", "completed_at": None,
                         "check_attempts": 0, "last_checks": []}
                        for q in self.questions
                    ],
                    "events": [{"type": "session_started", "timestamp": now_iso()}],
                }
                self._install_staged_session(candidate_id, stage, result)
                return result
            finally:
                if stage.exists():
                    shutil.rmtree(stage, onerror=self._remove_readonly)

    def get_session(self, session_id: str) -> dict:
        self._validate_session_id(session_id)
        path = self.result_root / f"{session_id}.json"
        if not path.exists():
            raise KeyError("找不到考試紀錄")
        result = json.loads(path.read_text(encoding="utf-8"))
        return self._validate_result(result)

    def list_sessions(self, limit: int = 8) -> list[dict]:
        sessions: list[dict] = []
        for path in self.result_root.glob("*.json"):
            try:
                result = self._validate_result(
                    self._migrate_result(json.loads(path.read_text(encoding="utf-8")))
                )
                tasks = result.get("tasks", [])
                completed_count = sum(1 for task in tasks if task.get("status") == "completed")
                workspace = self._workspace_path(result)
                health = self._session_health(result)
                events = result.get("events", [])
                last_activity = events[-1].get("timestamp", result.get("started_at", "")) if events else result.get("started_at", "")
                sessions.append(
                    {
                        "session_id": result["session_id"],
                        "candidate_name": result.get("candidate_name", result.get("candidate_id", "Unknown")),
                        "started_at": result.get("started_at", ""),
                        "last_activity_at": last_activity,
                        "completed_at": result.get("completed_at"),
                        "completed_count": completed_count,
                        "total": len(tasks),
                        "available": workspace.exists() and workspace.is_dir(),
                        "healthy": health["healthy"],
                        "health_issues": health["issues"],
                    }
                )
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                continue
        sessions.sort(key=lambda item: item["last_activity_at"], reverse=True)
        return sessions[:limit]

    def delete_session(self, session_id: str) -> None:
        """Permanently remove one active result and its matching workspace."""
        initial = self.get_session(session_id)
        candidate_id = initial["candidate_id"]
        candidate_key = initial["candidate_key"]
        with self._locked(f"candidate:{candidate_id.casefold()}"), self._locked(f"session:{session_id}"):
            result = self.get_session(session_id)
            if result["candidate_id"].casefold() != candidate_id.casefold():
                raise ValueError("考試紀錄與考生資料不符")
            result_path = self.result_path(session_id)
            workspace = self._workspace_path(result)
            workspace_root = self.workspace_root.resolve()
            if workspace_root not in workspace.parents or workspace == workspace_root:
                raise ValueError("拒絕刪除不安全的工作目錄")

            try:
                if workspace.exists():
                    shutil.rmtree(workspace, onerror=self._remove_readonly)
                result_path.unlink()
            except OSError as exc:
                raise ValueError("無法刪除測驗紀錄，請先關閉正在使用該題目的 Terminal 或編輯器後再試一次") from exc

            remaining = self._candidate_records(candidate_key)
            remaining.sort(key=lambda item: item[1].get("started_at", ""), reverse=True)
            if remaining:
                try:
                    self._assign_candidate_slots(candidate_id, remaining[:2])
                except (OSError, ValueError) as exc:
                    self.log.warning("紀錄已刪除，但剩餘 workspace 將於下次啟動時整理：%s", exc)
            else:
                candidate_root = (self.workspace_root / candidate_id).resolve()
                try:
                    candidate_root.rmdir()
                except OSError:
                    pass

    def get_question(self, task_id: str) -> dict:
        for question in self.questions:
            if question["id"] == task_id:
                return question
        raise KeyError("找不到題目")

    def task_state(self, result: dict, task_id: str) -> dict:
        for task in result["tasks"]:
            if task["task_id"] == task_id:
                return task
        raise KeyError("找不到題目狀態")

    def task_repo(self, result: dict, task_id: str) -> Path:
        self.get_question(task_id)
        workspace = self._safe_existing_workspace(result)
        direct_repo = (workspace / task_id).resolve()
        legacy_repo = (direct_repo / "repo").resolve()
        repo = direct_repo if (direct_repo / ".git").exists() else legacy_repo
        if workspace not in repo.parents or not (repo / ".git").exists():
            raise ValueError("此題的 repository 無法讀取")
        return repo

    def mark_opened(self, session_id: str, task_id: str) -> dict:
        with self._locked(f"session:{session_id}"):
            result = self.get_session(session_id)
            task = self.task_state(result, task_id)
            if task["status"] == "not_started":
                task["status"] = "in_progress"
                result["events"].append({"type": "task_opened", "task_id": task_id, "timestamp": now_iso()})
                self._save_result(result)
            return result

    def check_task(self, session_id: str, task_id: str) -> dict:
        with self._locked(f"task:{session_id}:{task_id}"), self._locked(f"session:{session_id}"):
            result = self.get_session(session_id)
            question = self.get_question(task_id)
            task = self.task_state(result, task_id)
            repo = self.task_repo(result, task_id)
            checks = self.checker.run_all(repo, question["checks"])
            completed = all(item["passed"] for item in checks if item["required"])

            task["check_attempts"] += 1
            task["last_checks"] = checks
            task["status"] = "completed" if completed else "in_progress"
            task["completed_at"] = now_iso() if completed else None
            result["events"].append(
                {"type": "task_checked", "task_id": task_id, "passed": completed, "timestamp": now_iso()}
            )
            result["completed_at"] = (
                result["completed_at"] or now_iso()
                if all(item["status"] == "completed" for item in result["tasks"])
                else None
            )
            self._save_result(result)
            return {"completed": completed, "checks": checks, "session": result}

    def reset_task(self, session_id: str, task_id: str) -> dict:
        with self._locked(f"task:{session_id}:{task_id}"), self._locked(f"session:{session_id}"):
            result = self.get_session(session_id)
            question = self.get_question(task_id)
            workspace = self._safe_existing_workspace(result)
            task_dir = (workspace / task_id).resolve()
            if workspace not in task_dir.parents or task_dir.name != task_id:
                raise ValueError("拒絕重設不安全的路徑")
            origin_dir = (workspace / ".origins" / f"{task_id}.git").resolve()
            self._reset_task_atomically(question, workspace, task_dir, origin_dir)

            task = self.task_state(result, task_id)
            task.update(status="not_started", completed_at=None, check_attempts=0, last_checks=[])
            result["completed_at"] = None
            result["events"].append({"type": "task_reset", "task_id": task_id, "timestamp": now_iso()})
            self._save_result(result)
            return result

    def simulate_remote_update(self, session_id: str, task_id: str) -> dict:
        if task_id != "task04":
            raise ValueError("此題沒有模擬遠端更新")
        with self._locked(f"task:{session_id}:{task_id}"), self._locked(f"session:{session_id}"):
            result = self.get_session(session_id)
            workspace = self._safe_existing_workspace(result)
            origin = (workspace / ".origins" / "task04.git").resolve()
            if workspace not in origin.parents or not origin.is_dir():
                raise ValueError("第四題的假遠端無法讀取")
            pending_result = self.git.run(
                origin, "rev-parse", "--verify", "refs/assessment/pending-main", check=False
            )
            if pending_result.returncode != 0:
                raise ValueError("此測驗建立於舊版題目，請先重設第四題再使用模擬遠端")
            pending = pending_result.stdout
            current = self.git.run(origin, "rev-parse", "--verify", "refs/heads/main").stdout
            updated = current != pending
            if updated:
                self.git.run(origin, "update-ref", "refs/heads/main", pending, current)
                result["events"].append({
                    "type": "remote_update_simulated", "task_id": task_id,
                    "from": current, "to": pending, "timestamp": now_iso(),
                })
                self._save_result(result)
            return {"updated": updated, "before": current, "after": pending}

    def remote_update_status(self, result: dict, task_id: str) -> dict:
        if task_id != "task04":
            return {"available": False}
        workspace = self._safe_existing_workspace(result)
        repo = self.task_repo(result, task_id)
        origin = workspace / ".origins" / "task04.git"
        pending = self.git.run(origin, "rev-parse", "--verify", "refs/assessment/pending-main", check=False)
        if pending.returncode != 0:
            return {
                "available": False,
                "message": "此測驗建立於舊版第四題。請使用「重設本題」套用新版假遠端情境。",
            }
        remote = self.git.run(origin, "rev-parse", "--verify", "refs/heads/main").stdout
        tracked = self.git.run(repo, "rev-parse", "--verify", "refs/remotes/origin/main").stdout
        return {
            "available": True,
            "remote_updated": remote == pending.stdout,
            "fetched": tracked == pending.stdout,
        }

    def task_compatibility(self, result: dict, task_id: str) -> dict:
        if task_id != "task05":
            return {"compatible": True}
        workspace = self._safe_existing_workspace(result)
        repo = self.task_repo(result, task_id)
        origin = workspace / ".origins" / "task05.git"
        if not origin.is_dir():
            return {
                "compatible": False,
                "message": "此測驗建立於舊版第五題。請使用「重設本題」套用遠端限定分支情境。",
            }
        remote = self.git.run(
            origin, "rev-parse", "--verify", "refs/heads/hotfix/check-status", check=False
        )
        version = self.git.run(repo, "config", "--get", "assessment.templateVersion", check=False)
        compatible = remote.returncode == 0 and version.returncode == 0 and version.stdout == "5"
        return {
            "compatible": compatible,
            "message": "此測驗建立於舊版第五題。請使用「重設本題」套用遠端限定分支情境。" if not compatible else "",
        }

    def _reset_task_atomically(
        self,
        question: dict,
        workspace: Path,
        task_dir: Path,
        origin_dir: Path,
    ) -> None:
        token = uuid.uuid4().hex
        stage_root = workspace / f".reset-stage-{token}"
        backup_root = workspace / f".reset-backup-{token}"
        staged_task = stage_root / question["id"]
        staged_origin = stage_root / ".origins" / f"{question['id']}.git"
        backup_task = backup_root / question["id"]
        backup_origin = backup_root / f"{question['id']}.git"
        old_task_moved = False
        old_origin_moved = False
        new_task_installed = False
        new_origin_installed = False
        success = False

        try:
            stage_root.mkdir()
            self._copy_task(question, stage_root)
            if not (staged_task / ".git").exists():
                raise RuntimeError("重設用 repository 建立不完整")

            backup_root.mkdir()
            if task_dir.exists():
                try:
                    os.replace(task_dir, backup_task)
                except PermissionError as exc:
                    raise ValueError(
                        "此題資料夾正被 Terminal、VS Code 或其他程式使用。"
                        "請先離開該資料夾並關閉占用程式，再重新重設。"
                    ) from exc
                old_task_moved = True

            if origin_dir.exists():
                try:
                    os.replace(origin_dir, backup_origin)
                except PermissionError as exc:
                    raise ValueError("此題的本機 remote 正被使用，請稍後再重設。") from exc
                old_origin_moved = True

            os.replace(staged_task, task_dir)
            new_task_installed = True
            if staged_origin.exists():
                origin_dir.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staged_origin, origin_dir)
                new_origin_installed = True
            self._repair_workspace_remotes(workspace)
            success = True
        finally:
            if not success:
                if new_task_installed and task_dir.exists():
                    shutil.rmtree(task_dir, onerror=self._remove_readonly)
                if old_task_moved and backup_task.exists() and not task_dir.exists():
                    os.replace(backup_task, task_dir)
                if new_origin_installed and origin_dir.exists():
                    shutil.rmtree(origin_dir, onerror=self._remove_readonly)
                if old_origin_moved and backup_origin.exists() and not origin_dir.exists():
                    origin_dir.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(backup_origin, origin_dir)

            if stage_root.exists():
                shutil.rmtree(stage_root, onerror=self._remove_readonly)
            if backup_root.exists() and (success or not any(backup_root.iterdir())):
                shutil.rmtree(backup_root, onerror=self._remove_readonly)

        if success and backup_root.exists():
            shutil.rmtree(backup_root, onerror=self._remove_readonly)

    def open_task_folder(self, session_id: str, task_id: str) -> None:
        result = self.get_session(session_id)
        repo = self.task_repo(result, task_id)
        if os.name == "nt":
            os.startfile(repo)  # type: ignore[attr-defined]
            return
        raise OSError("目前版本只支援在 Windows 開啟資料夾")

    def result_path(self, session_id: str) -> Path:
        self._validate_session_id(session_id)
        return (self.result_root / f"{session_id}.json").resolve()

    def _copy_task(self, question: dict, session_dir: Path) -> None:
        source = (self.template_root / question["repository_template"]).resolve()
        source_repo = source / "repo"
        target_repo = (session_dir / question["id"]).resolve()
        if self.template_root.resolve() not in source.parents:
            raise ValueError("Template 路徑不安全")
        # Sample hooks are documentation generated by `git init`; they are not
        # needed by the assessment and account for most small-file copy overhead.
        shutil.copytree(source_repo, target_repo, ignore=shutil.ignore_patterns("*.sample"))
        source_origin = source / "origin.git"
        if source_origin.exists():
            origin = session_dir / ".origins" / f"{question['id']}.git"
            origin.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source_origin, origin, ignore=shutil.ignore_patterns("*.sample"))
            self.git.run(target_repo, "remote", "set-url", "origin", str(origin.resolve()))

    def _normalize_storage(self) -> None:
        """Validate and migrate active data without permanently deleting anomalies."""
        grouped: dict[str, list[tuple[Path, dict]]] = {}
        for result_path in self.result_root.glob("*.json"):
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
                result = self._migrate_result(result)
                self._validate_result(result)
                candidate_id = result["candidate_id"]
                workspace = self._workspace_path(result)
                if not workspace.exists():
                    self._quarantine_file(result_path, "missing-workspace")
                    continue
                grouped.setdefault(result["candidate_key"], []).append((result_path, result))
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                self.log.warning("隔離無效結果 %s: %s", result_path, exc)
                self._quarantine_file(result_path, "invalid-result")

        for records in grouped.values():
            records.sort(key=lambda item: item[1].get("started_at", ""), reverse=True)
            keep = records[:2]
            protected = {self._workspace_path(item[1]) for item in keep}
            for result_path, result in records[2:]:
                self._archive_record(result_path, result, protected)
            self._assign_candidate_slots(keep[0][1]["candidate_id"], keep)

    def _assign_candidate_slots(self, candidate_id: str, records: list[tuple[Path, dict]]) -> None:
        candidate_root = (self.workspace_root / candidate_id).resolve()
        if self.workspace_root.resolve() not in candidate_root.parents:
            raise ValueError("考生工作目錄無效")
        candidate_root.mkdir(parents=True, exist_ok=True)
        for orphan in candidate_root.glob(".migrate-*"):
            if orphan.is_dir():
                self._quarantine_directory(orphan, "orphan-migration")
        staged: list[tuple[Path | None, Path, Path, dict]] = []

        for index, (result_path, result) in enumerate(records):
            target = candidate_root / ("current" if index == 0 else "previous")
            source = self._workspace_path(result)
            if source == target.resolve():
                staged.append((None, target, result_path, result))
                continue
            stage = candidate_root / f".migrate-{uuid.uuid4().hex}"
            self._move_workspace(source, stage)
            staged.append((stage, target, result_path, result))

        occupied = {target.resolve() for stage, target, _, _ in staged if stage is None}
        for slot in (candidate_root / "current", candidate_root / "previous"):
            if slot.exists() and slot.resolve() not in occupied:
                self._quarantine_directory(slot, "unindexed-workspace")

        for stage, target, result_path, result in staged:
            if stage is not None:
                self._move_workspace(stage, target)
            result["workspace"] = self._workspace_reference(candidate_id, target.name)
            result["slot"] = target.name
            self._save_result(result)
            self._repair_workspace_remotes(target)

    def _install_staged_session(self, candidate_id: str, stage: Path, result: dict) -> None:
        """Commit a prepared session and roll back the slot exchange on failure."""
        candidate_root = self._candidate_root(candidate_id)
        current = candidate_root / "current"
        previous = candidate_root / "previous"
        records = self._candidate_records(result["candidate_key"])
        old_current = next((item for item in records if item[1].get("slot") == "current"), None)
        old_previous = next((item for item in records if item[1].get("slot") == "previous"), None)
        transaction_id = uuid.uuid4().hex
        archive_workspace = self.archive_root / "workspaces" / candidate_id / transaction_id
        archive_result = self.archive_root / "results" / f"{transaction_id}.json"
        manifest = candidate_root / f".transaction-{transaction_id}.json"
        backups = {path: path.read_bytes() for path, _ in records if path.exists()}
        new_result_path = self.result_root / f"{result['session_id']}.json"
        archived_previous = False
        current_moved = False
        stage_installed = False
        try:
            manifest.write_text(json.dumps({"session_id": result["session_id"], "phase": "prepared"}), encoding="utf-8")
            if old_previous:
                archive_result.parent.mkdir(parents=True, exist_ok=True)
                self._replace_with_retry(old_previous[0], archive_result)
            if previous.exists():
                archive_workspace.parent.mkdir(parents=True, exist_ok=True)
                self._replace_with_retry(previous, archive_workspace)
                archived_previous = True
            if current.exists():
                self._replace_with_retry(current, previous)
                current_moved = True
            self._replace_with_retry(stage, current)
            stage_installed = True
            self._repair_workspace_remotes(current)
            if old_current:
                old_current[1]["workspace"] = self._workspace_reference(candidate_id, "previous")
                old_current[1]["slot"] = "previous"
                self._save_result(old_current[1])
            self._save_result(result)
            manifest.unlink(missing_ok=True)
        except Exception:
            if stage_installed and current.exists():
                self._quarantine_directory(current, "failed-new-session")
            if current_moved and previous.exists() and not current.exists():
                self._replace_with_retry(previous, current)
            if archived_previous and archive_workspace.exists() and not previous.exists():
                self._replace_with_retry(archive_workspace, previous)
            for path, content in backups.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                temp = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
                temp.write_bytes(content)
                self._replace_with_retry(temp, path)
            new_result_path.unlink(missing_ok=True)
            manifest.unlink(missing_ok=True)
            raise

    def _replace_with_retry(
        self, source: Path, destination: Path, attempts: int = 5, initial_delay: float = 0.1
    ) -> None:
        """Retry a Windows rename when another process briefly holds a workspace handle."""
        for attempt in range(attempts):
            try:
                os.replace(source, destination)
                return
            except PermissionError:
                if attempt + 1 >= attempts:
                    raise
                delay = initial_delay * (2**attempt)
                self.log.warning(
                    "路徑暫時被占用，%.1f 秒後重試移動 %s -> %s",
                    delay,
                    source,
                    destination,
                )
                time.sleep(delay)

    def _repair_workspace_remotes(self, workspace: Path) -> None:
        for question in self.questions:
            direct_repo = workspace / question["id"]
            legacy_repo = direct_repo / "repo"
            repo = direct_repo if (direct_repo / ".git").exists() else legacy_repo
            direct_origin = workspace / ".origins" / f"{question['id']}.git"
            legacy_origin = direct_repo / "origin.git"
            origin = direct_origin if direct_origin.exists() else legacy_origin
            if (repo / ".git").exists() and origin.exists():
                self.git.run(repo, "remote", "set-url", "origin", str(origin.resolve()))

    def runtime_health(self) -> dict:
        sessions = []
        issue_count = 0
        for path in self.result_root.glob("*.json"):
            try:
                result = self._validate_result(json.loads(path.read_text(encoding="utf-8")))
                health = self._session_health(result)
                sessions.append({"session_id": result["session_id"], **health})
                issue_count += len(health["issues"])
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                sessions.append({"session_id": path.stem, "healthy": False, "issues": [str(exc)]})
                issue_count += 1
        leftovers = list(self.workspace_root.rglob(".reset-stage-*")) + list(self.workspace_root.rglob(".transaction-*.json"))
        issue_count += len(leftovers)
        return {"healthy": issue_count == 0, "issue_count": issue_count, "sessions": sessions}

    def session_task_health(self, result: dict) -> dict[str, dict]:
        workspace = self._safe_existing_workspace(result)
        health = {}
        for question in self.questions:
            ok, message = self._task_repo_health(workspace, question["id"], deep=False, probe_git=True)
            health[question["id"]] = {"healthy": ok, "message": message}
        return health

    def repair_task(self, session_id: str, task_id: str, confirm_completed: bool = False) -> dict:
        with self._locked(f"task:{session_id}:{task_id}"), self._locked(f"session:{session_id}"):
            result = self.get_session(session_id)
            task = self.task_state(result, task_id)
            if task["status"] == "completed" and not confirm_completed:
                raise ValueError("此題已完成；修復會重設作答，請先進行考官確認")
            workspace = self._safe_existing_workspace(result)
            question = self.get_question(task_id)
            self._repair_corrupt_task(workspace, question)
            task.update(status="not_started", completed_at=None, check_attempts=0, last_checks=[])
            result["completed_at"] = None
            result["events"].append({"type": "task_repaired", "task_id": task_id, "timestamp": now_iso()})
            self._save_result(result)
            return result

    def _session_health(self, result: dict) -> dict:
        issues: list[str] = []
        try:
            workspace = self._safe_existing_workspace(result)
        except ValueError as exc:
            return {"healthy": False, "issues": [str(exc)]}
        for question in self.questions:
            ok, message = self._task_repo_health(workspace, question["id"], deep=False, probe_git=False)
            if not ok:
                issues.append(f"{question['id']}: {message}")
        return {"healthy": not issues, "issues": issues}

    def _task_repo_health(
        self, workspace: Path, task_id: str, deep: bool = True, probe_git: bool = True
    ) -> tuple[bool, str]:
        task_dir = workspace / task_id
        repo = task_dir if (task_dir / ".git").is_dir() else task_dir / "repo"
        if not (repo / ".git").is_dir():
            return False, "缺少完整的 .git repository"
        if not probe_git:
            return True, "正常"
        result = self.git.run(repo, "rev-parse", "--is-inside-work-tree", check=False)
        if result.returncode != 0 or result.stdout != "true":
            return False, result.stderr or "Git repository 無法辨識"
        if deep:
            result = self.git.run(repo, "fsck", "--no-dangling", check=False)
            if result.returncode != 0:
                return False, result.stderr or result.stdout or "git fsck 失敗"
        return True, "正常"

    def _validate_workspace(self, workspace: Path) -> None:
        for question in self.questions:
            ok, message = self._task_repo_health(workspace, question["id"], deep=True)
            if not ok:
                raise RuntimeError(f"{question['id']} 建立不完整：{message}")

    def _repair_incomplete_corrupt_tasks(self) -> None:
        for result_path in list(self.result_root.glob("*.json")):
            try:
                result = self.get_session(result_path.stem)
                workspace = self._safe_existing_workspace(result)
                changed = False
                for question in self.questions:
                    task = self.task_state(result, question["id"])
                    ok, message = self._task_repo_health(
                        workspace, question["id"], deep=False, probe_git=False
                    )
                    if ok or task["status"] == "completed":
                        continue
                    self._repair_corrupt_task(workspace, question)
                    task.update(status="not_started", completed_at=None, check_attempts=0, last_checks=[])
                    result["events"].append({
                        "type": "task_auto_repaired", "task_id": question["id"],
                        "reason": message, "timestamp": now_iso(),
                    })
                    changed = True
                    self.log.warning("已備份並重建 %s/%s: %s", result["session_id"], question["id"], message)
                if changed:
                    result["completed_at"] = None
                    self._save_result(result)
            except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError) as exc:
                self.log.error("Workspace 健康修復失敗 %s: %s", result_path, exc)

    def _repair_corrupt_task(self, workspace: Path, question: dict) -> None:
        task_id = question["id"]
        stage = workspace / f".repair-stage-{uuid.uuid4().hex}"
        task_dir = workspace / task_id
        origin_dir = workspace / ".origins" / f"{task_id}.git"
        stage.mkdir()
        try:
            self._copy_task(question, stage)
            ok, message = self._task_repo_health(stage, task_id, deep=True)
            if not ok:
                raise RuntimeError(message)
            if task_dir.exists():
                self._quarantine_directory(task_dir, f"corrupt-{task_id}")
            if origin_dir.exists():
                self._quarantine_directory(origin_dir, f"corrupt-{task_id}-origin")
            os.replace(stage / task_id, task_dir)
            staged_origin = stage / ".origins" / f"{task_id}.git"
            if staged_origin.exists():
                origin_dir.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staged_origin, origin_dir)
            self._repair_workspace_remotes(workspace)
        finally:
            if stage.exists():
                shutil.rmtree(stage, onerror=self._remove_readonly)

    def _candidate_records(self, candidate_key: str) -> list[tuple[Path, dict]]:
        records = []
        for path in self.result_root.glob("*.json"):
            try:
                result = self._migrate_result(json.loads(path.read_text(encoding="utf-8")))
                if result["candidate_key"] == candidate_key:
                    records.append((path, result))
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                continue
        return records

    def _archive_record(self, result_path: Path, result: dict, protected: set[Path] | None = None) -> None:
        destination = self.archive_root / "results" / result_path.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            destination = destination.with_name(f"{destination.stem}-{uuid.uuid4().hex[:8]}.json")
        workspace = self._workspace_path(result)
        if workspace.exists() and workspace not in (protected or set()) and self.workspace_root.resolve() in workspace.parents:
            self._quarantine_directory(workspace, "archived-workspace", root=self.archive_root / "workspaces")
        os.replace(result_path, destination)

    def _quarantine_file(self, path: Path, reason: str) -> Path:
        destination_dir = self.quarantine_root / "results"
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / f"{path.stem}-{reason}-{uuid.uuid4().hex[:8]}{path.suffix}"
        if path.exists():
            os.replace(path, destination)
        return destination

    def _quarantine_directory(self, path: Path, reason: str, root: Path | None = None) -> Path:
        destination_dir = root or (self.quarantine_root / "workspaces")
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / f"{path.name}-{reason}-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}"
        os.replace(path, destination)
        return destination

    def _migrate_result(self, result: dict) -> dict:
        if not isinstance(result, dict):
            raise ValueError("結果資料必須是 object")
        display_name = str(result.get("candidate_name") or result.get("candidate_id") or "").strip()
        if not display_name:
            raise ValueError("結果缺少考生名稱")
        candidate_id = str(result.get("candidate_id") or self._new_candidate_id(display_name))
        if not self.SESSION_PATTERN.fullmatch(candidate_id):
            candidate_id = self._new_candidate_id(display_name)
        result["schema_version"] = self.SCHEMA_VERSION
        result["candidate_id"] = candidate_id
        result["candidate_key"] = self._candidate_key(display_name)
        result["candidate_name"] = display_name
        slot = result.get("slot")
        if slot not in {"current", "previous"}:
            legacy_workspace = Path(str(result.get("workspace", "")))
            slot = legacy_workspace.name if legacy_workspace.name in {"current", "previous"} else "current"
        result["slot"] = slot
        # Workspace references are stored relative to runtime so the complete
        # application folder can be copied to another computer or location.
        # Absolute paths from schema v2 and earlier are deliberately ignored:
        # a copied package must never continue reading the original folder.
        result["workspace"] = self._workspace_reference(candidate_id, slot)
        result.setdefault("events", [])
        return result

    def _validate_result(self, result: dict) -> dict:
        required_strings = ("session_id", "candidate_id", "candidate_key", "candidate_name", "workspace", "started_at")
        if result.get("schema_version") != self.SCHEMA_VERSION:
            raise ValueError("結果資料版本不支援")
        if any(not isinstance(result.get(field), str) or not result[field] for field in required_strings):
            raise ValueError("結果資料缺少必要欄位")
        self._validate_session_id(result["session_id"])
        if not self.SESSION_PATTERN.fullmatch(result["candidate_id"]):
            raise ValueError("考生 ID 無效")
        if result.get("slot") not in {"current", "previous"}:
            raise ValueError("結果 slot 無效")
        workspace = Path(result["workspace"])
        expected_workspace = Path("workspaces") / result["candidate_id"] / result["slot"]
        if (
            workspace.is_absolute()
            or ".." in workspace.parts
            or workspace.as_posix().casefold() != expected_workspace.as_posix().casefold()
        ):
            raise ValueError("結果 workspace 路徑無效")
        if not isinstance(result.get("tasks"), list) or not isinstance(result.get("events"), list):
            raise ValueError("結果 tasks 或 events 格式錯誤")
        expected_ids = {question["id"] for question in self.questions}
        actual_ids = set()
        for task in result["tasks"]:
            if not isinstance(task, dict) or task.get("status") not in {"not_started", "in_progress", "completed"}:
                raise ValueError("題目狀態格式錯誤")
            task_id = task.get("task_id")
            if task_id not in expected_ids or task_id in actual_ids:
                raise ValueError("題目 ID 格式錯誤")
            actual_ids.add(task_id)
            if not isinstance(task.get("check_attempts"), int) or not isinstance(task.get("last_checks"), list):
                raise ValueError("題目檢查資料格式錯誤")
        if actual_ids != expected_ids:
            raise ValueError("結果題目數量不完整")
        return result

    def _candidate_root(self, candidate_id: str) -> Path:
        root = (self.workspace_root / candidate_id).resolve()
        if self.workspace_root.resolve() not in root.parents:
            raise ValueError("考生工作目錄無效")
        root.mkdir(parents=True, exist_ok=True)
        return root

    @contextmanager
    def _locked(self, key: str):
        with self._locks_guard:
            lock = self._locks.setdefault(key, threading.RLock())
        with lock:
            yield

    def _remove_workspace_path(self, workspace: Path) -> None:
        root = self.workspace_root.resolve()
        target = workspace.resolve()
        if root not in target.parents or target == root:
            raise ValueError("拒絕移除不安全的工作目錄")
        if target.exists():
            self._quarantine_directory(target, "removed-workspace")

    def _move_workspace(self, source: Path, target: Path) -> None:
        """Move a workspace without permanently deleting an occupied target."""
        if target.exists():
            self._quarantine_directory(target, "occupied-slot")
        os.replace(source, target)

    def _load_questions(self) -> list[dict]:
        if not self.questions_path.exists():
            raise RuntimeError("找不到題目設定檔")
        data = json.loads(self.questions_path.read_text(encoding="utf-8"))
        return sorted(data["questions"], key=lambda item: item["order"])

    def _validate_questions(self) -> None:
        supported = {
            "current_branch", "branch_exists", "commit_message", "commit_count", "file_contains",
            "file_at_revision_contains", "file_at_revision_not_contains", "file_in_commit", "file_not_in_commit",
            "working_tree_modified", "working_tree_clean", "untracked_file", "stash_count",
            "no_operation_in_progress", "is_ancestor", "not_is_ancestor", "no_merge_commit",
            "reflog_contains",
        }
        ids = [q["id"] for q in self.questions]
        orders = [q["order"] for q in self.questions]
        if len(ids) != len(set(ids)) or len(orders) != len(set(orders)):
            raise RuntimeError("題目 id 或順序重複")
        for question in self.questions:
            if not question.get("checks") or not any(c.get("required", True) for c in question["checks"]):
                raise RuntimeError(f"{question['id']} 沒有必要檢查項目")
            for check in question["checks"]:
                if check["type"] not in supported:
                    raise RuntimeError(f"不支援的檢查類型：{check['type']}")
                if "file" in check:
                    file_path = Path(check["file"])
                    if file_path.is_absolute() or ".." in file_path.parts:
                        raise RuntimeError(f"不安全的題目檔案路徑：{check['file']}")

    def _save_result(self, result: dict) -> None:
        self._validate_result(result)
        path = self.result_root / f"{result['session_id']}.json"
        temp = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, path)

    @staticmethod
    def _workspace_reference(candidate_id: str, slot: str) -> str:
        return (Path("workspaces") / candidate_id / slot).as_posix()

    def _workspace_path(self, result: dict) -> Path:
        root = self.data_root.resolve()
        workspace = (root / result["workspace"]).resolve()
        if root not in workspace.parents or workspace == root:
            raise ValueError("考試工作目錄無效")
        return workspace

    def _safe_existing_workspace(self, result: dict) -> Path:
        root = self.workspace_root.resolve()
        workspace = self._workspace_path(result)
        if root not in workspace.parents or not workspace.exists():
            raise ValueError("考試工作目錄無效")
        if workspace.name not in {"current", "previous"} or workspace.parent.name.casefold() != result["candidate_id"].casefold():
            raise ValueError("考試工作目錄與考生資料不符")
        return workspace

    def _validate_session_id(self, session_id: str) -> None:
        if not self.SESSION_PATTERN.fullmatch(session_id):
            raise ValueError("Session ID 無效")

    @staticmethod
    def _candidate_key(value: str) -> str:
        normalized = unicodedata.normalize("NFKC", value).strip().casefold()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _candidate_id(self, value: str) -> str:
        key = self._candidate_key(value)
        for path in self.result_root.glob("*.json"):
            try:
                existing = self._migrate_result(json.loads(path.read_text(encoding="utf-8")))
                if existing["candidate_key"] == key:
                    return existing["candidate_id"]
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                continue
        return self._new_candidate_id(value)

    @classmethod
    def _new_candidate_id(cls, value: str) -> str:
        normalized = unicodedata.normalize("NFKC", value)
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", normalized).strip(".-_")
        digest = hashlib.sha256(normalized.strip().casefold().encode("utf-8")).hexdigest()[:8]
        base = (slug or "candidate").lower()[:31]
        return f"{base}-{digest}"

    @classmethod
    def _slug(cls, value: str) -> str:
        """Backward-compatible alias used by older integrations."""
        return cls._new_candidate_id(value)

    @staticmethod
    def _remove_readonly(function, path: str, _exc_info) -> None:
        """Allow reset to remove read-only Git objects copied on Windows."""
        os.chmod(path, stat.S_IWRITE)
        function(path)
