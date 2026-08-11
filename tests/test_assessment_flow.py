from __future__ import annotations

import json
import shutil
import subprocess
import os
import threading
from pathlib import Path

import pytest

from app import create_app


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    if check and completed.returncode != 0:
        raise AssertionError(completed.stderr or completed.stdout)
    return completed


def workspace_path(service, result: dict) -> Path:
    return (service.data_root / result["workspace"]).resolve()


@pytest.fixture()
def assessment(tmp_path: Path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test",
            "TEMPLATE_ROOT": PROJECT_ROOT / "data" / "templates",
            "DATA_ROOT": tmp_path / "runtime",
            "QUESTIONS_PATH": PROJECT_ROOT / "questions" / "questions.json",
        }
    )
    service = app.extensions["assessment_service"]
    result = service.create_session("Test Candidate")
    return app, service, result


def test_home_and_session_pages(assessment):
    app, _, result = assessment
    client = app.test_client()
    assert client.get("/").status_code == 200
    overview = client.get(f"/assessment/{result['session_id']}")
    assert overview.status_code == 200
    assert "任務總覽" in overview.get_data(as_text=True)
    task = client.get(f"/assessment/{result['session_id']}/tasks/task01")
    assert task.status_code == 200
    assert "提交指定的修改" in task.get_data(as_text=True)
    summary = client.get(f"/assessment/{result['session_id']}/result")
    assert summary.status_code == 200
    assert "測驗結果摘要" in summary.get_data(as_text=True)
    assert "保存成 PNG" in summary.get_data(as_text=True)


def test_home_lists_saved_session_for_resume(assessment):
    app, service, result = assessment
    sessions = service.list_sessions()
    assert sessions[0]["session_id"] == result["session_id"]
    assert sessions[0]["completed_count"] == 0
    assert sessions[0]["available"] is True

    page = app.test_client().get("/").get_data(as_text=True)
    assert "繼續上次測驗" in page
    assert result["session_id"] in page


def test_task02_shows_copyable_expected_code(assessment):
    app, _, result = assessment
    page = app.test_client().get(
        f"/assessment/{result['session_id']}/tasks/task02"
    ).get_data(as_text=True)
    assert "複製程式碼" in page
    assert "from src.config import CONFIG_PATH" in page
    assert "CONFIG_PATH == &#34;config/production.json&#34;" in page


def test_initial_states_do_not_pass(assessment):
    _, service, result = assessment
    for question in service.questions:
        outcome = service.check_task(result["session_id"], question["id"])
        assert outcome["completed"] is False, question["id"]


def test_task01_rejects_more_than_one_new_commit(assessment):
    _, service, result = assessment
    repo = service.task_repo(result, "task01")
    git(repo, "commit", "--allow-empty", "-m", "Prepare configuration change")
    git(repo, "add", "src/config.py")
    git(repo, "commit", "-m", "Fix configuration loading")

    outcome = service.check_task(result["session_id"], "task01")
    checks = {item["check_id"]: item["passed"] for item in outcome["checks"]}
    assert outcome["completed"] is False
    assert checks["single-commit"] is False


def test_task03_requires_timeout_inside_commit_and_clean_tree(assessment):
    _, service, result = assessment
    repo = service.task_repo(result, "task03")
    git(repo, "switch", "-c", "feature/login-timeout")
    git(repo, "commit", "--allow-empty", "-m", "Update login timeout")
    (repo / "src/login.py").write_text(
        "LOGIN_TIMEOUT = 60\n\ndef login():\n    return LOGIN_TIMEOUT\n", encoding="utf-8"
    )

    outcome = service.check_task(result["session_id"], "task03")
    checks = {item["check_id"]: item["passed"] for item in outcome["checks"]}
    assert outcome["completed"] is False
    assert checks["timeout"] is False
    assert checks["clean"] is False


