"""Local fixture site for integration tests.

Serves deliberately broken headers so collectors have something real to find.
Integration tests NEVER touch a public website: they bind 127.0.0.1 only.
"""
from __future__ import annotations

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SITE = Path(__file__).parent / "site"


class FixtureHandler(SimpleHTTPRequestHandler):
    """A site with realistic security defects."""

    def end_headers(self):
        # Present, so a PASS is testable:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        # Deliberately ABSENT: Content-Security-Policy, Strict-Transport-Security
        # Deliberately leaky (WEB-10):
        self.send_header("Server", "FixtureHTTP/2.4.1")
        self.send_header("X-Powered-By", "PHP/8.1.2")
        # Insecure cookie (WEB-05 must FAIL on this):
        if self.path == "/":
            self.send_header("Set-Cookie", "sessionid=abc123def456; Path=/")
            self.send_header("Set-Cookie",
                             "consent=1; Path=/; Secure; HttpOnly; SameSite=Lax")
        super().end_headers()

    def do_GET(self):
        if self.path.startswith("/assessment-probe-"):
            body = (b"<h1>404 Not Found</h1><pre>Traceback (most recent call last):\n"
                    b'  File "/var/www/fixture/app.py", line 42\n</pre>')
            self.send_response(404)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/robots.txt":
            body = b"User-agent: *\nDisallow: /admin\nDisallow: /internal\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_message(self, *args):
        pass  # keep test output clean


class FixtureSite:
    """Context manager yielding the base URL of a running fixture site."""

    def __init__(self, port: int = 0):
        handler = partial(FixtureHandler, directory=str(SITE))
        self.server = ThreadingHTTPServer(("127.0.0.1", port), handler)
        self.port = self.server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "FixtureSite":
        self._thread = threading.Thread(target=self.server.serve_forever,
                                        daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.server.shutdown()
        self.server.server_close()
        if self._thread:
            self._thread.join(timeout=5)
