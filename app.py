"""Vercel / Flask entrypoint with visible boot errors.

On success, re-exports everything from application.py (so tests and
`flask --app app` keep working). On failure, serves the traceback as HTML
instead of an opaque FUNCTION_INVOCATION_FAILED page.
"""

from __future__ import annotations

import os
import traceback

# Force pure-Python DB path before any driver import.
os.environ["MYSQL_CONNECTOR_PYTHON_IMPL"] = "pure"

_BOOT_TRACEBACK: str | None = None

try:
    from application import *  # noqa: F401,F403
    from application import app as app
except Exception:  # noqa: BLE001 - never crash the serverless import
    from flask import Flask

    _BOOT_TRACEBACK = traceback.format_exc()
    app = Flask(__name__)

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def boot_failed(path: str = ""):  # noqa: ARG001
        return (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<title>JC Aqua boot failed</title></head>"
            "<body style='font-family:Segoe UI,Arial,sans-serif;background:#0f1720;color:#fecaca;"
            "padding:2rem;line-height:1.5'>"
            "<h1 style='color:#fff'>App failed to start on Vercel</h1>"
            "<p style='color:#94a3b8'>Copy this full error into Cursor chat.</p>"
            f"<pre style='white-space:pre-wrap;background:#020617;color:#e2e8f0;padding:1rem;"
            f"border-radius:12px;border:1px solid #334155'>{_BOOT_TRACEBACK}</pre>"
            "</body></html>"
        ), 500