def test_reference_solutions_pass_all_tasks(assessment):
    _, service, result = assessment
    session_id = result["session_id"]

    repo = service.task_repo(result, "task01")
    git(repo, "add", "src/config.py")
    git(repo, "commit", "-m", "Fix configuration loading")
    assert service.check_task(session_id, "task01")["completed"]

    repo = service.task_repo(result, "task02")
    (repo / "tests/test_config.py").write_text(
        "from src.config import CONFIG_PATH\n\n\ndef test_config_path():\n"
        "    assert CONFIG_PATH == \"config/production.json\"\n",
        encoding="utf-8",
    )
    git(repo, "add", "tests/test_config.py")
    git(repo, "commit", "--amend", "--no-edit")
    assert service.check_task(session_id, "task02")["completed"]

    repo = service.task_repo(result, "task03")
    git(repo, "switch", "-c", "feature/login-timeout")
    (repo / "src/login.py").write_text("LOGIN_TIMEOUT = 60\n\ndef login():\n    return LOGIN_TIMEOUT\n", encoding="utf-8")
    git(repo, "add", "src/login.py")
    git(repo, "commit", "-m", "Update login timeout")
    assert service.check_task(session_id, "task03")["completed"]

    repo = service.task_repo(result, "task04")
    service.simulate_remote_update(session_id, "task04")
    git(repo, "fetch", "origin")
    rebase = git(repo, "rebase", "origin/main", check=False)
    assert rebase.returncode != 0
    (repo / "src/login.py").write_text("LOGIN_TIMEOUT = 60\nLOGIN_RETRY = 5\n", encoding="utf-8")
    git(repo, "add", "src/login.py")
    git(repo, "-c", "core.editor=true", "rebase", "--continue")
    assert service.check_task(session_id, "task04")["completed"]

    repo = service.task_repo(result, "task05")
    git(repo, "stash", "push", "-m", "temporary assessment work")
    git(repo, "fetch", "origin")
    git(repo, "switch", "--track", "origin/hotfix/check-status")
    git(repo, "switch", "feature/login-timeout")
    git(repo, "stash", "pop")
    assert service.check_task(session_id, "task05")["completed"]

    repo = service.task_repo(result, "task06")
    fix_sha = git(repo, "rev-parse", "fix/validation").stdout.strip()
    git(repo, "cherry-pick", fix_sha)
    final = service.check_task(session_id, "task06")
    assert final["completed"]
    assert final["session"]["completed_at"] is not None


def test_reset_only_replaces_selected_task(assessment):
    _, service, result = assessment
    session_id = result["session_id"]
    task01 = service.task_repo(result, "task01")
    task02 = service.task_repo(result, "task02")
    marker = task02 / "keep-me.txt"
    marker.write_text("preserve", encoding="utf-8")
    git(task01, "add", "src/config.py")
    git(task01, "commit", "-m", "Fix configuration loading")

    service.reset_task(session_id, "task01")

    refreshed = service.get_session(session_id)
    assert service.task_state(refreshed, "task01")["status"] == "not_started"
    assert marker.exists()
    assert git(service.task_repo(refreshed, "task01"), "log", "-1", "--format=%s").stdout.strip() == "Initial project"


def test_failed_reset_keeps_original_repository(assessment, monkeypatch):
    _, service, result = assessment
    session_id = result["session_id"]
    repo = service.task_repo(result, "task03")
    original_head = git(repo, "rev-parse", "HEAD").stdout.strip()
    real_replace = os.replace

    def block_task_swap(source, destination):
        if Path(source).resolve() == repo.resolve():
            raise PermissionError("simulated folder lock")
        return real_replace(source, destination)

    monkeypatch.setattr("app.services.os.replace", block_task_swap)
    with pytest.raises(ValueError, match="正被 Terminal"):
        service.reset_task(session_id, "task03")

    assert (repo / ".git").exists()
    assert git(repo, "rev-parse", "HEAD").stdout.strip() == original_head
    assert not list(workspace_path(service, result).glob(".reset-stage-*"))


