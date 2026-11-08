"""Vercel entrypoint.

Vercel looks for a Flask instance named ``app`` in this file. The real
application lives in ``webapp.py``; it is imported defensively so that a
startup failure produces a readable message instead of Vercel's opaque
"FUNCTION_INVOCATION_FAILED" page.
"""

import os
import traceback

from flask import Flask


def _redact(text):
    secret = (os.environ.get("DATABASE_URL") or "").strip()
    if not secret:
        return text
    text = text.replace(secret, "<DATABASE_URL redacted>")
    try:
        from urllib.parse import urlsplit

        password = urlsplit(secret).password
        if password:
            text = text.replace(password, "<password redacted>")
    except ValueError:
        pass
    return text


try:
    from webapp import app  # noqa: F401
except BaseException:  # pragma: no cover - only on a broken deployment
    _STARTUP_ERROR = _redact(traceback.format_exc())

    app = Flask(__name__)

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def _startup_failure(path):
        return (
            "STARTUP FAILED\n\n" + _STARTUP_ERROR,
            500,
            {"Content-Type": "text/plain; charset=utf-8"},
        )


if __name__ == "__main__":
    from webapp import run_dev

    run_dev()
