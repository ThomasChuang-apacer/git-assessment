from __future__ import annotations

import logging
import threading
import time

from flask import Blueprint, abort, current_app, jsonify, redirect, render_template, request, url_for
from werkzeug.exceptions import HTTPException


bp = Blueprint("main", __name__)
logger = logging.getLogger("git_assessment.routes")


def service():
    return current_app.extensions["assessment_service"]


def session_context(session_id: str) -> tuple[dict, dict[str, dict]]:
    result = service().get_session(session_id)
    states = {item["task_id"]: item for item in result["tasks"]}
    return result, states


@bp.errorhandler(KeyError)
@bp.errorhandler(ValueError)
def handle_known_error(error):
    message = error.args[0] if error.args else "要求無法處理"
    if request.path.startswith("/api/"):
        return jsonify({"error": message}), 400
    return render_template("error.html", message=message), 400


@bp.app_errorhandler(HTTPException)
def handle_http_error(error: HTTPException):
    if request.path.startswith("/api/"):
        return jsonify({"error": error.description}), error.code
    return render_template("error.html", message=error.description), error.code


@bp.get("/")
def home():
    recent_sessions = service().list_sessions()
    latest_incomplete = next(
        (item for item in recent_sessions if item["available"] and item["completed_at"] is None),
        None,
    )
    return render_template(
        "home.html",
        environment=service().environment_status(),
        recent_sessions=recent_sessions,
        latest_incomplete=latest_incomplete,
    )


@bp.post("/api/sessions")
def create_session():
    if request.form.get("_confirm") != "create":
        abort(400, description="缺少建立測驗確認")
    try:
        result = service().create_session(request.form.get("candidate_name", ""))
    except PermissionError:
        logger.warning("建立測驗時 workspace 持續被其他程式占用", exc_info=True)
        abort(
            409,
            description=(
                "測驗工作資料夾正在被其他程式使用。請關閉正在開啟該資料夾的 Terminal、"
                "VS Code 或檔案總管後再試。"
            ),
        )
    return redirect(url_for("main.overview", session_id=result["session_id"]))


@bp.post("/api/sessions/<session_id>/delete")
def delete_session(session_id: str):
    if request.headers.get("X-Git-Assessment-Confirm") != "delete-session":
        abort(400, description="缺少刪除確認")
    service().idempotent(
        f"delete:{session_id}", request.headers.get("X-Git-Assessment-Request-ID"),
        lambda: service().delete_session(session_id),
    )
    return jsonify({"ok": True})


@bp.get("/assessment/<session_id>")
def overview(session_id: str):
    result, states = session_context(session_id)
    completed = sum(1 for item in result["tasks"] if item["status"] == "completed")
    return render_template(
        "overview.html",
        result=result,
        states=states,
        questions=service().questions,
        completed=completed,
        task_health=service().session_task_health(result),
    )


@bp.get("/assessment/<session_id>/tasks/<task_id>")
def task(session_id: str, task_id: str):
    result = service().mark_opened(session_id, task_id)
    question = service().get_question(task_id)
    state = service().task_state(result, task_id)
    repo = service().task_repo(result, task_id)
    questions = service().questions
    index = next(i for i, item in enumerate(questions) if item["id"] == task_id)
    return render_template(
        "task.html",
        result=result,
        question=question,
        state=state,
        repo=repo,
        completed=sum(1 for item in result["tasks"] if item["status"] == "completed"),
        total=len(questions),
        previous=questions[index - 1] if index > 0 else None,
        next_task=questions[index + 1] if index + 1 < len(questions) else None,
        remote_update_status=service().remote_update_status(result, task_id),
        task_compatibility=service().task_compatibility(result, task_id),
    )


