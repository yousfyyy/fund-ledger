import datetime as dt
import logging
import os
import re
import secrets
import urllib.parse

from flask import Flask, abort, g, request, send_from_directory
from flask import redirect as flask_redirect
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import HTTPException

import db
import templates as T
from db import CURRENCY, money

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DIR = os.path.join(BASE_DIR, "public")
STATIC_DIR = os.path.join(PUBLIC_DIR, "static")
PORT = int(os.environ.get("PORT", "8000"))
SESSION_COOKIE = "fund_session"
IS_VERCEL = bool(os.environ.get("VERCEL"))

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 1_000_000
app.config["PROPAGATE_EXCEPTIONS"] = False
app.logger.setLevel(logging.INFO)


# ---------------------------------------------------------------- helpers

def is_secure():
    if IS_VERCEL or request.headers.get("X-Forwarded-Proto", "").lower() == "https":
        return True
    return request.is_secure


def client_ip():
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or ""


def flash_to(path, ok=None, err=None):
    parts = []
    if ok:
        parts.append("ok=" + urllib.parse.quote(str(ok), safe=""))
    if err:
        parts.append("err=" + urllib.parse.quote(str(err), safe=""))
    if parts:
        sep = "&" if "?" in path else "?"
        path = path + sep + "&".join(parts)
    return flask_redirect(path, 303)


def csrf_error(path):
    if not g.session:
        return flask_redirect("/login", 303)
    if request.form.get("csrf", "") != g.session.get("csrf", ""):
        return flash_to(path, err="Session expired or invalid. Please try again.")
    return None


def require_admin():
    if not g.session:
        return flask_redirect("/login", 303)
    if g.session["role"] != "admin":
        return flash_to("/", err="Admin access is required.")
    return None


def render(content, status=200):
    token = g.session.get("csrf", "") if g.session else ""
    page = T.layout(
        _title(content),
        content.replace("__CSRF__", token),
        user=g.session,
        notice=request.args.get("ok"),
        error=request.args.get("err"),
    )
    return page, status


def _title(content):
    match = re.search(r"<h1[^>]*>(.*?)</h1>", content, re.S)
    if match:
        return re.sub("<[^>]+>", "", match.group(1)).strip() or "Account"
    return "Account"


def _error_page(status, message):
    body = T.layout(str(status), f"""
    <div class="signin"><div class="signin-card">
      <div class="brand big"><span class="mark">{CURRENCY}</span></div>
      <h1>{message}</h1>
      <p class="muted">HTTP {status}</p>
      <a class="btn btn-primary wide" href="/">Back to home</a>
    </div></div>""")
    return body, status


# ---------------------------------------------------------------- lifecycle

@app.before_request
def _load_session():
    token = request.cookies.get(SESSION_COOKIE)
    found = db.get_session(token)
    g.session = dict(found, token=token) if found else None


@app.before_request
def _force_password_change():
    if not g.session or not g.session.get("must_change"):
        return None
    path = request.path
    if path == "/password" or path == "/logout" or path.startswith("/static/"):
        return None
    if request.method == "GET":
        return flask_redirect("/password", 303)
    return flash_to("/password", err="Please choose a new password first.")


@app.errorhandler(HTTPException)
def _http_error(exc):
    if exc.code == 404:
        return _error_page(404, "Page not found")
    if exc.code >= 500:
        return _error_page(500, "Something went wrong on our side")
    return exc


@app.errorhandler(Exception)
def _unhandled(exc):
    app.logger.exception("Unhandled error on %s %s", request.method, request.path)
    return _error_page(500, "Something went wrong on our side")


@app.route("/static/<path:filename>")
def static_files(filename):
    base = os.path.realpath(STATIC_DIR)
    full = os.path.realpath(os.path.join(base, filename))
    if not full.startswith(base + os.sep) or not os.path.isfile(full):
        abort(404)
    response = send_from_directory(base, filename)
    response.headers["Cache-Control"] = "public, max-age=300"
    return response


# ------------------------------------------------------------------ pages

@app.get("/")
def home():
    if not g.session:
        return render(T.login_page())
    if g.session["role"] == "admin":
        month = dt.date.today().strftime("%Y-%m")
        content = T.admin_home(
            db.dashboard_stats(),
            db.list_members(),
            month,
            dues_message=request.args.get("ok"),
            flash_error=request.args.get("err"),
        )
        return render(content)
    member = db.get_member(g.session.get("member_id") or 0)
    entries = db.ledger(member["id"]) if member else []
    return render(T.member_home(member, entries, g.session))


# ------------------------------------------------------------------ auth