def test_candidate_keeps_only_current_and_previous(assessment):
    _, service, first = assessment
    first_id = first["session_id"]
    second = service.create_session("Test Candidate")
    third = service.create_session("Test Candidate")

    sessions = [item for item in service.list_sessions(20) if item["candidate_name"] == "Test Candidate"]
    assert len(sessions) == 2
    assert {item["session_id"] for item in sessions} == {second["session_id"], third["session_id"]}
    with pytest.raises(KeyError):
        service.get_session(first_id)

    current = workspace_path(service, service.get_session(third["session_id"]))
    previous = workspace_path(service, service.get_session(second["session_id"]))
    assert current.parts[-2:] == (third["candidate_id"], "current")
    assert previous.parts[-2:] == (third["candidate_id"], "previous")
    assert service.task_repo(service.get_session(third["session_id"]), "task02") == current / "task02"


def test_candidate_ids_do_not_collide_and_ignore_case():
    from app.services import AssessmentService

    assert AssessmentService._new_candidate_id("王小明") != AssessmentService._new_candidate_id("李小華")
    assert AssessmentService._new_candidate_id("Example User") == AssessmentService._new_candidate_id("example user")


def test_post_requires_local_token(assessment):
    app, service, result = assessment
    client = app.test_client()
    endpoint = f"/api/sessions/{result['session_id']}/tasks/task01/check"
    assert client.post(endpoint).status_code == 403
    headers = {
        "X-Git-Assessment-Token": app.config["LOCAL_API_TOKEN"],
        "X-Git-Assessment-Request-ID": "same-request-1234",
    }
    response = client.post(endpoint, headers=headers)
    assert response.status_code == 200
    assert client.post(endpoint, headers=headers).status_code == 200
    refreshed = service.get_session(result["session_id"])
    assert service.task_state(refreshed, "task01")["check_attempts"] == 1


def test_shutdown_requires_token_and_calls_registered_server(assessment):
    app, _, _ = assessment
    stopped = threading.Event()
    app.extensions["git_assessment_shutdown"] = stopped.set
    client = app.test_client()

    assert client.post("/api/shutdown").status_code == 403
    response = client.post(
        "/api/shutdown",
        headers={
            "X-Git-Assessment-Token": app.config["LOCAL_API_TOKEN"],
            "X-Git-Assessment-Request-ID": "shutdown-request-1234",
        },
    )

    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    assert stopped.wait(timeout=2)


def test_task02_rejects_working_tree_only_content(assessment):
    _, service, result = assessment
    repo = service.task_repo(result, "task02")
    expected = (
        "from src.config import CONFIG_PATH\n\n\n"
        "def test_config_path():\n    assert CONFIG_PATH == \"config/production.json\"\n"
    )
    (repo / "tests/test_config.py").write_text(expected, encoding="utf-8")
    git(repo, "add", "tests/test_config.py")
    git(repo, "commit", "--amend", "--no-edit")
    (repo / "tests/test_config.py").write_text(expected + "# uncommitted\n", encoding="utf-8")

    outcome = service.check_task(result["session_id"], "task02")
    checks = {item["check_id"]: item["passed"] for item in outcome["checks"]}
    assert outcome["completed"] is False
    assert checks["test-content"] is True
    assert checks["clean"] is False


def test_task06_missing_source_branch_is_not_accepted(assessment):
    _, service, result = assessment
    repo = service.task_repo(result, "task06")
    fix_sha = git(repo, "rev-parse", "fix/validation").stdout.strip()
    git(repo, "cherry-pick", fix_sha)
    git(repo, "branch", "-D", "fix/validation")

    outcome = service.check_task(result["session_id"], "task06")
    checks = {item["check_id"]: item for item in outcome["checks"]}
    assert outcome["completed"] is False
    assert checks["not-merged"]["passed"] is False
    assert "無法完成檢查" in checks["not-merged"]["message"]


