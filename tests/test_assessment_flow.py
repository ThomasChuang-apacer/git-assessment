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


def test_session_form_error_uses_requested_response_format(assessment):
    app, _, _ = assessment
    client = app.test_client()
    data = {
        "_api_token": app.config["LOCAL_API_TOKEN"],
        "_confirm": "create",
        "candidate_name": "",
    }

    html = client.post("/api/sessions", data=data, headers={"Accept": "text/html"})
    assert html.status_code == 400
    assert html.mimetype == "text/html"

    json_response = client.post(
        "/api/sessions", data=data, headers={"Accept": "application/json"}
    )
    assert json_response.status_code == 400
    assert json_response.is_json


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


def test_task05_new_session_has_no_compatibility_warning(assessment):
    app, service, result = assessment
    compat = service.task_compatibility(result, "task05")
    assert compat["compatible"] is True
    assert compat["message"] == ""
    page = app.test_client().get(f"/assessment/{result['session_id']}/tasks/task05").get_data(as_text=True)
    assert "需要套用新版題目" not in page


def test_task01_rejects_initial_no_commit_and_readme_tampering(assessment):
    _, service, result = assessment
    session_id = result["session_id"]
    repo = service.task_repo(result, "task01")

    initial = service.check_task(session_id, "task01")
    initial_checks = {item["check_id"]: item["passed"] for item in initial["checks"]}
    assert initial_checks["config-in-commit"] is False

    git(repo, "add", "README.md")
    staged = service.check_task(session_id, "task01")
    staged_checks = {item["check_id"]: item["passed"] for item in staged["checks"]}
    assert staged_checks["readme-modified"] is False

    git(repo, "restore", "--staged", "README.md")
    git(repo, "add", "src/config.py", "README.md")
    git(repo, "commit", "-m", "Fix configuration loading")
    committed = service.check_task(session_id, "task01")
    committed_checks = {item["check_id"]: item["passed"] for item in committed["checks"]}
    assert committed["completed"] is False
    assert committed_checks["readme-not-commit"] is False


def test_task04_rejects_unfetched_bypass_and_conflict_markers(assessment):
    _, service, result = assessment
    session_id = result["session_id"]
    repo = service.task_repo(result, "task04")

    # Bypass without simulate_remote_update, fetch, or rebase
    (repo / "src/login.py").write_text("LOGIN_TIMEOUT = 60\nLOGIN_RETRY = 5\n", encoding="utf-8")
    git(repo, "add", "src/login.py")
    git(repo, "commit", "-m", "Fake retry edit")
    bypass = service.check_task(session_id, "task04")
    bypass_checks = {item["check_id"]: item["passed"] for item in bypass["checks"]}
    assert bypass["completed"] is False
    assert bypass_checks["remote-fetched"] is False
    assert bypass_checks["main-ancestor"] is False
    assert bypass_checks["used-rebase"] is False

    # Reset and try committing unresolved conflict markers
    service.reset_task(session_id, "task04")
    repo = service.task_repo(service.get_session(session_id), "task04")
    service.simulate_remote_update(session_id, "task04")
    git(repo, "fetch", "origin")
    rebase = git(repo, "rebase", "origin/main", check=False)
    assert rebase.returncode != 0
    git(repo, "add", "src/login.py")
    git(repo, "-c", "core.editor=true", "rebase", "--continue")

    markers = service.check_task(session_id, "task04")
    marker_checks = {item["check_id"]: item["passed"] for item in markers["checks"]}
    assert markers["completed"] is False
    assert marker_checks["no-conflict-markers"] is False
    assert marker_checks["no-stale-values"] is False


