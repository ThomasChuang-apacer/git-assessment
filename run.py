from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import socket
import threading
import time
import webbrowser

from app import create_app
from werkzeug.serving import make_server


HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_FALLBACK_PORT = 8799
DEFAULT_IDLE_TIMEOUT_SECONDS = 7200
PORT = int(os.environ.get("GIT_ASSESSMENT_PORT", str(DEFAULT_PORT)))
ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime"
SERVER_URL_FILE = RUNTIME / "server-url.txt"
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


class AnsiStrippingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return ANSI_ESCAPE_RE.sub("", super().format(record))


class IdleShutdownMonitor:
    """Automatically shut down the local server after sustained inactivity."""

    def __init__(self, timeout_seconds: float, shutdown_callback, logger: logging.Logger | None = None):
        self.timeout_seconds = float(timeout_seconds)
        self._shutdown = shutdown_callback
        self._logger = logger or logging.getLogger("git_assessment.idle")
        self._lock = threading.Lock()
        self._active_requests = 0
        self._last_activity = time.monotonic()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.triggered = False

    def request_started(self) -> None:
        with self._lock:
            self._active_requests += 1
            self._last_activity = time.monotonic()

    def request_finished(self) -> None:
        with self._lock:
            self._active_requests = max(0, self._active_requests - 1)
            self._last_activity = time.monotonic()

    def attach(self, app) -> None:
        app.before_request(self.request_started)
        app.teardown_request(lambda _exc=None: self.request_finished())

    def start(self) -> None:
        if self.timeout_seconds <= 0:
            return
        self._thread = threading.Thread(target=self._run, name="idle-shutdown-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if (
            self._thread is not None
            and self._thread.is_alive()
            and self._thread is not threading.current_thread()
        ):
            self._thread.join(timeout=1.0)

    def _run(self) -> None:
        poll_interval = min(30.0, max(0.05, self.timeout_seconds / 4.0))
        while not self._stop_event.wait(poll_interval):
            with self._lock:
                idle_for = time.monotonic() - self._last_activity
                busy = self._active_requests > 0
            if not busy and idle_for >= self.timeout_seconds:
                self.triggered = True
                self._logger.info(
                    "Git Assessment 已閒置超過 %d 秒，自動安全關閉",
                    int(self.timeout_seconds),
                )
                try:
                    self._shutdown()
                except Exception:
                    self._logger.exception("閒置自動關閉失敗")
                return


def resolve_port_config() -> tuple[int, bool]:
    raw = os.environ.get("GIT_ASSESSMENT_PORT", "").strip()
    if raw:
        try:
            port = int(raw)
            if 1 <= port <= 65535:
                return port, True
        except ValueError:
            pass
    return DEFAULT_PORT, False


def resolve_idle_timeout() -> int:
    raw = os.environ.get("GIT_ASSESSMENT_IDLE_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return DEFAULT_IDLE_TIMEOUT_SECONDS
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_IDLE_TIMEOUT_SECONDS


def read_saved_server_url(runtime_dir: Path = RUNTIME) -> str | None:
    path = runtime_dir / "server-url.txt"
    if not path.is_file():
        return None
    try:
        value = path.read_text(encoding="ascii").strip()
        if value.startswith("http://127.0.0.1:"):
            return value
    except OSError:
        return None
    return None


def write_saved_server_url(url: str, runtime_dir: Path = RUNTIME) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "server-url.txt").write_text(url, encoding="ascii")


def port_is_available(port: int = PORT, host: str = HOST) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


def create_bound_server(
    app,
    host: str = HOST,
    preferred_port: int = DEFAULT_PORT,
    strict: bool = False,
    max_port: int = MAX_FALLBACK_PORT,
):
    end_port = preferred_port if strict else max(preferred_port, max_port)
    last_error: OSError | None = None
    for candidate_port in range(preferred_port, end_port + 1):
        if not port_is_available(candidate_port, host=host):
            continue
        try:
            server = make_server(host, candidate_port, app, threaded=True)
            return server, candidate_port
        except OSError as exc:
            last_error = exc
    raise OSError(f"無法綁定可用連接埠（{preferred_port}-{end_port}）") from last_error


def configure_logging() -> None:
    log_dir = RUNTIME / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / "git-assessment.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(AnsiStrippingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().setLevel(logging.INFO)
    logging.getLogger().addHandler(handler)


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


def open_browser_when_ready(port: int = PORT) -> None:
    url = f"http://{HOST}:{port}"
    for _ in range(60):
        try:
            with socket.create_connection((HOST, port), timeout=0.5):
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
    preferred_port, strict_port = resolve_port_config()
    idle_timeout = resolve_idle_timeout()
    try:
        lock_handle = acquire_instance_lock()
    except RuntimeError:
        existing_url = read_saved_server_url() or f"http://{HOST}:{preferred_port}"
        logger.info("Git Assessment 已在執行，開啟現有網站：%s", existing_url)
        if os.environ.get("GIT_ASSESSMENT_NO_BROWSER") != "1":
            open_browser(existing_url)
        return 0
    server = None
    idle_monitor = None
    try:
        if strict_port and not port_is_available(preferred_port):
            message = f"Port {preferred_port} 已被其他程式使用，Git Assessment 無法啟動"
            logger.error(message)
            print(message)
            return 3
        app = create_app()
        try:
            server, actual_port = create_bound_server(
                app,
                host=HOST,
                preferred_port=preferred_port,
                strict=strict_port,
            )
        except OSError:
            port_desc = f"Port {preferred_port}" if strict_port else f"Port {preferred_port}-{MAX_FALLBACK_PORT}"
            message = f"{port_desc} 已被其他程式使用，Git Assessment 無法啟動"
            logger.error(message)
            print(message)
            return 3
        if actual_port != preferred_port:
            logger.info("Port %d 已被其他程式占用，自動改用可用連接埠 %d", preferred_port, actual_port)
        url = f"http://{HOST}:{actual_port}"
        write_saved_server_url(url)
        app.extensions["git_assessment_shutdown"] = server.shutdown
        idle_monitor = IdleShutdownMonitor(idle_timeout, server.shutdown, logger=logger)
        idle_monitor.attach(app)
        idle_monitor.start()
        if os.environ.get("GIT_ASSESSMENT_NO_BROWSER") != "1":
            threading.Thread(target=open_browser_when_ready, args=(actual_port,), daemon=True).start()
        idle_desc = f"{idle_timeout // 60} 分鐘" if idle_timeout >= 60 else (f"{idle_timeout} 秒" if idle_timeout > 0 else "停用")
        logger.info("Git Assessment 啟動於 %s（閒置自動關閉：%s）", url, idle_desc)
        print(f"Git Assessment 已啟動：{url}（請保持此視窗開啟，結束測驗請按網頁右上角「安全關閉」）", flush=True)
        server.serve_forever()
        logger.info("Git Assessment 已安全關閉")
        return 0
    except Exception:
        logger.exception("Git Assessment 啟動或執行失敗")
        raise
    finally:
        if idle_monitor is not None:
            idle_monitor.stop()
        if server is not None:
            server.server_close()
        (RUNTIME / "server-url.txt").unlink(missing_ok=True)
        (RUNTIME / "git-assessment.pid").unlink(missing_ok=True)
        lock_handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