def test_task04_remote_update_requires_fetch(assessment):
    app, service, result = assessment
    repo = service.task_repo(result, "task04")
    origin = workspace_path(service, result) / ".origins" / "task04.git"
    tracked_before = git(repo, "rev-parse", "origin/main").stdout.strip()
    remote_before = git(origin, "rev-parse", "refs/heads/main").stdout.strip()
    pending = git(origin, "rev-parse", "refs/assessment/pending-main").stdout.strip()
    assert tracked_before == remote_before
    assert pending != remote_before

    page = app.test_client().get(
        f"/assessment/{result['session_id']}/tasks/task04"
    ).get_data(as_text=True)
    assert "模擬遠端 main 更新" in page

    outcome = service.simulate_remote_update(result["session_id"], "task04")
    assert outcome["updated"] is True
    assert git(origin, "rev-parse", "refs/heads/main").stdout.strip() == pending
    assert git(repo, "rev-parse", "origin/main").stdout.strip() == tracked_before

    git(repo, "fetch", "origin")
    assert git(repo, "rev-parse", "origin/main").stdout.strip() == pending


def test_task05_fetches_remote_only_hotfix_with_checkout(assessment):
    _, service, result = assessment
    repo = service.task_repo(result, "task05")
    assert git(repo, "show-ref", "--verify", "refs/heads/hotfix/check-status", check=False).returncode != 0
    assert git(repo, "show-ref", "--verify", "refs/remotes/origin/hotfix/check-status", check=False).returncode != 0

    git(repo, "stash", "push", "-m", "temporary assessment work")
    git(repo, "fetch", "origin")
    remote_hotfix = git(repo, "rev-parse", "origin/hotfix/check-status").stdout.strip()
    git(repo, "checkout", "-b", "hotfix/check-status", "origin/hotfix/check-status")
    assert git(repo, "rev-parse", "HEAD").stdout.strip() == remote_hotfix
    git(repo, "switch", "feature/login-timeout")
    git(repo, "stash", "pop")

    outcome = service.check_task(result["session_id"], "task05")
    assert outcome["completed"] is True
    checks = {item["check_id"]: item["passed"] for item in outcome["checks"]}
    assert checks["hotfix-updated"] is True
    assert checks["stash-empty"] is True


def test_new_session_copy_failure_preserves_current(assessment, monkeypatch):
    _, service, first = assessment
    first_workspace = workspace_path(service, first)
    first_head = git(service.task_repo(first, "task01"), "rev-parse", "HEAD").stdout.strip()
    real_copy = service._copy_task
    calls = 0

    def fail_on_third(question, session_dir):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("simulated disk failure")
        return real_copy(question, session_dir)

    monkeypatch.setattr(service, "_copy_task", fail_on_third)
    with pytest.raises(OSError, match="simulated disk failure"):
        service.create_session("Test Candidate")

    refreshed = service.get_session(first["session_id"])
    assert workspace_path(service, refreshed) == first_workspace
    assert refreshed["slot"] == "current"
    assert git(service.task_repo(refreshed, "task01"), "rev-parse", "HEAD").stdout.strip() == first_head
    assert not list(first_workspace.parent.glob(".session-stage-*"))


def test_new_session_swap_failure_rolls_back_current(assessment, monkeypatch):
    _, service, first = assessment
    first_workspace = workspace_path(service, first)
    first_head = git(service.task_repo(first, "task01"), "rev-parse", "HEAD").stdout.strip()
    real_replace = os.replace

    def fail_stage_install(source, destination):
        if Path(source).name.startswith(".session-stage-") and Path(destination).name == "current":
            raise PermissionError("simulated slot failure")
        return real_replace(source, destination)

    monkeypatch.setattr("app.services.os.replace", fail_stage_install)
    monkeypatch.setattr("app.services.time.sleep", lambda _delay: None)
    with pytest.raises(PermissionError, match="simulated slot failure"):
        service.create_session("Test Candidate")

    refreshed = service.get_session(first["session_id"])
    assert refreshed["slot"] == "current"
    assert workspace_path(service, refreshed) == first_workspace
    assert not (first_workspace.parent / "previous").exists()
    assert git(service.task_repo(refreshed, "task01"), "rev-parse", "HEAD").stdout.strip() == first_head