def test_tampered_tags_and_main_do_not_bypass_server_baseline(assessment):
    _, service, result = assessment
    session_id = result["session_id"]

    repo1 = service.task_repo(result, "task01")
    git(repo1, "commit", "--allow-empty", "-m", "Extra commit")
    git(repo1, "add", "src/config.py")
    git(repo1, "commit", "-m", "Fix configuration loading")
    git(repo1, "tag", "-f", "assessment-start", "HEAD~1")
    t1 = service.check_task(session_id, "task01")
    t1_checks = {item["check_id"]: item["passed"] for item in t1["checks"]}
    assert t1["completed"] is False
    assert t1_checks["single-commit"] is False

    repo3 = service.task_repo(result, "task03")
    git(repo3, "switch", "-c", "feature/login-timeout")
    git(repo3, "commit", "--allow-empty", "-m", "Extra commit")
    git(repo3, "branch", "-f", "main", "HEAD")
    (repo3 / "src/login.py").write_text("LOGIN_TIMEOUT = 60\n\ndef login():\n    return LOGIN_TIMEOUT\n", encoding="utf-8")
    git(repo3, "add", "src/login.py")
    git(repo3, "commit", "-m", "Update login timeout")
    t3 = service.check_task(session_id, "task03")
    t3_checks = {item["check_id"]: item["passed"] for item in t3["checks"]}
    assert t3["completed"] is False
    assert t3_checks["main-unchanged"] is False


def test_task02_and_task06_enforce_process_checks(assessment):
    _, service, result = assessment
    session_id = result["session_id"]

    # Task 02: reset --soft + new commit instead of amend should fail used-amend
    repo2 = service.task_repo(result, "task02")
    (repo2 / "tests/test_config.py").write_text(
        'from src.config import CONFIG_PATH\n\n\ndef test_config_path():\n    assert CONFIG_PATH == "config/production.json"\n',
        encoding="utf-8",
    )
    git(repo2, "reset", "--soft", "HEAD~1")
    git(repo2, "add", "tests/test_config.py")
    git(repo2, "commit", "-m", "Fix configuration loading")
    t2 = service.check_task(session_id, "task02")
    t2_checks = {item["check_id"]: item["passed"] for item in t2["checks"]}
    assert t2["completed"] is False
    assert t2_checks["used-amend"] is False

    # Task 06: manual copy + commit (not cherry-pick) fails used-cherry-pick; merge brings unrelated file
    repo6 = service.task_repo(result, "task06")
    (repo6 / "src/validator.py").write_text(
        'def is_valid(value):\n    return value is not None and value.strip() != ""\n',
        encoding="utf-8",
    )
    git(repo6, "add", "src/validator.py")
    git(repo6, "commit", "-m", "Reject empty validation values")
    t6_manual = service.check_task(session_id, "task06")
    t6_manual_checks = {item["check_id"]: item["passed"] for item in t6_manual["checks"]}
    assert t6_manual["completed"] is False
    assert t6_manual_checks["used-cherry-pick"] is False

    service.reset_task(session_id, "task06")
    repo6 = service.task_repo(service.get_session(session_id), "task06")
    git(repo6, "merge", "fix/validation")
    t6_merge = service.check_task(session_id, "task06")
    t6_merge_checks = {item["check_id"]: item["passed"] for item in t6_merge["checks"]}
    assert t6_merge["completed"] is False
    assert t6_merge_checks["no-unrelated-file"] is False
    assert t6_merge_checks["not-merged"] is False


def test_task05_requires_tracking_and_allows_intermediate_branch(assessment):
    _, service, result = assessment
    session_id = result["session_id"]
    repo = service.task_repo(result, "task05")

    git(repo, "stash", "push", "-m", "wip")
    git(repo, "fetch", "origin")
    git(repo, "checkout", "-b", "hotfix/check-status", "--no-track", "origin/hotfix/check-status")
    git(repo, "switch", "main")
    git(repo, "switch", "feature/login-timeout")
    git(repo, "stash", "pop")

    no_track = service.check_task(session_id, "task05")
    no_track_checks = {item["check_id"]: item["passed"] for item in no_track["checks"]}
    assert no_track["completed"] is False
    assert no_track_checks["hotfix-branch"] is False
    assert no_track_checks["switched-back"] is True

    git(repo, "branch", "--set-upstream-to=origin/hotfix/check-status", "hotfix/check-status")
    with_track = service.check_task(session_id, "task05")
    assert with_track["completed"] is True


