"""Create every table and seed the default admin user.

Run it once against your production database, for example:

    DATABASE_URL="postgres://..." python migrate.py

It is safe to run repeatedly - existing data is never touched.
"""
import db


def main():
    url = db._database_url()
    print(f"Database: {url}")
    if url.startswith("sqlite:"):
        print("WARNING: no DATABASE_URL is set, so this used a local SQLite file.")
        print("         Set DATABASE_URL to your Neon connection string for production.")

    db.init_db()
    print("Schema is up to date.")

    with db.get_db() as conn:
        count = conn.execute(db.text("SELECT COUNT(*) FROM users")).scalar()
        members = conn.execute(db.text("SELECT COUNT(*) FROM members")).scalar()

    print(f"Users: {count}   Members: {members}")
    if count == 1:
        print(f"Admin login: {db.DEFAULT_ADMIN_USER} / {db.DEFAULT_ADMIN_PASS}")
        print("You will be asked to change that password on first sign-in.")


if __name__ == "__main__":
    main()
