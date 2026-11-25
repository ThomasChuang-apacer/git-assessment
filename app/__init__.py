from __future__ import annotations

import os
from pathlib import Path
import secrets

from flask import Flask, session

from .routes import bp
from .security import install_local_request_protection
from .services import AssessmentService


def create_app(test_config: dict | None = None) -> Flask:
    project_root = Path(__file__).resolve().parent.parent
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=secrets.token_hex(32),
        LOCAL_API_TOKEN=secrets.token_urlsafe(32),
        EXAMINER_PIN=os.environ.get("GIT_ASSESSMENT_EXAMINER_PIN", "").strip(),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PROJECT_ROOT=project_root,
        QUESTIONS_PATH=project_root / "questions" / "questions.json",
        TEMPLATE_ROOT=project_root / "data" / "templates",
        DATA_ROOT=project_root / "runtime",
        GIT_TIMEOUT=5,
    )
    if test_config:
        app.config.update(test_config)

    service = AssessmentService(
        questions_path=Path(app.config["QUESTIONS_PATH"]),
        template_root=Path(app.config["TEMPLATE_ROOT"]),
        data_root=Path(app.config["DATA_ROOT"]),
        git_timeout=int(app.config["GIT_TIMEOUT"]),
    )
    service.prepare()
    app.extensions["assessment_service"] = service
    install_local_request_protection(app)

    @app.context_processor
    def inject_globals():
        pin = str(app.config.get("EXAMINER_PIN") or "").strip()
        return {
            "api_token": app.config["LOCAL_API_TOKEN"],
            "instance_id": service.instance_id,
            "examiner_required": bool(pin),
            "examiner_unlocked": (not pin) or (session.get("examiner_unlocked") is True),
        }

    app.register_blueprint(bp)
    return app