@bp.post("/api/sessions/<session_id>/tasks/<task_id>/check")
def check_task(session_id: str, task_id: str):
    outcome = service().idempotent(
        f"check:{session_id}:{task_id}", request.headers.get("X-Git-Assessment-Request-ID"),
        lambda: service().check_task(session_id, task_id),
    )
    completed_count = sum(1 for item in outcome["session"]["tasks"] if item["status"] == "completed")
    return jsonify(
        {
            "completed": outcome["completed"],
            "checks": outcome["checks"],
            "completed_count": completed_count,
            "total": len(outcome["session"]["tasks"]),
            "all_completed": outcome["session"]["completed_at"] is not None,
        }
    )


@bp.post("/api/sessions/<session_id>/tasks/<task_id>/reset")
def reset_task(session_id: str, task_id: str):
    if request.headers.get("X-Git-Assessment-Confirm") != "reset":
        abort(400, description="缺少重設確認")
    service().idempotent(
        f"reset:{session_id}:{task_id}", request.headers.get("X-Git-Assessment-Request-ID"),
        lambda: service().reset_task(session_id, task_id),
    )
    return jsonify({"ok": True})


@bp.post("/api/sessions/<session_id>/tasks/<task_id>/open")
def open_task(session_id: str, task_id: str):
    service().idempotent(
        f"open:{session_id}:{task_id}", request.headers.get("X-Git-Assessment-Request-ID"),
        lambda: service().open_task_folder(session_id, task_id),
    )
    return jsonify({"ok": True})


@bp.post("/api/sessions/<session_id>/tasks/<task_id>/remote-update")
def simulate_remote_update(session_id: str, task_id: str):
    outcome = service().idempotent(
        f"remote-update:{session_id}:{task_id}", request.headers.get("X-Git-Assessment-Request-ID"),
        lambda: service().simulate_remote_update(session_id, task_id),
    )
    return jsonify(outcome)


@bp.post("/api/sessions/<session_id>/tasks/<task_id>/repair")
def repair_task(session_id: str, task_id: str):
    if request.headers.get("X-Git-Assessment-Confirm") != "repair":
        abort(400, description="缺少修復確認")
    confirm_completed = request.headers.get("X-Git-Assessment-Confirm-Completed") == "yes"
    service().idempotent(
        f"repair:{session_id}:{task_id}", request.headers.get("X-Git-Assessment-Request-ID"),
        lambda: service().repair_task(session_id, task_id, confirm_completed),
    )
    return jsonify({"ok": True})


@bp.get("/api/sessions/<session_id>/result")
def get_result(session_id: str):
    return jsonify(service().get_session(session_id))


@bp.get("/assessment/<session_id>/result")
def result_summary(session_id: str):
    result = service().get_session(session_id)
    states = {item["task_id"]: item for item in result["tasks"]}
    tasks = [
        {
            "task_id": question["id"],
            "order": question["order"],
            "title": question["title"],
            "status": states[question["id"]]["status"],
            "check_attempts": states[question["id"]]["check_attempts"],
            "completed_at": states[question["id"]]["completed_at"],
        }
        for question in service().questions
    ]
    summary = {
        "candidate_name": result["candidate_name"],
        "session_id": result["session_id"],
        "started_at": result["started_at"],
        "completed_at": result["completed_at"],
        "completed_count": sum(1 for item in tasks if item["status"] == "completed"),
        "total": len(tasks),
        "tasks": tasks,
    }
    return render_template("result.html", result=result, summary=summary)


@bp.get("/api/health")
def get_health():
    return jsonify(service().runtime_health())


@bp.post("/api/shutdown")
def shutdown_app():
    shutdown = current_app.extensions.get("git_assessment_shutdown")
    if shutdown is None:
        abort(503, description="目前執行模式不支援網頁關閉")

    def shutdown_after_response() -> None:
        # Give the JSON response enough time to reach the browser before the
        # local server stops accepting connections.
        time.sleep(0.5)
        try:
            shutdown()
        except Exception:
            logger.exception("安全關閉 Git Assessment 失敗")

    threading.Thread(target=shutdown_after_response, daemon=True).start()
    return jsonify({"ok": True, "message": "Git Assessment 正在安全關閉"})
