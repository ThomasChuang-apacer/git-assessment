from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path


class TemplateBuilder:
    VERSION = 6
    _validation_cache: dict[tuple[str, bool], tuple[int, tuple[bool, str]]] = {}

    def __init__(self, root: Path):
        self.root = root

    def ensure(self) -> None:
        if self.validate(deep=False)[0]:
            return
        stage = self.root.with_name(f".{self.root.name}-stage-{uuid.uuid4().hex}")
        backup = self.root.with_name(f".{self.root.name}-backup-{uuid.uuid4().hex}")
        builder = TemplateBuilder(stage)
        builder._build()
        valid, message = builder.validate(deep=True)
        if not valid:
            shutil.rmtree(stage, ignore_errors=True)
            raise RuntimeError(f"新題目環境驗證失敗：{message}")
        old_moved = False
        try:
            if self.root.exists():
                os.replace(self.root, backup)
                old_moved = True
            os.replace(stage, self.root)
        except Exception:
            if self.root.exists() and self.root != stage:
                shutil.rmtree(self.root, ignore_errors=True)
            if old_moved and backup.exists():
                os.replace(backup, self.root)
            raise
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)

    def _build(self) -> None:
        self.root.mkdir(parents=True)
        for number in range(1, 7):
            getattr(self, f"_task{number:02d}")()
        manifest = {"version": self.VERSION, "tasks": [f"task{number:02d}" for number in range(1, 7)]}
        (self.root / f".ready-v{self.VERSION}.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def validate(self, deep: bool = True) -> tuple[bool, str]:
        marker = self.root / f".ready-v{self.VERSION}.json"
        try:
            marker_stamp = marker.stat().st_mtime_ns
            cache_key = (str(self.root.resolve()).casefold(), deep)
            cached = self._validation_cache.get(cache_key)
            if cached and cached[0] == marker_stamp:
                return cached[1]
            manifest = json.loads(marker.read_text(encoding="utf-8"))
            if manifest.get("version") != self.VERSION:
                return False, "題目版本不符"
            for number in range(1, 7):
                task_id = f"task{number:02d}"
                repo = self.root / task_id / "repo"
                if not (repo / ".git").is_dir():
                    return False, f"{task_id} 缺少 .git"
                if not deep:
                    continue
                if self._git(repo, "rev-parse", "--verify", "HEAD") == "":
                    return False, f"{task_id} 缺少 HEAD"
                self._git(repo, "rev-parse", "--verify", "refs/tags/assessment-start")
                self._git(repo, "fsck", "--no-dangling")
            if not deep:
                for remote_path in (self.root / "task04" / "origin.git", self.root / "task05" / "origin.git"):
                    if not remote_path.is_dir():
                        return False, f"{remote_path.parent.name} 缺少本機 origin"
                outcome = (True, "6 個任務已通過快速啟動檢查")
                self._validation_cache[cache_key] = (marker_stamp, outcome)
                return outcome
            self._git(self.root / "task04" / "repo", "rev-parse", "--verify", "refs/remotes/origin/main")
            task04_repo = self.root / "task04" / "repo"
            task04_origin = self.root / "task04" / "origin.git"
            tracked_main = self._git(task04_repo, "rev-parse", "refs/remotes/origin/main")
            remote_main = self._git(task04_origin, "rev-parse", "refs/heads/main")
            pending_main = self._git(task04_origin, "rev-parse", "refs/assessment/pending-main")
            if tracked_main != remote_main or remote_main == pending_main:
                return False, "task04 假遠端的初始／待更新 refs 不正確"
            self._git(self.root / "task06" / "repo", "rev-parse", "--verify", "refs/heads/fix/validation")
            task05_repo = self.root / "task05" / "repo"
            task05_origin = self.root / "task05" / "origin.git"
            remote_hotfix = self._git(task05_origin, "rev-parse", "refs/heads/hotfix/check-status")
            local_hotfix = self._git_result(task05_repo, "show-ref", "--verify", "refs/heads/hotfix/check-status")
            tracked_hotfix = self._git_result(
                task05_repo, "show-ref", "--verify", "refs/remotes/origin/hotfix/check-status"
            )
            task05_version = self._git(task05_repo, "config", "--get", "assessment.templateVersion")
            if not remote_hotfix or local_hotfix.returncode == 0 or tracked_hotfix.returncode == 0 or task05_version != "6":
                return False, "task05 假遠端分支不應在本機預先存在"
        except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
            return False, str(exc)
        outcome = (True, "6 個任務已通過完整性檢查" if deep else "6 個任務已通過快速啟動檢查")
        self._validation_cache[cache_key] = (marker_stamp, outcome)
        return outcome

    def _git(self, repo: Path, *args: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            shell=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr or completed.stdout)
        return completed.stdout.strip()

    def _git_result(self, repo: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=10, shell=False,
        )

    def _new_repo(self, task_id: str) -> Path:
        repo = self.root / task_id / "repo"
        repo.mkdir(parents=True)
        self._git(repo, "init", "-b", "main")
        self._git(repo, "config", "user.name", "Git Assessment")
        self._git(repo, "config", "user.email", "git-assessment@example.invalid")
        return repo

    @staticmethod
    def _write(repo: Path, relative: str, content: str) -> None:
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _commit_all(self, repo: Path, message: str) -> None:
        self._git(repo, "add", "-A")
        self._git(repo, "commit", "-m", message)

    def _task01(self) -> None:
        repo = self._new_repo("task01")
        self._write(repo, "src/config.py", 'CONFIG_PATH = "config/default.json"\n')
        self._write(repo, "README.md", "# Demo Service\n\nBasic project documentation.\n")
        self._commit_all(repo, "Initial project")
        self._git(repo, "tag", "assessment-start")
        self._write(repo, "src/config.py", 'CONFIG_PATH = "config/production.json"\n')
        self._write(repo, "README.md", "# Demo Service\n\nBasic project documentation.\n\nTODO: finish deployment notes.\n")
        self._write(repo, "debug.log", "temporary debug output\n")

    def _task02(self) -> None:
        repo = self._new_repo("task02")
        self._write(repo, "src/config.py", 'CONFIG_PATH = "config/default.json"\n')
        self._write(
            repo,
            "tests/test_config.py",
            "def test_config_path():\n    # TODO: verify the production config path\n    assert True\n",
        )
        self._commit_all(repo, "Initial project")
        self._git(repo, "tag", "assessment-start")
        self._write(repo, "src/config.py", 'CONFIG_PATH = "config/production.json"\n')
        self._commit_all(repo, "Fix configuration loading")

    def _task03(self) -> None:
        repo = self._new_repo("task03")
        self._write(repo, "src/login.py", "LOGIN_TIMEOUT = 30\n\ndef login():\n    return LOGIN_TIMEOUT\n")
        self._commit_all(repo, "Initial login service")
        self._git(repo, "tag", "assessment-start")

    def _task04(self) -> None:
        task_root = self.root / "task04"
        repo = task_root / "repo"
        origin = task_root / "origin.git"
        repo.mkdir(parents=True)
        origin.mkdir(parents=True)
        self._git(repo, "init", "-b", "main")
        self._git(repo, "config", "user.name", "Git Assessment")
        self._git(repo, "config", "user.email", "git-assessment@example.invalid")
        subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
        self._write(repo, "src/login.py", "LOGIN_TIMEOUT = 30\nLOGIN_RETRY = 3\n")
        self._commit_all(repo, "Initial login service")
        self._git(repo, "tag", "assessment-start")
        initial_sha = self._git(repo, "rev-parse", "HEAD")
        self._git(repo, "remote", "add", "origin", "../origin.git")
        self._git(repo, "push", "-u", "origin", "main")
        self._git(repo, "switch", "-c", "feature/login-timeout")
        self._write(repo, "src/login.py", "LOGIN_TIMEOUT = 60\nLOGIN_RETRY = 3\n")
        self._commit_all(repo, "Update login timeout")
        self._git(repo, "switch", "main")
        self._write(repo, "src/login.py", "LOGIN_TIMEOUT = 45\nLOGIN_RETRY = 5\n")
        self._commit_all(repo, "Tune login defaults")
        self._git(repo, "push", "origin", "HEAD:refs/assessment/pending-main")
        self._git(repo, "reset", "--hard", initial_sha)
        self._git(repo, "switch", "feature/login-timeout")

    def _task05(self) -> None:
        repo = self._new_repo("task05")
        task_root = self.root / "task05"
        origin = task_root / "origin.git"
        origin.mkdir(parents=True)
        subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
        self._write(repo, "notes/development.md", "# Development Notes\n\nStable notes.\n")
        self._write(repo, "src/status.py", 'STATUS = "ok"\n')
        self._commit_all(repo, "Initial project")
        self._git(repo, "tag", "assessment-start")
        self._git(repo, "remote", "add", "origin", "../origin.git")
        self._git(repo, "push", "-u", "origin", "main")
        self._git(repo, "switch", "-c", "hotfix/check-status", "assessment-start")
        self._write(repo, "src/status.py", 'STATUS = "healthy"\n')
        self._commit_all(repo, "Update status check")
        self._git(repo, "push", "-u", "origin", "hotfix/check-status")
        self._git(repo, "switch", "-c", "feature/login-timeout", "assessment-start")
        self._git(repo, "branch", "-D", "hotfix/check-status")
        self._git(repo, "update-ref", "-d", "refs/remotes/origin/hotfix/check-status")
        self._git(repo, "config", "assessment.templateVersion", "6")
        self._write(
            repo,
            "notes/development.md",
            "# Development Notes\n\nStable notes.\n\nDRAFT: investigate login timeout behavior.\n",
        )

    def _task06(self) -> None:
        repo = self._new_repo("task06")
        self._write(repo, "src/validator.py", "def is_valid(value):\n    return value is not None\n")
        self._commit_all(repo, "Initial validator")
        self._git(repo, "tag", "assessment-start")
        self._git(repo, "switch", "-c", "fix/validation")
        self._write(
            repo,
            "src/validator.py",
            "def is_valid(value):\n    return value is not None and value.strip() != \"\"\n",
        )
        self._commit_all(repo, "Reject empty validation values")
        self._git(repo, "switch", "-c", "feature/login-timeout", "assessment-start")