def test_reset_preserves_attempts_and_completed_at_is_not_overwritten(assessment):
    _, service, result = assessment
    session_id = result["session_id"]

    service.check_task(session_id, "task01")
    service.reset_task(session_id, "task01")
    after_reset = service.task_state(service.get_session(session_id), "task01")
    assert after_reset["check_attempts"] == 1
    assert after_reset["reset_count"] == 1
    assert after_reset["status"] == "not_started"

    repo = service.task_repo(service.get_session(session_id), "task01")
    git(repo, "add", "src/config.py")
    git(repo, "commit", "-m", "Fix configuration loading")
    first_pass = service.check_task(session_id, "task01")
    assert first_pass["completed"] is True
    first_done = service.task_state(first_pass["session"], "task01")["completed_at"]
    assert first_done is not None

    # Force a slightly different timestamp check via second pass
    second_pass = service.check_task(session_id, "task01")
    second_state = service.task_state(second_pass["session"], "task01")
    assert second_state["completed_at"] == first_done
    assert second_state["check_attempts"] == 3


def test_api_status_codes_json_creation_and_host_protection(assessment):
    app, service, result = assessment
    client = app.test_client()
    token = app.config["LOCAL_API_TOKEN"]

    # Health includes instance identity
    health = client.get("/api/health").get_json()
    assert health["instance_id"] == service.instance_id
    assert health["project_root"] == str(service.project_root)

    # Host header check applies to GET as well
    assert client.get("/", headers={"Host": "evil.example.com"}).status_code == 403
    assert client.get("/api/health", headers={"Host": "evil.example.com"}).status_code == 403

    # Missing resources return 404 (not 400) and Chinese JSON errors
    missing_session = client.get("/api/sessions/does-not-exist/result", headers={"Accept": "application/json"})
    assert missing_session.status_code == 404
    assert "找不到" in missing_session.get_json()["error"]

    missing_task = client.post(
        f"/api/sessions/{result['session_id']}/tasks/task99/check",
        headers={"X-Git-Assessment-Token": token, "Accept": "application/json"},
    )
    assert missing_task.status_code == 404

    unknown_api = client.get("/api/nonexistent", headers={"Accept": "application/json"})
    assert unknown_api.status_code == 404
    assert "找不到" in unknown_api.get_json()["error"]

    bad_method = client.delete(
        "/api/health",
        headers={"X-Git-Assessment-Token": token, "Accept": "application/json"},
    )
    assert bad_method.status_code == 405
    assert "不支援" in bad_method.get_json()["error"]

    # Backend enforces 80-char candidate_name limit
    too_long = client.post(
        "/api/sessions",
        data={"_api_token": token, "_confirm": "create", "candidate_name": "A" * 81},
        headers={"Accept": "application/json"},
    )
    assert too_long.status_code == 400

    # JSON create returns 201 JSON with redirect_url
    created = client.post(
        "/api/sessions",
        data={"_api_token": token, "_confirm": "create", "candidate_name": "Json Candidate"},
        headers={"Accept": "application/json"},
    )
    assert created.status_code == 201
    payload = created.get_json()
    assert payload["session_id"]
    assert payload["redirect_url"].endswith(payload["session_id"])