@app.route("/login", methods=["GET", "POST"])
def login():
    if g.session and request.method == "GET":
        return flask_redirect("/", 303)
    if request.method == "GET":
        return render(T.login_page())

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    key = f"login:{username.lower()}|{client_ip()}"
    if db.login_blocked(key):
        return flash_to("/login", err="Too many attempts. Try again in 15 minutes.")

    user = db.authenticate(username, password)
    if user is None:
        db.record_failed_login(key)
        return flash_to("/login", err="Wrong username or password.")

    db.clear_login_attempts(key)
    db.touch_login(user["id"])
    token, _csrf = db.create_session(user["id"])
    target = "/password" if user["must_change"] else "/"
    response = flask_redirect(target, 303)
    response.set_cookie(SESSION_COOKIE, token, max_age=1209600, path="/",
                        httponly=True, samesite="Lax", secure=is_secure())
    return response


@app.post("/logout")
def logout():
    error = csrf_error(request.path)
    if error:
        return error
    response = flask_redirect("/login", 303)
    response.delete_cookie(SESSION_COOKIE, path="/")
    db.delete_session(g.session["token"])
    return response


@app.route("/password", methods=["GET", "POST"])
def password():
    if not g.session:
        return flask_redirect("/login", 303)
    if request.method == "GET":
        return render(T.password_page(g.session))

    error = csrf_error(request.path)
    if error:
        return error
    pw, pw2 = request.form.get("password", ""), request.form.get("password2", "")
    if pw != pw2:
        return flash_to("/password", err="The two passwords do not match.")
    try:
        db.set_password(g.session["user_id"], pw)
    except ValueError as exc:
        return flash_to("/password", err=str(exc))
    return flash_to("/", ok="Password updated.")


# ---------------------------------------------------------------- members

@app.get("/members")
def members_list():
    denied = require_admin()
    if denied:
        return denied
    return render(T.members_page(db.list_members()))


@app.route("/members/new", methods=["GET", "POST"])
def member_new():
    denied = require_admin()
    if denied:
        return denied
    if request.method == "GET":
        return render(T.member_form(None, error=request.args.get("err")))

    error = csrf_error(request.path)
    if error:
        return error
    try:
        due_date = db.parse_date(request.form.get("due_date"))
        member_id = db.create_member(
            name=request.form.get("name"),
            phone=request.form.get("phone", ""),
            email=request.form.get("email", ""),
            note=request.form.get("note", ""),
            due_amount=db.parse_money(request.form.get("due_amount")),
            due_day=db.parse_int(request.form.get("due_day"), None, 1, 28),
            due_date=due_date.isoformat() if due_date else None,
            status=request.form.get("status", "active"),
        )
        username = request.form.get("username", "").strip()
        if username:
            db.create_user(username, request.form.get("password", ""),
                           role="member", member_id=member_id, must_change=1)
    except ValueError as exc:
        return flash_to("/members/new", err=str(exc))
    except IntegrityError:
        return flash_to("/members/new", err="That username is already taken.")
    return flash_to(f"/members/{member_id}", ok="Member created.")


@app.route("/members/<int:member_id>", methods=["GET"])
def member_detail(member_id):
    denied = require_admin()
    if denied:
        return denied
    member = db.get_member(member_id)
    if member is None:
        return flash_to("/members", err="That member does not exist.")
    linked = [u for u in db.list_users() if u.get("member_id") == member["id"]]
    return render(T.member_detail(member, db.ledger(member["id"]), linked,
                                  flash=request.args.get("ok"),
                                  flash_error=request.args.get("err")))


@app.route("/members/<int:member_id>/edit", methods=["GET", "POST"])
def member_edit(member_id):
    denied = require_admin()
    if denied:
        return denied
    member = db.get_member(member_id)
    if member is None:
        return flash_to("/members", err="That member does not exist.")
    if request.method == "GET":
        return render(T.member_form(member, error=request.args.get("err")))

    error = csrf_error(request.path)
    if error:
        return error
    try:
        due_date = db.parse_date(request.form.get("due_date"))
        db.update_member(
            member["id"],
            name=request.form.get("name", member["name"]),
            phone=request.form.get("phone", ""),
            email=request.form.get("email", ""),
            note=request.form.get("note", ""),
            due_amount=db.parse_money(request.form.get("due_amount")),
            due_day=db.parse_int(request.form.get("due_day"), None, 1, 28),
            due_date=due_date.isoformat() if due_date else None,
            status=request.form.get("status", "active"),
        )
    except ValueError as exc:
        return flash_to(f"/members/{member_id}/edit", err=str(exc))
    return flash_to(f"/members/{member_id}", ok="Member updated.")


@app.post("/members/<int:member_id>/delete")
def member_delete(member_id):
    denied = require_admin()
    if denied:
        return denied
    error = csrf_error(request.path)
    if error:
        return error
    db.delete_member(member_id)
    return flash_to("/members", ok="Member and their transactions were deleted.")


def _member_for_write(member_id):
    member = db.get_member(member_id)
    if member is None:
        return None, flash_to("/members", err="That member does not exist.")
    error = csrf_error(request.path)
    if error:
        return None, error
    return member, None


