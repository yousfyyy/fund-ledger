"""Temporary diagnostic endpoint: /api/diag

Reports the Python runtime version, whether the dependencies import,
whether app.py imports, and the traceback if it does not.
Remove this file once the deployment is verified.
"""

import json
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _redact(text):
    secret = (os.environ.get("DATABASE_URL") or "").strip()
    if secret:
        text = text.replace(secret, "<DATABASE_URL redacted>")
        try:
            from urllib.parse import urlsplit
            parts = urlsplit(secret)
            if parts.password:
                text = text.replace(parts.password, "<password redacted>")
        except Exception:
            pass
    return text


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        info = {"python": sys.version.split()[0], "root": ROOT}

        for module in ("flask", "werkzeug", "sqlalchemy", "psycopg"):
            try:
                mod = __import__(module)
                info[module] = getattr(mod, "__version__", "imported")
            except Exception as exc:
                info[module] = "FAIL: " + repr(exc)

        info["database_url_set"] = bool((os.environ.get("DATABASE_URL") or "").strip())
        info["files"] = sorted(os.listdir(ROOT))[:40]

        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        try:
            import app as _app  # noqa: F401
            info["app_import"] = "ok"
        except Exception:
            info["app_import"] = _redact(traceback.format_exc())[-1500:]

        body = json.dumps(info, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