def test_exam_mode_hints_integrity_and_examiner_pin_privacy(tmp_path: Path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "EXAMINER_PIN": "2468",
            "TEMPLATE_ROOT": PROJECT_ROOT / "data" / "templates",
            "DATA_ROOT": tmp_path / "runtime",
            "QUESTIONS_PATH": PROJECT_ROOT / "questions" / "questions.json",
        }
    )
    service = app.extensions["assessment_service"]
    token = app.config["LOCAL_API_TOKEN"]
    client = app.test_client()

    # Create exam session via POST form (sets active-session cookie on this client)
    created = client.post(
        "/api/sessions",
        data={"_api_token": token, "_confirm": "create", "candidate_name": "Exam User", "mode": "exam"},
        headers={"Accept": "application/json"},
    )
    assert created.status_code == 201
    sid = created.get_json()["session_id"]

    # Task page in exam mode shows exam_goal instead of step-by-step instructions
    task_html = client.get(f"/assessment/{sid}/tasks/task01").get_data(as_text=True)
    assert "任務目標" in task_html
    assert "先查看目前檔案狀態" not in task_html

    # Hint viewing records unique hint views
    h1 = client.post(
        f"/api/sessions/{sid}/tasks/task01/hint",
        json={"hint_index": 0},
        headers={"X-Git-Assessment-Token": token, "X-Git-Assessment-Request-ID": "hint-req-0001"},
    )
    assert h1.status_code == 200
    assert h1.get_json()["hints_used"] == 1
    h1_dup = client.post(
        f"/api/sessions/{sid}/tasks/task01/hint",
        json={"hint_index": 0},
        headers={"X-Git-Assessment-Token": token, "X-Git-Assessment-Request-ID": "hint-req-0002"},
    )
    assert h1_dup.get_json()["hints_used"] == 1

    # Integrity hash detects manual JSON tampering
    raw = service.get_session(sid)
    assert service.verify_result_integrity(raw) is True
    raw_tampered = dict(raw)
    raw_tampered["candidate_name"] = "Tampered Name"
    assert service.verify_result_integrity(raw_tampered) is False

    # Another browser without cookie cannot see Exam User on Home when PIN is set
    anon_client = app.test_client()
    anon_home = anon_client.get("/").get_data(as_text=True)
    assert "Exam User" not in anon_home
    assert "共用考場隱私保護" in anon_home

    # Protected examiner endpoints return 403 while locked
    assert anon_client.get(f"/api/sessions/{sid}/result", headers={"Accept": "application/json"}).status_code == 403
    assert (
        anon_client.post(
            f"/api/sessions/{sid}/delete",
            headers={"X-Git-Assessment-Token": token, "X-Git-Assessment-Confirm": "delete-session"},
        ).status_code
        == 403
    )

    # Wrong PIN rejected; valid PIN unlocks examiner console and cleanup
    assert (
        anon_client.post(
            "/api/examiner/unlock",
            json={"pin": "0000"},
            headers={"X-Git-Assessment-Token": token, "Accept": "application/json"},
        ).status_code
        == 403
    )
    assert (
        anon_client.post(
            "/api/examiner/unlock",
            json={"pin": "2468"},
            headers={"X-Git-Assessment-Token": token, "Accept": "application/json"},
        ).status_code
        == 200
    )
    assert anon_client.get(f"/api/sessions/{sid}/result").status_code == 200
    assert "Exam User" in anon_client.get("/examiner").get_data(as_text=True)

    # Legacy lock + quarantine cleanup via examiner API
    (service.data_root / "git-exam.lock").write_text("old", encoding="utf-8")
    (service.quarantine_root / "results").mkdir(parents=True, exist_ok=True)
    (service.quarantine_root / "results" / "stale.json").write_text("{}", encoding="utf-8")
    cleanup = anon_client.post(
        "/api/examiner/cleanup",
        json={"include_quarantine": True, "include_archive": False},
        headers={"X-Git-Assessment-Token": token},
    )
    assert cleanup.status_code == 200
    assert cleanup.get_json()["removed_items"] >= 2
    assert not (service.data_root / "git-exam.lock").exists()


def test_ansi_stripping_log_formatter():
    import logging
    from run import AnsiStrippingFormatter

    formatter = AnsiStrippingFormatter("%(message)s")
    record = logging.LogRecord("test", logging.INFO, "", 0, '\x1b[31m\x1b[1m"GET / HTTP/1.1" 404\x1b[0m', (), None)
    assert formatter.format(record) == '"GET / HTTP/1.1" 404'


def test_launcher_script_encodings_are_windows_safe():
    vbs_files = list(PROJECT_ROOT.rglob("*.vbs"))
    assert vbs_files
    for path in vbs_files:
        raw = path.read_bytes()
        assert all(byte < 128 for byte in raw), f"{path.name} must remain pure 7-bit ASCII for Windows VBScript"

    ps1_files = list((PROJECT_ROOT / "scripts").glob("*.ps1"))
    assert ps1_files
    for path in ps1_files:
        raw = path.read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf"), f"{path.name} must start with UTF-8 BOM for Windows PowerShell 5.1"


def test_task05_blocks_no_stash_switch_and_branch_track_shortcut(assessment):
    _, service, result = assessment
    session_id = result["session_id"]
    repo = service.task_repo(result, "task05")

    assert git(repo, "config", "--get", "core.autocrlf").stdout.strip() == "false"

    initial = service.check_task(session_id, "task05")
    initial_checks = {item["check_id"]: item for item in initial["checks"]}
    assert initial_checks["switched-back"]["passed"] is False

    # Without stash, switching to origin/hotfix/check-status must be rejected due to notes/development.md conflict
    git(repo, "fetch", "origin")
    no_stash_switch = git(repo, "switch", "--track", "origin/hotfix/check-status", check=False)
    assert no_stash_switch.returncode != 0

    # Shortcut using `git branch --track` without actually switching must not pass
    git(repo, "branch", "--track", "hotfix/check-status", "origin/hotfix/check-status")
    shortcut = service.check_task(session_id, "task05")
    shortcut_checks = {item["check_id"]: item["passed"] for item in shortcut["checks"]}
    assert shortcut["completed"] is False
    assert shortcut_checks["hotfix-branch"] is True
    assert shortcut_checks["hotfix-updated"] is True
    assert shortcut_checks["switched-back"] is False


