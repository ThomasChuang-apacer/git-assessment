from __future__ import annotations

from datetime import datetime
import hmac
import logging
import threading
import time

from flask import Blueprint, abort, current_app, jsonify, make_response, redirect, render_template, request, session, url_for
from werkzeug.exceptions import HTTPException


bp = Blueprint("main", __name__)
logger = logging.getLogger("git_assessment.routes")

ACTIVE_SESSION_COOKIE = "git_assessment_active_session"

HTTP_ERROR_MESSAGES = {
    400: "要求內容不正確，請回到上一頁再試一次。",
    403: "這個操作沒有通過安全驗證，請重新整理頁面後再試一次。",
    404: "找不到這個頁面。網址可能打錯了，或這份測驗紀錄已被刪除。",
    405: "這個網址不支援目前的操作方式，請從頁面上的按鈕操作。",
    500: "程式發生未預期的錯誤，請重新整理頁面；若持續發生，請聯絡考官。",
}


def service():
    return current_app.extensions["assessment_service"]


def examiner_pin() -> str:
    return str(current_app.config.get("EXAMINER_PIN") or "").strip()


def examiner_required() -> bool:
    return bool(examiner_pin())


def examiner_unlocked() -> bool:
    pin = examiner_pin()
    if not pin:
        return True
    if session.get("examiner_unlocked") is True:
        return True
    supplied = request.headers.get("X-Git-Assessment-Examiner-PIN", "").strip()
    return bool(supplied) and hmac.compare_digest(supplied, pin)


def require_examiner() -> None:
    if not examiner_unlocked():
        abort(403, description="此操作僅限考官模式使用，請先驗證考官 PIN 碼")


def session_context(session_id: str) -> tuple[dict, dict[str, dict]]:
    result = service().get_session(session_id)
    states = {item["task_id"]: item for item in result["tasks"]}
    return result, states


def wants_json_response() -> bool:
    return request.path.startswith("/api/") and request.accept_mimetypes.best_match(
        ["application/json", "text/html"]
    ) != "text/html"


@bp.app_template_filter("format_dt")
def format_dt_filter(value: str | None) -> str:
    if not value:
        return "—"
    try:
        dt = datetime.fromisoformat(value)
        return dt.strftime("%Y/%m/%d %H:%M:%S")
    except ValueError:
        return str(value)


@bp.errorhandler(KeyError)
def handle_not_found_error(error):
    message = error.args[0] if error.args else "找不到指定的資料"
    if wants_json_response():
        return jsonify({"error": message}), 404
    return render_template("error.html", message=message), 404


@bp.errorhandler(ValueError)
def handle_known_error(error):
    message = error.args[0] if error.args else "要求無法處理"
    if wants_json_response():
        return jsonify({"error": message}), 400
    return render_template("error.html", message=message), 400


@bp.app_errorhandler(HTTPException)
def handle_http_error(error: HTTPException):
    message = error.description
    if message == type(error).description:
        message = HTTP_ERROR_MESSAGES.get(error.code, f"目前無法處理這個要求（錯誤代碼 {error.code}）。")
    if wants_json_response():
        return jsonify({"error": message}), error.code
    return render_template("error.html", message=message), error.code


@bp.get("/")
def home():
    all_sessions = service().list_sessions()
    restricted = examiner_required() and not examiner_unlocked()
    active_cookie = request.cookies.get(ACTIVE_SESSION_COOKIE)
    if restricted:
        recent_sessions = []
        latest_incomplete = next(
            (
                item
                for item in all_sessions
                if item["session_id"] == active_cookie and item["available"] and item["completed_at"] is None
            ),
            None,
        )
    else:
        recent_sessions = all_sessions
        latest_incomplete = next(
            (
                item
                for item in all_sessions
                if item["session_id"] == active_cookie and item["available"] and item["completed_at"] is None
            ),
            None,
        ) or next(
            (item for item in all_sessions if item["available"] and item["completed_at"] is None),
            None,
        )
    return render_template(
        "home.html",
        environment=service().environment_status(),
        recent_sessions=recent_sessions,
        latest_incomplete=latest_incomplete,
        privacy_restricted=restricted,
    )


@bp.post("/api/sessions")
def create_session():
    payload = request.get_json(silent=True) if request.is_json else None
    confirm = request.form.get("_confirm") or (payload.get("_confirm") if isinstance(payload, dict) else None)
    if confirm != "create":
        abort(400, description="缺少建立測驗確認")
    candidate_name = (
        request.form.get("candidate_name")
        if "candidate_name" in request.form
        else (str(payload.get("candidate_name", "")) if isinstance(payload, dict) else "")
    )
    mode = (
        request.form.get("mode")
        or (str(payload.get("mode", "practice")) if isinstance(payload, dict) else "practice")
        or "practice"
    )
    try:
        if mode == "practice":
            result = service().create_session(candidate_name)
        else:
            result = service().create_session(candidate_name, mode=mode)
    except PermissionError:
        logger.warning("建立測驗時 workspace 持續被其他程式占用", exc_info=True)
        abort(
            409,
            description=(
                "測驗工作資料夾正在被其他程式使用。請關閉正在開啟該資料夾的 Terminal、"
                "VS Code 或檔案總管後再試。"
            ),
        )
    target_url = url_for("main.overview", session_id=result["session_id"])
    if wants_json_response():
        response = make_response(
            jsonify({"session_id": result["session_id"], "redirect_url": target_url, "session": result}),
            201,
        )
    else:
        response = make_response(redirect(target_url))
    response.set_cookie(ACTIVE_SESSION_COOKIE, result["session_id"], httponly=True, samesite="Lax")
    return response


