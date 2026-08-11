from __future__ import annotations

from urllib.parse import urlparse

from flask import Flask, abort, request


LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def install_local_request_protection(app: Flask) -> None:
    """Reject state-changing requests that did not originate from this app."""

    @app.before_request
    def protect_local_api():
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return None

        host = (urlparse(f"//{request.host}").hostname or "").lower()
        if host not in LOCAL_HOSTS:
            abort(403, description="只允許從本機存取")

        origin = request.headers.get("Origin")
        if origin:
            origin_host = (urlparse(origin).hostname or "").lower()
            if origin_host not in LOCAL_HOSTS:
                abort(403, description="拒絕非本機來源的要求")

        supplied = request.headers.get("X-Git-Assessment-Token") or request.form.get("_api_token")
        if supplied != app.config["LOCAL_API_TOKEN"]:
            abort(403, description="要求驗證失敗，請重新整理頁面")
        return None
