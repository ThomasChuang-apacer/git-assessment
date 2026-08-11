from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import socket
import threading
import time
import webbrowser

from app import create_app
from werkzeug.serving import make_server


HOST = "127.0.0.1"
PORT = int(os.environ.get("GIT_ASSESSMENT_PORT", "8765"))
ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime"


def configure_logging() -> None:
    log_dir = RUNTIME / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / "git-assessment.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().setLevel(logging.INFO)
    logging.getLogger().addHandler(handler)


def port_is_available() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((HOST, PORT))
        except OSError:
            return False
    return True


def acquire_instance_lock():
    lock_path = RUNTIME / "git-assessment.lock"
    RUNTIME.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise RuntimeError("Git Assessment 已經在執行中")
    (RUNTIME / "git-assessment.pid").write_text(str(os.getpid()), encoding="ascii")
    return handle


def open_browser_when_ready() -> None:
    url = f"http://{HOST}:{PORT}"
    for _ in range(60):
        try:
            with socket.create_connection((HOST, PORT), timeout=0.5):
                open_browser(url)
                return
        except OSError:
            time.sleep(0.25)


def open_browser(url: str) -> None:
    if os.name == "nt":
        os.startfile(url)  # type: ignore[attr-defined]
    else:
        webbrowser.open(url)


def main() -> int:
    configure_logging()
    logger = logging.getLogger("git_assessment.run")
    try:
        lock_handle = acquire_instance_lock()
    except RuntimeError as exc:
        logger.info("Git Assessment 已在執行，開啟現有網站")
        open_browser(f"http://{HOST}:{PORT}")
        return 0
    server = None
    try:
        if not port_is_available():
            message = f"Port {PORT} 已被其他程式使用，Git Assessment 無法啟動"
            logger.error(message)
            print(message)
            return 3
        app = create_app()
        server = make_server(HOST, PORT, app, threaded=True)
        app.extensions["git_assessment_shutdown"] = server.shutdown
        if os.environ.get("GIT_ASSESSMENT_NO_BROWSER") != "1":
            threading.Thread(target=open_browser_when_ready, daemon=True).start()
        logger.info("Git Assessment 啟動於 http://%s:%s", HOST, PORT)
        server.serve_forever()
        logger.info("Git Assessment 已安全關閉")
        return 0
    except Exception:
        logger.exception("Git Assessment 啟動或執行失敗")
        raise
    finally:
        if server is not None:
            server.server_close()
        (RUNTIME / "git-assessment.pid").unlink(missing_ok=True)
        lock_handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