def test_spoofed_reflog_commit_messages_do_not_bypass_process_checks(assessment):
    _, service, result = assessment
    session_id = result["session_id"]

    # Task 02: spoof "commit (amend)" inside a regular commit message then reset
    repo2 = service.task_repo(result, "task02")
    (repo2 / "tests/test_config.py").write_text(
        'from src.config import CONFIG_PATH\n\n\ndef test_config_path():\n    assert CONFIG_PATH == "config/production.json"\n',
        encoding="utf-8",
    )
    git(repo2, "commit", "--allow-empty", "-m", "commit (amend)")
    git(repo2, "reset", "--soft", "HEAD~2")
    git(repo2, "add", "-A")
    git(repo2, "commit", "-m", "Fix configuration loading")
    t2 = service.check_task(session_id, "task02")
    t2_checks = {item["check_id"]: item["passed"] for item in t2["checks"]}
    assert t2["completed"] is False
    assert t2_checks["used-amend"] is False

    # Task 06: spoof "cherry-pick" inside a regular commit message + manual file copy
    repo6 = service.task_repo(result, "task06")
    git(repo6, "commit", "--allow-empty", "-m", "cherry-pick")
    git(repo6, "reset", "--hard", "HEAD~1")
    (repo6 / "src/validator.py").write_text(
        'def is_valid(value):\n    return value is not None and value.strip() != ""\n',
        encoding="utf-8",
    )
    git(repo6, "add", "src/validator.py")
    git(repo6, "commit", "-m", "Reject empty validation values")
    t6 = service.check_task(session_id, "task06")
    t6_checks = {item["check_id"]: item["passed"] for item in t6["checks"]}
    assert t6["completed"] is False
    assert t6_checks["used-cherry-pick"] is False


def test_task04_rejects_indented_conflict_markers_commented_stale_values_and_extra_commits(assessment):
    _, service, result = assessment
    session_id = result["session_id"]
    repo = service.task_repo(result, "task04")

    # Pre-fetch error message should not leak unseen remote SHA
    pending_sha = service.task_state(result, "task04")["baseline"]["remote_pending_main"]
    pre = service.check_task(session_id, "task04")
    for item in pre["checks"]:
        assert pending_sha[:7] not in item["message"]

    # Indented conflict marker + commented stale value must fail
    service.simulate_remote_update(session_id, "task04")
    git(repo, "fetch", "origin")
    rebase = git(repo, "rebase", "origin/main", check=False)
    assert rebase.returncode != 0
    (repo / "src/login.py").write_text(
        " <<<<<<< HEAD\nLOGIN_TIMEOUT = 60\nLOGIN_RETRY = 5\n# LOGIN_TIMEOUT = 45\n",
        encoding="utf-8",
    )
    git(repo, "add", "src/login.py")
    git(repo, "-c", "core.editor=true", "rebase", "--continue")
    dirty = service.check_task(session_id, "task04")
    dirty_checks = {item["check_id"]: item["passed"] for item in dirty["checks"]}
    assert dirty["completed"] is False
    assert dirty_checks["no-conflict-markers"] is False
    assert dirty_checks["no-stale-values"] is False

    # Clean file + extra commit must fail single-commit check
    (repo / "src/login.py").write_text("LOGIN_TIMEOUT = 60\nLOGIN_RETRY = 5\n", encoding="utf-8")
    git(repo, "add", "src/login.py")
    git(repo, "commit", "--amend", "--no-edit")
    git(repo, "commit", "--allow-empty", "-m", "Extra stray commit")
    extra = service.check_task(session_id, "task04")
    extra_checks = {item["check_id"]: item["passed"] for item in extra["checks"]}
    assert extra["completed"] is False
    assert extra_checks["single-commit"] is False


