"""Live dashboard server.

Serves ``dashboard.html`` and a small JSON API that drives a real
:class:`~asis.core.SwarmController`. Uses only the standard library.

API (all responses are JSON frames in the same shape as trace snapshots):

    GET  /api/state            current frame, no step taken
    POST /api/step             advance the swarm one step
    POST /api/inject {"task"}  parse ASIS notation and inject it as a task
    POST /api/reset            discard the swarm and start a fresh one
"""

from __future__ import annotations

import json
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from typing import Any, Dict, Optional, Tuple

from asis.core import C, ParseError, SwarmController, __version__, create_default_swarm, parse_expression

MAX_BODY_BYTES = 64 * 1024
MAX_TASK_CHARS = 2000


def _demo_task():
    return C.compose(
        C.goal("optimize_system"),
        C.constraint("latency < 100ms"),
        C.constraint("throughput > 1000rps")
    )


class DashboardSession:
    """A swarm shared by all dashboard clients, guarded by a lock."""

    def __init__(self, demo: bool = True):
        self._lock = threading.Lock()
        self._demo = demo
        self._swarm = self._new_swarm()

    def _new_swarm(self) -> SwarmController:
        swarm = create_default_swarm()
        if self._demo:
            swarm.inject_task(_demo_task())
        return swarm

    def _frame(self, frame: Dict[str, Any]) -> Dict[str, Any]:
        frame["version"] = __version__
        return frame

    def state(self) -> Dict[str, Any]:
        with self._lock:
            return self._frame(self._swarm.snapshot())

    def step(self) -> Dict[str, Any]:
        with self._lock:
            self._swarm.step()
            return self._frame(dict(self._swarm.latest_snapshot or {}))

    def inject(self, text: str) -> Dict[str, Any]:
        expression = parse_expression(text)
        with self._lock:
            task_id = self._swarm.inject_task(expression)
            frame = self._frame(self._swarm.snapshot())
        frame["task_id"] = task_id
        frame["expression"] = expression.serialize()
        return frame

    def reset(self) -> Dict[str, Any]:
        with self._lock:
            self._swarm = self._new_swarm()
            return self._frame(self._swarm.snapshot())


def _dashboard_html() -> bytes:
    return resources.files("asis").joinpath("dashboard.html").read_bytes()


def make_handler(session: DashboardSession):
    html = _dashboard_html()

    class Handler(BaseHTTPRequestHandler):
        server_version = f"asis/{__version__}"

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
            pass

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: Dict[str, Any]) -> None:
            self._send(status, json.dumps(payload, default=str).encode("utf-8"), "application/json")

        def _read_json(self) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return None, "invalid Content-Length"
            if length > MAX_BODY_BYTES:
                return None, "request body too large"
            raw = self.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                return None, "request body is not valid JSON"
            if not isinstance(data, dict):
                return None, "request body must be a JSON object"
            return data, None

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                self._send(HTTPStatus.OK, html, "text/html; charset=utf-8")
            elif path == "/api/state":
                self._json(HTTPStatus.OK, session.state())
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:
            path = self.path.split("?", 1)[0]
            data, error = self._read_json()
            if error:
                self._json(HTTPStatus.BAD_REQUEST, {"error": error})
                return
            assert data is not None
            if path == "/api/step":
                self._json(HTTPStatus.OK, session.step())
            elif path == "/api/reset":
                self._json(HTTPStatus.OK, session.reset())
            elif path == "/api/inject":
                task = data.get("task")
                if not isinstance(task, str) or not task.strip():
                    self._json(HTTPStatus.BAD_REQUEST, {"error": "'task' must be a non-empty string"})
                elif len(task) > MAX_TASK_CHARS:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": f"task is longer than {MAX_TASK_CHARS} characters"})
                else:
                    try:
                        self._json(HTTPStatus.OK, session.inject(task))
                    except ParseError as e:
                        self._json(HTTPStatus.BAD_REQUEST, {"error": str(e)})
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    return Handler


def create_server(host: str = "127.0.0.1", port: int = 8765, demo: bool = True) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), make_handler(DashboardSession(demo=demo)))
    server.daemon_threads = True
    return server


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True, demo: bool = True) -> int:
    try:
        server = create_server(host, port, demo)
    except OSError as e:
        print(f"error: could not listen on {host}:{port}: {e}", file=sys.stderr)
        return 1
    bound_host, bound_port = server.server_address[:2]
    shown_host = "localhost" if bound_host in ("127.0.0.1", "0.0.0.0", "::") else bound_host
    url = f"http://{shown_host}:{bound_port}/"
    print(f"ASIS dashboard running at {url}  (Ctrl+C to stop)", flush=True)
    if host not in ("127.0.0.1", "localhost", "::1"):
        print("warning: the dashboard has no authentication; anyone who can reach this address can drive the swarm",
              file=sys.stderr)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard.")
    finally:
        server.server_close()
    return 0
