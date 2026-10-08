import csv
import datetime as dt
import hashlib
import io
import os
import secrets
from contextlib import contextmanager

from sqlalchemy import (
    Column,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    func,
    text,
)
from sqlalchemy.exc import IntegrityError

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CURRENCY = "$"
DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_PASS = "admin123"

LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_MINUTES = 15

metadata = MetaData()

members = Table(
    "members", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", Text, nullable=False),
    Column("phone", Text, nullable=False, server_default=""),
    Column("email", Text, nullable=False, server_default=""),
    Column("note", Text, nullable=False, server_default=""),
    Column("due_amount", Integer, nullable=False, server_default="0"),
    Column("due_day", Integer, nullable=True),
    Column("due_date", String(10), nullable=True),
    Column("status", String(16), nullable=False, server_default="active"),
    Column("created_at", String(19), nullable=False),
)

users = Table(
    "users", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("username", String(64), nullable=False),
    Column("password_hash", String(128), nullable=False),
    Column("salt", String(32), nullable=False),
    Column("role", String(16), nullable=False, server_default="member"),
    Column("member_id", Integer, ForeignKey("members.id", ondelete="CASCADE"), nullable=True),
    Column("must_change", Integer, nullable=False, server_default="0"),
    Column("created_at", String(19), nullable=False),
    Column("last_login", String(19), nullable=True),
)