def test_examiner_pin_privacy_isolation_lockout_prg_and_config_file(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("GIT_ASSESSMENT_EXAMINER_PIN", raising=False)
    data_root = tmp_path / "runtime"
    data_root.mkdir(parents=True, exist_ok=True)
    (data_root / "examiner.json").write_text(json.dumps({"pin": "9876"}), encoding="utf-8")

    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "pin-test-secret",
            "TEMPLATE_ROOT": PROJECT_ROOT / "data" / "templates",
            "DATA_ROOT": data_root,
            "QUESTIONS_PATH": PROJECT_ROOT / "questions" / "questions.json",
        }
    )
    assert app.config["EXAMINER_PIN"] == "9876"
    token = app.config["LOCAL_API_TOKEN"]

    owner = app.test_client()
    created = owner.post(
        "/api/sessions",
        data={"_api_token": token, "_confirm": "create", "candidate_name": "Alice", "mode": "exam"},
        headers={"Accept": "application/json"},
    )
    assert created.status_code == 201
    sid = created.get_json()["session_id"]

    # /api/health must not list session IDs
    health = owner.get("/api/health").get_json()
    assert "sessions" not in health
    assert health["healthy"] is True

    # Header hides examiner link while locked
    home_html = owner.get("/").get_data(as_text=True)
    assert "header-examiner" not in home_html

    # Another browser without matching cookie cannot access Alice's pages or task APIs
    other = app.test_client()
    assert other.get(f"/assessment/{sid}").status_code == 403
    assert other.get(f"/assessment/{sid}/tasks/task01").status_code == 403
    assert other.get(f"/assessment/{sid}/result").status_code == 403
    assert (
        other.post(
            f"/api/sessions/{sid}/tasks/task01/check",
            headers={"X-Git-Assessment-Token": token, "Accept": "application/json"},
        ).status_code
        == 403
    )

    # HTML wrong PIN uses PRG redirect to /examiner and shows error message
    bad_form = other.post(
        "/api/examiner/unlock",
        data={"_api_token": token, "pin": "1111"},
        headers={"Accept": "text/html"},
    )
    assert bad_form.status_code == 302
    assert bad_form.headers["Location"].endswith("/examiner")
    after_redirect = other.get("/examiner").get_data(as_text=True)
    assert "考官 PIN 碼錯誤" in after_redirect

    # 4 more wrong JSON attempts trigger lockout (5 total -> 429)
    for _ in range(3):
        resp = other.post(
            "/api/examiner/unlock",
            json={"pin": "0000"},
            headers={"X-Git-Assessment-Token": token, "Accept": "application/json"},
        )
        assert resp.status_code == 403
    locked_resp = other.post(
        "/api/examiner/unlock",
        json={"pin": "0000"},
        headers={"X-Git-Assessment-Token": token, "Accept": "application/json"},
    )
    assert locked_resp.status_code == 429
    # Even correct PIN is rejected while locked
    still_locked = other.post(
        "/api/examiner/unlock",
        json={"pin": "9876"},
        headers={"X-Git-Assessment-Token": token, "Accept": "application/json"},
    )
    assert still_locked.status_code == 429

    # Simulate lockout expiration -> correct PIN unlocks and grants access to Alice's result
    app.extensions["examiner_auth_state"]["locked_until"] = 0.0
    unlocked = other.post(
        "/api/examiner/unlock",
        json={"pin": "9876"},
        headers={"X-Git-Assessment-Token": token, "Accept": "application/json"},
    )
    assert unlocked.status_code == 200
    assert other.get(f"/assessment/{sid}/result").status_code == 200

    # Without PIN configured, /api/examiner/unlock returns 400 JSON
    no_pin_app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "no-pin-secret",
            "EXAMINER_PIN": "",
            "TEMPLATE_ROOT": PROJECT_ROOT / "data" / "templates",
            "DATA_ROOT": tmp_path / "runtime-nopin",
            "QUESTIONS_PATH": PROJECT_ROOT / "questions" / "questions.json",
        }
    )
    no_pin_resp = no_pin_app.test_client().post(
        "/api/examiner/unlock",
        json={"pin": "1234"},
        headers={"X-Git-Assessment-Token": no_pin_app.config["LOCAL_API_TOKEN"], "Accept": "application/json"},
    )
    assert no_pin_resp.status_code == 400


