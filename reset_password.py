"""Reset a user's password.

Usage:
    python reset_password.py <username> [new-password]

If you leave the password out you will be prompted for it.
Run it against the same database the site uses, e.g.

    DATABASE_URL="postgres://..." python reset_password.py admin
"""
import getpass
import sys

import db


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    username = sys.argv[1].strip()
    with db.get_db() as conn:
        found = db.row(conn, "SELECT id FROM users WHERE lower(username) = lower(:u)",
                       u=username)
    if found is None:
        print(f"No user called '{username}'. Existing usernames:")
        for u in db.list_users():
            print(f"  - {u['username']} ({u['role']})")
        return 1

    new_password = sys.argv[2] if len(sys.argv) > 2 else getpass("New password: ")
    if len(new_password) < 6:
        print("Password must be at least 6 characters.")
        return 1

    db.set_password(found["id"], new_password)
    with db.get_db() as conn:
        conn.execute(db.text("DELETE FROM sessions WHERE user_id = :i"), {"i": found["id"]})
    print(f"Password for '{username}' has been reset. They will need to sign in again.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
