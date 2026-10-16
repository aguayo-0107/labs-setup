"""HTTP transport for a protocol adapter, on the standard library's server."""

from __future__ import annotations

import json
import threading
from abc import ABC, abstractmethod
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .protocol import ProtocolAdapter


class InboundServer(ABC):
    @property
    @abstractmethod
    def address(self) -> tuple[str, int]:
        """Host and port actually bound (port 0 resolves to a free port)."""

    @abstractmethod
    def serve_forever(self) -> None:
        """Serve until `shutdown` is called."""

    @abstractmethod
    def shutdown(self) -> None:
        """Stop serving and release the socket."""


class HttpGatewayServer(InboundServer):
    """POST / carries API calls; GET /health answers the container healthcheck."""

    CONTENT_TYPE = "application/x-amz-json-1.1"

    def __init__(self, protocol: ProtocolAdapter, host: str, port: int) -> None:
        handler = self._handler_for(protocol)
        self._server = ThreadingHTTPServer((host, port), handler)
        self._server.daemon_threads = True
        self._serving = threading.Event()

    @classmethod
    def _handler_for(cls, protocol: ProtocolAdapter) -> type[BaseHTTPRequestHandler]:
        content_type = cls.CONTENT_TYPE

        class Handler(BaseHTTPRequestHandler):
            def _reply(self, status: int, document: dict, kind: str) -> None:
                payload = json.dumps(document).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_POST(self) -> None:  # noqa: N802 - name fixed by BaseHTTPRequestHandler
                length = int(self.headers.get("Content-Length") or 0)
                status, document = protocol.handle(self.headers.get("X-Amz-Target"), self.rfile.read(length))
                self._reply(status, document, content_type)

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/health":
                    self._reply(200, {"status": "ok"}, "application/json")
                else:
                    self._reply(404, {"message": "not found"}, "application/json")

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                return

        return Handler

    @property
    def address(self) -> tuple[str, int]:
        host, port = self._server.server_address[:2]
        return str(host), int(port)

    def serve_forever(self) -> None:
        self._serving.set()
        self._server.serve_forever(poll_interval=0.2)

    def shutdown(self) -> None:
        # socketserver's shutdown() waits for a running serve_forever loop and
        # would block forever on a server that was built but never served.
        if self._serving.is_set():
            self._server.shutdown()
        self._server.server_close()