def test_exam_mode_hides_unviewed_hints_and_scrubs_failure_commands(assessment):
    app, service, _ = assessment
    token = app.config["LOCAL_API_TOKEN"]
    client = app.test_client()

    created = client.post(
        "/api/sessions",
        data={"_api_token": token, "_confirm": "create", "candidate_name": "Exam Candidate", "mode": "exam"},
        headers={"Accept": "application/json"},
    )
    sid = created.get_json()["session_id"]

    # Unviewed hints must not appear in HTML source; exam_label replaces command-naming labels
    task06_html = client.get(f"/assessment/{sid}/tasks/task06").get_data(as_text=True)
    assert "git cherry-pick &lt;SHA&gt;" not in task06_html
    assert "git log --oneline fix/validation" not in task06_html
    assert "以單一 commit 套用方式帶入修正" in task06_html

    # Clicking hint fetches hint_text dynamically via API and records usage
    hint_resp = client.post(
        f"/api/sessions/{sid}/tasks/task06/hint",
        json={"hint_index": 1},
        headers={"X-Git-Assessment-Token": token, "X-Git-Assessment-Request-ID": "exam-hint-0001"},
    )
    assert hint_resp.status_code == 200
    hint_data = hint_resp.get_json()
    assert hint_data["hints_used"] == 1
    assert "git cherry-pick" in hint_data["hint_text"]

    # Exam failure messages must not leak Git commands
    leaked_tokens = ("git fetch", "git rebase", "git cherry-pick", "git commit --amend", "git stash pop", "git switch --track")
    for task_id in ("task02", "task04", "task05", "task06"):
        outcome = service.check_task(sid, task_id)
        for item in outcome["checks"]:
            if not item["passed"]:
                for bad in leaked_tokens:
                    assert bad not in item["message"], f"{task_id}/{item['check_id']} leaked {bad}: {item['message']}"


def test_waiting_state_duration_repair_count_and_quarantine_cleanup(assessment):
    _, service, result = assessment
    sid = result["session_id"]

    # Initial untouched check marks passive checks as waiting rather than passed
    initial = service.check_task(sid, "task01")
    states = {item["check_id"]: item["display_state"] for item in initial["checks"]}
    assert states["readme-modified"] == "waiting"
    assert states["debug-untracked"] == "waiting"
    assert states["readme-not-commit"] == "waiting"
    assert states["debug-not-commit"] == "waiting"
    assert states["single-commit"] == "failed"

    # Reset preserves first_opened_at
    service.mark_opened(sid, "task01")
    opened_at = service.task_state(service.get_session(sid), "task01")["first_opened_at"]
    assert opened_at is not None
    service.reset_task(sid, "task01")
    after_reset = service.task_state(service.get_session(sid), "task01")
    assert after_reset["first_opened_at"] == opened_at
    assert after_reset["reset_count"] == 1
    assert after_reset["repair_count"] == 0

    # Completed task without first_opened_at renders "—" instead of "尚未完成"
    repo2 = service.task_repo(service.get_session(sid), "task02")
    (repo2 / "tests/test_config.py").write_text(
        'from src.config import CONFIG_PATH\n\n\ndef test_config_path():\n    assert CONFIG_PATH == "config/production.json"\n',
        encoding="utf-8",
    )
    git(repo2, "add", "tests/test_config.py")
    git(repo2, "commit", "--amend", "--no-edit")
    assert service.check_task(sid, "task02")["completed"] is True
    summary = service.build_result_summary(service.get_session(sid))
    t2_summary = next(item for item in summary["tasks"] if item["task_id"] == "task02")
    assert t2_summary["status"] == "completed"
    assert t2_summary["duration_display"] == "—"

    # Examiner repair increments repair_count (not reset_count) and labels backup with repair-
    service.repair_task(sid, "task03")
    t3_state = service.task_state(service.get_session(sid), "task03")
    assert t3_state["repair_count"] == 1
    assert t3_state["reset_count"] == 0
    backups = list((service.quarantine_root / "workspaces").glob(f"task03-repair-task03-{sid}-*"))
    assert len(backups) == 1

    # Deleting session cleans up its matching quarantine backup
    service.delete_session(sid)
    assert not list((service.quarantine_root / "workspaces").glob(f"*{sid}*"))