def test_replace_with_retry_recovers_from_transient_permission_error(assessment, monkeypatch, tmp_path):
    _, service, _ = assessment
    source = tmp_path / "source.txt"
    destination = tmp_path / "destination.txt"
    source.write_text("ready", encoding="utf-8")
    real_replace = os.replace
    attempts = 0
    waits = []

    def transient_replace(source_path, destination_path):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError("temporarily busy")
        return real_replace(source_path, destination_path)

    monkeypatch.setattr("app.services.os.replace", transient_replace)
    monkeypatch.setattr("app.services.time.sleep", waits.append)

    service._replace_with_retry(source, destination)

    assert attempts == 3
    assert waits == [0.1, 0.2]
    assert destination.read_text(encoding="utf-8") == "ready"


def test_create_session_reports_busy_workspace(assessment, monkeypatch):
    app, service, _ = assessment

    def fail_create_session(_candidate_name):
        raise PermissionError("workspace busy")

    monkeypatch.setattr(service, "create_session", fail_create_session)
    response = app.test_client().post(
        "/api/sessions",
        data={
            "_confirm": "create",
            "_api_token": app.config["LOCAL_API_TOKEN"],
            "candidate_name": "Test Candidate",
        },
    )

    assert response.status_code == 409
    assert "VS Code" in response.get_json()["error"]


def test_incomplete_corrupt_task_is_backed_up_and_repaired(assessment):
    _, service, result = assessment
    workspace = workspace_path(service, result)
    corrupt = workspace / "task04" / ".git"
    shutil.rmtree(corrupt, onerror=service._remove_readonly)

    service._repair_incomplete_corrupt_tasks()

    repaired = service.get_session(result["session_id"])
    assert git(service.task_repo(repaired, "task04"), "status", "--porcelain").returncode == 0
    assert service.task_state(repaired, "task04")["status"] == "not_started"
    assert any(item["type"] == "task_auto_repaired" for item in repaired["events"])
    assert list((service.quarantine_root / "workspaces").glob("task04-corrupt-task04-*"))


def test_runtime_records_survive_copy_from_legacy_absolute_path(tmp_path: Path):
    source_data = tmp_path / "source" / "runtime"
    source_app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test",
            "TEMPLATE_ROOT": PROJECT_ROOT / "data" / "templates",
            "DATA_ROOT": source_data,
            "QUESTIONS_PATH": PROJECT_ROOT / "questions" / "questions.json",
        }
    )
    source_service = source_app.extensions["assessment_service"]
    original = source_service.create_session("Portable Candidate")
    original_workspace = workspace_path(source_service, original)

    result_path = source_service.result_path(original["session_id"])
    legacy = json.loads(result_path.read_text(encoding="utf-8"))
    legacy["schema_version"] = 2
    legacy["workspace"] = str(original_workspace)
    result_path.write_text(json.dumps(legacy, ensure_ascii=False, indent=2), encoding="utf-8")

    moved_data = tmp_path / "moved" / "runtime"
    shutil.copytree(source_data, moved_data)
    moved_app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test",
            "TEMPLATE_ROOT": PROJECT_ROOT / "data" / "templates",
            "DATA_ROOT": moved_data,
            "QUESTIONS_PATH": PROJECT_ROOT / "questions" / "questions.json",
        }
    )
    moved_service = moved_app.extensions["assessment_service"]
    migrated = moved_service.get_session(original["session_id"])
    moved_workspace = workspace_path(moved_service, migrated)

    assert not Path(migrated["workspace"]).is_absolute()
    assert moved_workspace != original_workspace
    assert moved_data.resolve() in moved_workspace.parents
    assert moved_service.task_repo(migrated, "task01").exists()
    stored = json.loads(moved_service.result_path(original["session_id"]).read_text(encoding="utf-8"))
    assert stored["schema_version"] == 3
    assert stored["workspace"] == migrated["workspace"]

    task04 = moved_service.task_repo(migrated, "task04")
    origin_url = git(task04, "remote", "get-url", "origin").stdout.strip()
    assert Path(origin_url).resolve() == moved_workspace / ".origins" / "task04.git"