@bp.post("/api/sessions/<session_id>/delete")
def delete_session(session_id: str):
    require_examiner()
    if request.headers.get("X-Git-Assessment-Confirm") != "delete-session":
        abort(400, description="缺少刪除確認")
    service().idempotent(
        f"delete:{session_id}", request.headers.get("X-Git-Assessment-Request-ID"),
        lambda: service().delete_session(session_id),
    )
    response = make_response(jsonify({"ok": True}))
    if request.cookies.get(ACTIVE_SESSION_COOKIE) == session_id:
        response.delete_cookie(ACTIVE_SESSION_COOKIE)
    return response


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
    state = service().task_state(outcome["session"], task_id)
    return jsonify(
        {
            "completed": outcome["completed"],
            "checks": outcome["checks"],
            "completed_count": completed_count,
            "total": len(outcome["session"]["tasks"]),
            "all_completed": outcome["session"]["completed_at"] is not None,
            "check_attempts": state["check_attempts"],
        }
    )


@bp.post("/api/sessions/<session_id>/tasks/<task_id>/hint")
def view_hint(session_id: str, task_id: str):
    payload = request.get_json(silent=True) if request.is_json else None
    raw_index = (
        payload.get("hint_index")
        if isinstance(payload, dict) and "hint_index" in payload
        else request.form.get("hint_index")
    )
    try:
        hint_index = int(raw_index)
    except (TypeError, ValueError):
        abort(400, description="無效的提示編號")
    outcome = service().idempotent(
        f"hint:{session_id}:{task_id}:{hint_index}",
        request.headers.get("X-Git-Assessment-Request-ID"),
        lambda: service().record_hint_viewed(session_id, task_id, hint_index),
    )
    return jsonify(outcome)


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
    require_examiner()
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
    require_examiner()
    return jsonify(service().get_session(session_id))


@bp.get("/assessment/<session_id>/result")
def result_summary(session_id: str):
    result = service().get_session(session_id)
    summary = service().build_result_summary(result)
    return render_template("result.html", result=result, summary=summary)


@bp.get("/examiner")
def examiner_dashboard():
    unlocked = examiner_unlocked()
    sessions_data = []
    if unlocked:
        for item in service().list_sessions(limit=50):
            try:
                raw = service().get_session(item["session_id"])
                summary = service().build_result_summary(raw)
                sessions_data.append({**item, "summary": summary})
            except (KeyError, ValueError):
                sessions_data.append({**item, "summary": None})
    return render_template(
        "examiner.html",
        unlocked=unlocked,
        pin_required=examiner_required(),
        sessions=sessions_data,
        storage=service().runtime_storage_stats(),
        health=service().runtime_health(),
    )


@bp.post("/api/examiner/unlock")
def unlock_examiner():
    pin = examiner_pin()
    payload = request.get_json(silent=True) if request.is_json else None
    supplied = (
        str(payload.get("pin", ""))
        if isinstance(payload, dict) and "pin" in payload
        else request.form.get("pin", "")
    ).strip()
    if pin and not hmac.compare_digest(supplied, pin):
        if wants_json_response():
            return jsonify({"error": "考官 PIN 碼錯誤"}), 403
        return render_template(
            "examiner.html",
            unlocked=False,
            pin_required=True,
            error_message="考官 PIN 碼錯誤，請再試一次。",
            sessions=[],
            storage=service().runtime_storage_stats(),
            health=service().runtime_health(),
        ), 403
    session["examiner_unlocked"] = True
    if wants_json_response():
        return jsonify({"ok": True})
    return redirect(url_for("main.examiner_dashboard"))


@bp.post("/api/examiner/lock")
def lock_examiner():
    session.pop("examiner_unlocked", None)
    if wants_json_response():
        return jsonify({"ok": True})
    return redirect(url_for("main.home"))


@bp.post("/api/examiner/cleanup")
def cleanup_examiner_storage():
    require_examiner()
    payload = request.get_json(silent=True) if request.is_json else {}
    include_quarantine = bool(payload.get("include_quarantine", True)) if isinstance(payload, dict) else True
    include_archive = bool(payload.get("include_archive", False)) if isinstance(payload, dict) else False
    outcome = service().cleanup_runtime(
        include_quarantine=include_quarantine,
        include_archive=include_archive,
    )
    return jsonify(outcome)


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
