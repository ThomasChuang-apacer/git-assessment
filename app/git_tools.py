from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitError(RuntimeError):
    pass


@dataclass(frozen=True)
class GitResult:
    returncode: int
    stdout: str
    stderr: str


class GitRunner:
    def __init__(self, timeout: int = 5):
        self.timeout = timeout

    def run(
        self,
        repo: Path,
        *args: str,
        check: bool = True,
        env: dict[str, str] | None = None,
    ) -> GitResult:
        if not repo.exists():
            raise GitError("Repository 不存在")
        try:
            completed = subprocess.run(
                ["git", "-C", str(repo), *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                shell=False,
                env=env,
            )
        except FileNotFoundError as exc:
            raise GitError("找不到 Git，請確認 Git 已安裝並加入 PATH") from exc
        except subprocess.TimeoutExpired as exc:
            raise GitError("Git 檢查逾時，請稍後再試") from exc

        # Preserve leading spaces because `git status --porcelain` uses both
        # status columns positionally (for example: " M README.md").
        result = GitResult(
            completed.returncode,
            completed.stdout.rstrip("\r\n"),
            completed.stderr.rstrip("\r\n"),
        )
        if check and result.returncode != 0:
            detail = result.stderr or result.stdout or "未知錯誤"
            raise GitError(detail)
        return result

    def available(self) -> tuple[bool, str]:
        try:
            completed = subprocess.run(
                ["git", "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                shell=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False, "找不到 Git"
        return completed.returncode == 0, completed.stdout.strip() or completed.stderr.strip()
