import os
import sqlite3

# On Render, point this at a Persistent Disk mount, e.g.:
#   DATABASE_PATH=/var/data/fathervpn.sqlite3
# Otherwise the DB is wiped on every deploy.
DB_PATH = os.getenv("DATABASE_PATH", "./data/fathervpn.sqlite3")


def connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def init_db() -> None:
    with connect() as db:
        db.execute(
            """CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        db.execute(
            """CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                starts_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                payment_charge_id TEXT UNIQUE,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        db.commit()


def save_user(user) -> None:
    with connect() as db:
        db.execute(
            """INSERT INTO users(telegram_id, username, first_name) VALUES(?,?,?)
               ON CONFLICT(telegram_id) DO UPDATE SET
                   username=excluded.username,
                   first_name=excluded.first_name""",
            (user.id, user.username, user.first_name),
        )
        db.commit()


def activate_subscription(user_id: int, charge_id: str, days: int) -> None:
    with connect() as db:
        if db.execute(
            "SELECT id FROM subscriptions WHERE payment_charge_id=?",
            (charge_id,),
        ).fetchone():
            return
        db.execute(
            """INSERT INTO subscriptions
               (telegram_id, status, starts_at, expires_at, payment_charge_id)
               VALUES(?, 'active', CURRENT_TIMESTAMP, datetime('now', ?), ?)""",
            (user_id, f"+{int(days)} days", charge_id),
        )
        db.commit()


def current_subscription(user_id: int):
    with connect() as db:
        return db.execute(
            """SELECT * FROM subscriptions
               WHERE telegram_id=?
                 AND status='active'
                 AND expires_at > CURRENT_TIMESTAMP
               ORDER BY expires_at DESC
               LIMIT 1""",
            (user_id,),
        ).fetchone()


def profile(user_id: int):
    with connect() as db:
        user = db.execute(
            "SELECT * FROM users WHERE telegram_id=?", (user_id,)
        ).fetchone()
        return user, current_subscription(user_id)