sessions = Table(
    "sessions", metadata,
    Column("id", String(64), primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("csrf", String(64), nullable=False),
    Column("created_at", String(19), nullable=False),
    Column("expires_at", String(19), nullable=False),
)

charges = Table(
    "charges", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("member_id", Integer, ForeignKey("members.id", ondelete="CASCADE"), nullable=False),
    Column("amount", Integer, nullable=False),
    Column("kind", String(16), nullable=False, server_default="other"),
    Column("description", Text, nullable=False, server_default=""),
    Column("billing_month", String(7), nullable=True),
    Column("created_by", Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    Column("created_at", String(19), nullable=False),
)

payments = Table(
    "payments", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("member_id", Integer, ForeignKey("members.id", ondelete="CASCADE"), nullable=False),
    Column("amount", Integer, nullable=False),
    Column("method", String(16), nullable=False, server_default="cash"),
    Column("reference", Text, nullable=False, server_default=""),
    Column("note", Text, nullable=False, server_default=""),
    Column("paid_at", String(10), nullable=False),
    Column("created_by", Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    Column("created_at", String(19), nullable=False),
)

payouts = Table(
    "payouts", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("member_id", Integer, ForeignKey("members.id", ondelete="CASCADE"), nullable=False),
    Column("amount", Integer, nullable=False),
    Column("note", Text, nullable=False, server_default=""),
    Column("paid_at", String(10), nullable=False),
    Column("created_by", Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    Column("created_at", String(19), nullable=False),
)

login_attempts = Table(
    "login_attempts", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("key", String(255), nullable=False),
    Column("at", String(19), nullable=False),
)

Index("ix_charges_member", charges.c.member_id)
Index("ix_payments_member", payments.c.member_id)
Index("ix_payouts_member", payouts.c.member_id)
Index("ix_users_member", users.c.member_id)
Index("ix_login_attempts_key", login_attempts.c.key)
Index("uq_charges_billing", charges.c.member_id, charges.c.billing_month, unique=True)
Index("uq_users_username_ci", func.lower(users.c.username), unique=True)


# ---------------------------------------------------------------- engine

def _database_url():
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        return "sqlite:///" + os.path.join(BASE_DIR, "fund.db").replace("\\", "/")
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def _build_engine():
    url = _database_url()
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url, pool_pre_ping=True, pool_recycle=300)


engine = _build_engine()


@contextmanager
def get_db():
    conn = engine.connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def rows(conn, sql, **params):
    return [dict(r) for r in conn.execute(text(sql), params).mappings().all()]


def row(conn, sql, **params):
    r = conn.execute(text(sql), params).mappings().first()
    return dict(r) if r else None


# ---------------------------------------------------------------- helpers

def now():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_str():
    return dt.date.today().isoformat()


def parse_money(value, default=0):
    if value is None:
        return default
    s = str(value).strip().replace(",", "").replace(CURRENCY, "").replace("\u20ac", "").replace("\u00a3", "")
    if not s:
        return default
    negative = s.startswith("-")
    if negative:
        s = s[1:]
    if not s:
        return default
    if "." in s:
        whole, frac = s.split(".", 1)
        frac = (frac + "00")[:2]
    else:
        whole, frac = s, "00"
    whole = whole or "0"
    if not whole.isdigit() or not frac.isdigit():
        raise ValueError(f"Not a valid amount: {value!r}")
    cents = int(whole) * 100 + int(frac)
    return -cents if negative else cents


def money(cents):
    cents = int(cents or 0)
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}{cents // 100:,}.{cents % 100:02d}"


def parse_int(value, default=None, lo=None, hi=None):
    if value is None or str(value).strip() == "":
        return default
    try:
        n = int(str(value).strip())
    except ValueError:
        raise ValueError("Not a whole number")
    if lo is not None and n < lo:
        raise ValueError(f"Must be at least {lo}")
    if hi is not None and n > hi:
        raise ValueError(f"Must be at most {hi}")
    return n


def parse_date(value, default=None):
    if value is None or str(value).strip() == "":
        return default
    try:
        return dt.date.fromisoformat(str(value).strip())
    except ValueError:
        raise ValueError("Use the date format YYYY-MM-DD")


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 200000)
    return digest.hex(), salt


def verify_password(password, salt, expected):
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 200000)
    return secrets.compare_digest(digest.hex(), expected)


def init_db():
    """Create every table and seed the default admin. Safe to run repeatedly."""
    metadata.create_all(engine)
    with get_db() as conn:
        existing = row(conn, "SELECT id FROM users WHERE username = :u", u=DEFAULT_ADMIN_USER)
        if existing is None:
            pw_hash, salt = hash_password(DEFAULT_ADMIN_PASS)
            conn.execute(
                users.insert().values(
                    username=DEFAULT_ADMIN_USER, password_hash=pw_hash, salt=salt,
                    role="admin", must_change=1, created_at=now(),
                )
            )
            return True
    return False


# ---------------------------------------------------------------- sessions

def create_session(user_id):
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    expires = (dt.datetime.now() + dt.timedelta(days=14)).strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        conn.execute(sessions.insert().values(
            id=token, user_id=user_id, csrf=csrf, created_at=now(), expires_at=expires))
    return token, csrf


def get_session(token):
    if not token:
        return None
    with get_db() as conn:
        found = row(
            conn,
            """
            SELECT s.id AS token, s.csrf, s.user_id, s.expires_at,
                   u.username, u.role, u.member_id, u.must_change
              FROM sessions s
              JOIN users u ON u.id = s.user_id
             WHERE s.id = :t AND s.expires_at > :now
            """,
            t=token, now=now(),
        )
        return found


def delete_session(token):
    if not token:
        return
    with get_db() as conn:
        conn.execute(text("DELETE FROM sessions WHERE id = :t"), {"t": token})


def touch_login(user_id):
    with get_db() as conn:
        conn.execute(users.update().where(users.c.id == user_id).values(last_login=now()))


# ---------------------------------------------------------------- login guard

def login_blocked(key):
    cutoff = (dt.datetime.now() - dt.timedelta(minutes=LOGIN_WINDOW_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        n = conn.execute(
            text("SELECT COUNT(*) FROM login_attempts WHERE key = :k AND at >= :c"),
            {"k": key, "c": cutoff},
        ).scalar()
        return bool(n and n >= LOGIN_MAX_ATTEMPTS)


def record_failed_login(key):
    cutoff = (dt.datetime.now() - dt.timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        conn.execute(text("DELETE FROM login_attempts WHERE at < :c"), {"c": cutoff})
        conn.execute(login_attempts.insert().values(key=key, at=now()))


def clear_login_attempts(key):
    with get_db() as conn:
        conn.execute(text("DELETE FROM login_attempts WHERE key = :k"), {"k": key})


# ---------------------------------------------------------------- users

def authenticate(username, password):
    username = (username or "").strip()
    with get_db() as conn:
        found = row(conn, "SELECT * FROM users WHERE lower(username) = lower(:u)", u=username)
        if found is None:
            return None
        if not verify_password(password, found["salt"], found["password_hash"]):
            return None
        return found


def create_user(username, password, role="member", member_id=None, must_change=0):
    username = (username or "").strip()
    if not username:
        raise ValueError("Username is required")
    if len(username) > 64:
        raise ValueError("Username must be 64 characters or fewer")
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters")
    pw_hash, salt = hash_password(password)
    with get_db() as conn:
        exists = row(conn, "SELECT id FROM users WHERE lower(username) = lower(:u)", u=username)
        if exists:
            raise ValueError("That username is already taken")
        conn.execute(users.insert().values(
            username=username, password_hash=pw_hash, salt=salt, role=role,
            member_id=member_id, must_change=1 if must_change else 0, created_at=now(),
        ))


def list_users():
    with get_db() as conn:
        return rows(
            conn,
            """
            SELECT u.*, m.name AS member_name
              FROM users u LEFT JOIN members m ON m.id = u.member_id
             ORDER BY u.role, lower(u.username)
            """,
        )


def set_password(user_id, password):
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters")
    pw_hash, salt = hash_password(password)
    with get_db() as conn:
        conn.execute(users.update().where(users.c.id == user_id).values(
            password_hash=pw_hash, salt=salt, must_change=0))


# ---------------------------------------------------------------- members

def _member_due_status(m, remaining):
    if remaining <= 0:
        return "settled"
    if m.get("due_date"):
        return "overdue" if dt.date.today() > dt.date.fromisoformat(m["due_date"]) else "due"
    if m.get("due_day"):
        return "overdue" if dt.date.today().day > m["due_day"] else "due"
    return "open"


def _with_balance(m):
    if m is None:
        return None
    m["remaining"] = m["charged"] - m["paid"]
    m["state"] = _member_due_status(m, m["remaining"])
    return m


MEMBER_BALANCES = """
    SELECT m.*,
           (SELECT COALESCE(SUM(amount),0) FROM charges  WHERE member_id = m.id) AS charged,
           (SELECT COALESCE(SUM(amount),0) FROM payments WHERE member_id = m.id) AS paid,
           (SELECT COALESCE(SUM(amount),0) FROM payouts  WHERE member_id = m.id) AS disbursed,
           (SELECT COUNT(*) FROM users WHERE member_id = m.id) AS login_count
      FROM members m
"""


def list_members(status=None):
    with get_db() as conn:
        if status:
            found = rows(conn, MEMBER_BALANCES + " WHERE m.status = :s ORDER BY lower(m.name)", s=status)
        else:
            found = rows(conn, MEMBER_BALANCES + " ORDER BY lower(m.name)")
        return [_with_balance(m) for m in found]


def get_member(member_id):
    with get_db() as conn:
        found = row(conn, MEMBER_BALANCES + " WHERE m.id = :i", i=member_id)
        return _with_balance(found)


def create_member(name, phone="", email="", note="", due_amount=0,
                  due_day=None, due_date=None, status="active"):
    name = (name or "").strip()
    if not name:
        raise ValueError("Member name is required")
    with get_db() as conn:
        result = conn.execute(members.insert().values(
            name=name, phone=(phone or "").strip(), email=(email or "").strip(),
            note=(note or "").strip(), due_amount=int(due_amount or 0),
            due_day=due_day, due_date=due_date, status=status, created_at=now(),
        ))
        return int(result.inserted_primary_key[0])


def update_member(member_id, **fields):
    allowed = ("name", "phone", "email", "note", "due_amount", "due_day", "due_date", "status")
    clean = {k: v for k, v in fields.items() if k in allowed}
    if not clean:
        return
    with get_db() as conn:
        conn.execute(members.update().where(members.c.id == member_id).values(**clean))


def delete_member(member_id):
    with get_db() as conn:
        conn.execute(text("DELETE FROM members WHERE id = :i"), {"i": member_id})


# ---------------------------------------------------------------- entries

def add_charge(member_id, amount, kind="other", description="", billing_month=None, created_by=None):
    amount = int(amount)
    if amount == 0:
        raise ValueError("Amount cannot be zero")
    try:
        with get_db() as conn:
            if billing_month:
                dup = row(
                    conn,
                    "SELECT description FROM charges WHERE member_id = :m AND billing_month = :b",
                    m=member_id, b=billing_month)
                if dup:
                    raise ValueError(f"Dues for {billing_month} already recorded: {dup['description']}")
            conn.execute(charges.insert().values(
                member_id=member_id, amount=amount, kind=kind,
                description=(description or "").strip() or "Charge",
                billing_month=billing_month, created_by=created_by, created_at=now(),
            ))
    except IntegrityError:
        raise ValueError(f"Dues for {billing_month} were already recorded.")


def add_payment(member_id, amount, method="cash", reference="", note="", paid_at=None, created_by=None):
    amount = int(amount)
    if amount <= 0:
        raise ValueError("Payment must be more than zero")
    with get_db() as conn:
        conn.execute(payments.insert().values(
            member_id=member_id, amount=amount, method=method,
            reference=(reference or "").strip(), note=(note or "").strip(),
            paid_at=paid_at or today_str(), created_by=created_by, created_at=now(),
        ))


def add_payout(member_id, amount, note="", paid_at=None, created_by=None):
    amount = int(amount)
    if amount <= 0:
        raise ValueError("Payout must be more than zero")
    with get_db() as conn:
        conn.execute(payouts.insert().values(
            member_id=member_id, amount=amount, note=(note or "").strip(),
            paid_at=paid_at or today_str(), created_by=created_by, created_at=now(),
        ))


def ledger(member_id):
    """Combined, chronologically ordered entries with a running balance."""
    entries = []
    with get_db() as conn:
        for r in rows(conn, "SELECT id, amount, kind, description, created_at "
                            "FROM charges WHERE member_id = :m", m=member_id):
            entries.append({"type": "charge", "amount": r["amount"],
                            "label": r["description"] or "Charge",
                            "detail": r["kind"], "at": r["created_at"],
                            "sort": r["created_at"], "ref": f"C-{r['id']}"})
        for r in rows(conn, "SELECT id, amount, method, reference, note, paid_at, created_at "
                            "FROM payments WHERE member_id = :m", m=member_id):
            extra = " ".join(x for x in (r["method"], r["reference"], r["note"]) if x)
            entries.append({"type": "payment", "amount": r["amount"],
                            "label": r["note"] or "Payment", "detail": extra,
                            "at": r["paid_at"], "sort": r["created_at"],
                            "ref": f"P-{r['id']}"})
        for r in rows(conn, "SELECT id, amount, note, paid_at, created_at "
                            "FROM payouts WHERE member_id = :m", m=member_id):
            entries.append({"type": "payout", "amount": r["amount"],
                            "label": r["note"] or "Payout",
                            "detail": "does not change balance", "at": r["paid_at"],
                            "sort": r["created_at"], "ref": f"D-{r['id']}"})
    entries.sort(key=lambda e: (e["at"], e["ref"]))
    balance = 0
    for e in entries:
        if e["type"] == "charge":
            balance += e["amount"]
        elif e["type"] == "payment":
            balance -= e["amount"]
        e["balance"] = balance
    return entries


def run_dues(billing_month, amount_override=None, created_by=None):
    """Create this month's due charge for every active member with a plan."""
    created, skipped, total = 0, 0, 0
    with get_db() as conn:
        plan = rows(conn, "SELECT id, due_amount FROM members WHERE status = 'active'")
        existing = {r["billing_month"] + ":" + str(r["member_id"])
                    for r in rows(conn, "SELECT member_id, billing_month FROM charges "
                                        "WHERE billing_month IS NOT NULL")}
        for m in plan:
            amount = amount_override if amount_override is not None else m["due_amount"]
            if not amount:
                skipped += 1
                continue
            if f"{billing_month}:{m['id']}" in existing:
                skipped += 1
                continue
            conn.execute(charges.insert().values(
                member_id=m["id"], amount=int(amount), kind="dues",
                description=f"Dues \u2014 {billing_month}", billing_month=billing_month,
                created_by=created_by, created_at=now(),
            ))
            created += 1
            total += int(amount)
    return created, skipped, total


# ---------------------------------------------------------------- reports

def dashboard_stats():
    month_start = dt.date.today().replace(day=1).isoformat()
    with get_db() as conn:
        stats = row(
            conn,
            """
            SELECT
              (SELECT COUNT(*) FROM members WHERE status='active') AS members,
              (SELECT COALESCE(SUM(amount),0) FROM charges)        AS charged,
              (SELECT COALESCE(SUM(amount),0) FROM payments)       AS paid,
              (SELECT COALESCE(SUM(amount),0) FROM payouts)        AS disbursed,
              (SELECT COALESCE(SUM(amount),0) FROM payments  WHERE paid_at  >= :ms) AS month_paid,
              (SELECT COALESCE(SUM(amount),0) FROM charges   WHERE created_at >= :ms) AS month_charged,
              (SELECT COUNT(*) FROM payments WHERE paid_at >= :ms) AS month_count
            """,
            ms=month_start,
        ) or {}
        stats.setdefault("members", 0)
        stats["outstanding"] = stats["charged"] - stats["paid"]
        stats["recent"] = rows(
            conn,
            """
            SELECT * FROM (
                SELECT 'payment' AS type, m.name AS member, p.amount,
                       p.paid_at AS at, p.reference AS ref, p.created_at AS sort
                  FROM payments p JOIN members m ON m.id = p.member_id
                UNION ALL
                SELECT 'charge', m.name, c.amount, substr(c.created_at,1,10),
                       c.description, c.created_at
                  FROM charges c JOIN members m ON m.id = c.member_id
                UNION ALL
                SELECT 'payout', m.name, p.amount, p.paid_at, p.note, p.created_at
                  FROM payouts p JOIN members m ON m.id = p.member_id
            ) AS activity ORDER BY sort DESC, at DESC LIMIT 12
            """,
        )
        return stats


def monthly_breakdown():
    with get_db() as conn:
        return rows(
            conn,
            """
            SELECT substr(paid_at,1,7) AS month, SUM(amount) AS total, COUNT(*) AS n
              FROM payments GROUP BY substr(paid_at,1,7)
             ORDER BY month DESC LIMIT 24
            """,
        )


def members_csv():
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Name", "Phone", "Email", "Status", "Due amount", "Due day",
                     "Due date", "Charged", "Paid", "Remaining", "State", "Joined"])
    for m in list_members():
        writer.writerow([
            m["name"], m["phone"], m["email"], m["status"],
            money(m["due_amount"]), m["due_day"] or "", m["due_date"] or "",
            money(m["charged"]), money(m["paid"]), money(m["remaining"]),
            m["state"], m["created_at"][:10],
        ])
    return out.getvalue()
