"""Local fixture site for User Behaviour Agent tests.

Deliberately imperfect, and each defect is there to prove one specific part
of the agent works:

    a button with no handler          -> Outcome.NO_RESPONSE, UX-DEAD
    a 620 ms search suggestion        -> UX-SLOW-SEARCH
    add-to-cart with no pending state -> UX-SILENT
    a banner injected after load      -> UX-SHIFT
    an icon button with no name       -> UX-A11Y-NAME
    `outline: none` with no replacement -> UX-A11Y-FOCUS
    "Buy now", "Place order", "Empty the cart" -> never pressed at all
    a card-number field               -> never typed into

Binds 127.0.0.1 only. The behaviour agent is never pointed at a public site
by this repository's own test suite — the same boundary the security
integration tests hold.
"""
from __future__ import annotations

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SITE = Path(__file__).parent / "ux_site"


class UXHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        # Serve the extensionless root as index.html; everything else is a
        # plain static file, so timing measured here is the page's own.
        if self.path in ("", "/"):
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self):
        # Nothing here should ever be reached: the agent submits no form
        # except a search box, which is a GET. If a test ever sees a POST
        # land, the safety boundary has broken and the test should fail.
        self.send_response(405)
        self.end_headers()

    def log_message(self, *args):
        pass


class UXFixtureSite:
    """Context manager yielding the base URL of a running fixture site."""

    def __init__(self, port: int = 0):
        handler = partial(UXHandler, directory=str(SITE))
        self.server = ThreadingHTTPServer(("127.0.0.1", port), handler)
        self.port = self.server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.posts: list[str] = []
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "UXFixtureSite":
        self._thread = threading.Thread(target=self.server.serve_forever,
                                        daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.server.shutdown()
        self.server.server_close()
        if self._thread:
            self._thread.join(timeout=5)