@app.post("/members/<int:member_id>/charges")
def add_charge(member_id):
    denied = require_admin()
    if denied:
        return denied
    member, error = _member_for_write(member_id)
    if error:
        return error
    try:
        db.add_charge(member["id"],
                      db.parse_money(request.form.get("amount")),
                      kind=request.form.get("kind", "other"),
                      description=request.form.get("description", ""),
                      created_by=g.session["user_id"])
    except ValueError as exc:
        return flash_to(f"/members/{member_id}", err=str(exc))
    return flash_to(f"/members/{member_id}", ok="Charge added.")


@app.post("/members/<int:member_id>/payments")
def add_payment(member_id):
    denied = require_admin()
    if denied:
        return denied
    member, error = _member_for_write(member_id)
    if error:
        return error
    try:
        paid_at = db.parse_date(request.form.get("paid_at")) or dt.date.today()
        db.add_payment(member["id"],
                       db.parse_money(request.form.get("amount")),
                       method=request.form.get("method", "cash"),
                       reference=request.form.get("reference", ""),
                       note=request.form.get("note", ""),
                       paid_at=paid_at.isoformat(),
                       created_by=g.session["user_id"])
    except ValueError as exc:
        return flash_to(f"/members/{member_id}", err=str(exc))
    return flash_to(f"/members/{member_id}", ok="Payment recorded.")


@app.post("/members/<int:member_id>/payouts")
def add_payout(member_id):
    denied = require_admin()
    if denied:
        return denied
    member, error = _member_for_write(member_id)
    if error:
        return error
    try:
        paid_at = db.parse_date(request.form.get("paid_at")) or dt.date.today()
        db.add_payout(member["id"],
                      db.parse_money(request.form.get("amount")),
                      note=request.form.get("note", ""),
                      paid_at=paid_at.isoformat(),
                      created_by=g.session["user_id"])
    except ValueError as exc:
        return flash_to(f"/members/{member_id}", err=str(exc))
    return flash_to(f"/members/{member_id}", ok="Payout recorded.")


# ---------------------------------------------------------------- billing

@app.get("/billing")
def billing():
    denied = require_admin()
    if denied:
        return denied
    month = dt.date.today().strftime("%Y-%m")
    return render(T.billing_page(db.monthly_breakdown(), month,
                                 notice=request.args.get("ok"),
                                 error=request.args.get("err")))


@app.post("/billing/run")
def billing_run():
    denied = require_admin()
    if denied:
        return denied
    error = csrf_error(request.path)
    if error:
        return error
    month = request.form.get("month", "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        return flash_to("/", err="Pick a month in YYYY-MM format.")
    try:
        override = db.parse_money(request.form.get("amount"), None)
    except ValueError:
        return flash_to("/", err="The override amount is not a valid number.")
    created, skipped, total = db.run_dues(month, override, created_by=g.session["user_id"])
    return flash_to("/", ok=f"Dues for {month}: {created} charge(s) created "
                            f"({CURRENCY}{money(total)}), {skipped} skipped.")


# ------------------------------------------------------------------ users

@app.get("/users")
def users_list():
    denied = require_admin()
    if denied:
        return denied
    return render(T.users_page(db.list_users(),
                               error=request.args.get("err"),
                               notice=request.args.get("ok")))


@app.route("/users/new", methods=["GET", "POST"])
def user_new():
    denied = require_admin()
    if denied:
        return denied
    if request.method == "GET":
        return render(T.user_form(db.list_members(), error=request.args.get("err")))

    error = csrf_error(request.path)
    if error:
        return error
    member_raw = request.form.get("member_id", "").strip()
    try:
        db.create_user(
            request.form.get("username", ""),
            request.form.get("password", ""),
            role=request.form.get("role", "member"),
            member_id=int(member_raw) if member_raw else None,
            must_change=1,
        )
    except ValueError as exc:
        return flash_to("/users/new", err=str(exc))
    return flash_to("/users", ok="Login created.")


@app.post("/users/<int:user_id>/reset")
def user_reset(user_id):
    denied = require_admin()
    if denied:
        return denied
    error = csrf_error(request.path)
    if error:
        return error
    new_pw = secrets.token_urlsafe(8)
    try:
        db.set_password(user_id, new_pw)
    except ValueError:
        return flash_to("/users", err="Could not reset that password.")
    return flash_to("/users", ok=f"Temporary password for that account: {new_pw}")


# ------------------------------------------------------------------ export

@app.get("/export.csv")
def export_csv():
    denied = require_admin()
    if denied:
        return denied
    stamp = dt.date.today().isoformat()
    body = db.members_csv()
    return app.response_class(
        body, mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="members-{stamp}.csv"'},
    )


# -------------------------------------------------------------------- dev

def run_dev(host="0.0.0.0", port=PORT):
    db.init_db()
    print("=" * 62)
    print(f"  Fund Ledger (development)")
    print(f"  Open: http://127.0.0.1:{port}/login")
    print(f"  Sign in as: {db.DEFAULT_ADMIN_USER} / {db.DEFAULT_ADMIN_PASS}")
    print(f"  Database: {db._database_url()}")
    print("=" * 62)
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    run_dev()
