import html
import json
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("FATHERVPN_DATA_DIR", str(BASE_DIR)))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "father_vpn.db"
INDEX_FILE = BASE_DIR / "index.html"
SERVERS_FILE = BASE_DIR / "subscription_servers.txt"
SERVERS_DIR = BASE_DIR / "servers"

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0") or "0")
BASE_URL = (os.environ.get("BASE_URL") or os.environ.get("RENDER_EXTERNAL_URL") or "http://127.0.0.1:8080").rstrip("/")
MAX_DEVICES = int(os.environ.get("MAX_DEVICES", "6") or "6")
PORT = int(os.environ.get("PORT", "8080") or "8080")
PAYMENTS_ENABLED = os.environ.get("PAYMENTS_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
PAYMENT_PROVIDER_TOKEN = os.environ.get("PAYMENT_PROVIDER_TOKEN", "").strip()
PAYMENT_CURRENCY = os.environ.get("PAYMENT_CURRENCY", "RUB").upper()
PAYMENT_TEST_MODE = os.environ.get("PAYMENT_TEST_MODE", "true").lower() in {"1", "true", "yes", "on"}

TARIFFS = {
    "1d": {"name": "1 день", "price": 0, "days": 1, "emoji": "🕐"},
    "7d": {"name": "7 дней", "price": 0, "days": 7, "emoji": "🗓"},
    "1m": {"name": "1 месяц", "price": 80, "days": 30, "emoji": "🌙"},
    "3m": {"name": "3 месяца", "price": 220, "days": 90, "emoji": "🔥"},
    "6m": {"name": "6 месяцев", "price": 420, "days": 180, "emoji": "💎"},
    "12m": {"name": "12 месяцев", "price": 760, "days": 365, "emoji": "👑"},
}

BLOCKED_SERVER_NAME = "⛔ ПОДПИСКА ЗАБЛОКИРОВАНА"
BLOCKED_VLESS = (
    "vless://633f424e-2b11-48da-a6b3-a849dd71456f@45.12.75.242:224"
    "?encryption=none&fp=chrome"
    "&pbk=l8AubqcxQO-HRFJy4pZL1vbLOo-eXit69s-XulSELE0"
    "&security=reality&sid=23103e1e&sni=ya.ru&type=raw"
    f"#{quote(BLOCKED_SERVER_NAME)}"
)
BLOCKED_SUBSCRIPTION = (
    "#profile-title: FatherVPN | ПОДПИСКА ЗАБЛОКИРОВАНА\n"
    "#profile-update-interval: 1\n"
    "#subscription-userinfo: upload=0; download=0; total=0; expire=0\n"
    "#announce: ⛔ FatherVPN | ПОДПИСКА ЗАБЛОКИРОВАНА\n"
    "#hide-settings: 1\n" + BLOCKED_VLESS + "\n"
)


def utc_now():
    return datetime.now(timezone.utc)


def now_iso():
    return utc_now().isoformat(timespec="seconds")


def parse_dt(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(value):
    dt = parse_dt(value)
    return dt.astimezone().strftime("%d.%m.%Y %H:%M") if dt else "—"


def esc(value):
    return html.escape(str(value), quote=True)


def db():
    c = sqlite3.connect(DB_PATH, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA busy_timeout=15000")
    return c


def init_db():
    c = db()
    try:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                tariff TEXT,
                expires_at TEXT,
                created_at TEXT NOT NULL,
                blocked INTEGER NOT NULL DEFAULT 0,
                cabinet_token TEXT,
                legacy_token TEXT
            );
            CREATE TABLE IF NOT EXISTS devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                token TEXT NOT NULL UNIQUE,
                blocked INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                last_seen TEXT,
                last_ip TEXT,
                user_agent TEXT,
                request_count INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                telegram_charge_id TEXT NOT NULL UNIQUE,
                provider_charge_id TEXT,
                payload TEXT NOT NULL,
                tariff_code TEXT NOT NULL,
                currency TEXT NOT NULL,
                amount INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_id INTEGER,
                action TEXT NOT NULL,
                target_type TEXT,
                target_id TEXT,
                details TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_devices_user ON devices(user_id);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_devices_token ON devices(token);
            CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id);
            """
        )
        cols = {r[1] for r in c.execute("PRAGMA table_info(users)")}
        migrations = {
            "blocked": "ALTER TABLE users ADD COLUMN blocked INTEGER NOT NULL DEFAULT 0",
            "cabinet_token": "ALTER TABLE users ADD COLUMN cabinet_token TEXT",
            "legacy_token": "ALTER TABLE users ADD COLUMN legacy_token TEXT",
            "tariff": "ALTER TABLE users ADD COLUMN tariff TEXT",
            "expires_at": "ALTER TABLE users ADD COLUMN expires_at TEXT",
        }
        for col, sql in migrations.items():
            if col not in cols:
                c.execute(sql)
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_cabinet_token ON users(cabinet_token)")
        c.commit()
    finally:
        c.close()


init_db()


def get_user(user_id):
    c = db()
    try:
        return c.execute("SELECT * FROM users WHERE user_id=?", (int(user_id),)).fetchone()
    finally:
        c.close()


def get_user_by_username(username):
    c = db()
    try:
        return c.execute("SELECT * FROM users WHERE lower(username)=lower(?)", (username.lstrip("@"),)).fetchone()
    finally:
        c.close()


def get_user_by_cabinet_token(token):
    c = db()
    try:
        return c.execute("SELECT * FROM users WHERE cabinet_token=?", (token,)).fetchone()
    finally:
        c.close()


def upsert_user(user_id, username="", first_name=""):
    c = db()
    try:
        c.execute(
            """INSERT INTO users(user_id,username,first_name,created_at)
               VALUES(?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name""",
            (int(user_id), username or "", first_name or "", now_iso()),
        )
        c.commit()
    finally:
        c.close()


def ensure_cabinet_token(user_id):
    user = get_user(user_id)
    if not user:
        upsert_user(user_id)
        user = get_user(user_id)
    if user["cabinet_token"]:
        return user["cabinet_token"]
    for _ in range(10):
        token = secrets.token_urlsafe(32)
        c = db()
        try:
            c.execute("UPDATE users SET cabinet_token=? WHERE user_id=?", (token, int(user_id)))
            c.commit()
            return token
        except sqlite3.IntegrityError:
            pass
        finally:
            c.close()
    raise RuntimeError("Cannot create cabinet token")


def list_devices(user_id):
    c = db()
    try:
        return c.execute("SELECT * FROM devices WHERE user_id=? ORDER BY id", (int(user_id),)).fetchall()
    finally:
        c.close()


def get_device(device_id):
    c = db()
    try:
        return c.execute("SELECT * FROM devices WHERE id=?", (int(device_id),)).fetchone()
    finally:
        c.close()


def create_device(user_id, name=None):
    devices = list_devices(user_id)
    if len(devices) >= MAX_DEVICES:
        return None
    if not name:
        used = {d["name"] for d in devices}
        n = 1
        while f"Устройство {n}" in used:
            n += 1
        name = f"Устройство {n}"
    c = db()
    try:
        cur = c.execute(
            "INSERT INTO devices(user_id,name,token,created_at) VALUES(?,?,?,?)",
            (int(user_id), name[:40], secrets.token_urlsafe(24), now_iso()),
        )
        c.commit()
        return c.execute("SELECT * FROM devices WHERE id=?", (cur.lastrowid,)).fetchone()
    finally:
        c.close()


def set_device_blocked(device_id, blocked):
    c = db()
    try:
        c.execute("UPDATE devices SET blocked=? WHERE id=?", (1 if blocked else 0, int(device_id)))
        c.commit()
    finally:
        c.close()


def delete_device(device_id):
    c = db()
    try:
        c.execute("DELETE FROM devices WHERE id=?", (int(device_id),))
        c.commit()
    finally:
        c.close()


def set_user_blocked(user_id, blocked):
    c = db()
    try:
        c.execute("UPDATE users SET blocked=? WHERE user_id=?", (1 if blocked else 0, int(user_id)))
        c.commit()
    finally:
        c.close()


def subscription_active(user):
    if not user or user["blocked"] or not user["expires_at"]:
        return False
    exp = parse_dt(user["expires_at"])
    return bool(exp and exp > utc_now())


def grant_subscription(user_id, tariff_code):
    tariff = TARIFFS[tariff_code]
    user = get_user(user_id)
    if not user:
        upsert_user(user_id)
        user = get_user(user_id)
    current = parse_dt(user["expires_at"])
    start = current if current and current > utc_now() else utc_now()
    expires = start + timedelta(days=tariff["days"])
    c = db()
    try:
        c.execute("UPDATE users SET tariff=?,expires_at=? WHERE user_id=?", (tariff["name"], expires.isoformat(), int(user_id)))
        c.commit()
    finally:
        c.close()
    if not list_devices(user_id):
        create_device(user_id)
    return expires


def resolve_target(value):
    if not value:
        return None
    if value.startswith("@"):
        return get_user_by_username(value)
    try:
        return get_user(int(value))
    except ValueError:
        return None


def log_action(actor_id, action, target_type="", target_id="", details=""):
    c = db()
    try:
        c.execute(
            "INSERT INTO audit_log(actor_id,action,target_type,target_id,details,created_at) VALUES(?,?,?,?,?,?)",
            (actor_id, action, target_type, str(target_id), str(details), now_iso()),
        )
        c.commit()
    finally:
        c.close()


def active_servers():
    if SERVERS_FILE.exists():
        try:
            text = SERVERS_FILE.read_text(encoding="utf-8").strip()
            return text + "\n" if text else ""
        except OSError:
            pass
    if SERVERS_DIR.exists():
        parts = []
        for p in sorted(SERVERS_DIR.glob("*.txt")):
            try:
                t = p.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if t:
                parts.append(t)
        return "\n".join(parts) + ("\n" if parts else "")
    return ""


def payment_payload(user_id, tariff_code):
    return f"fvpn:{int(user_id)}:{tariff_code}:{secrets.token_hex(8)}"


def parse_payload(payload):
    try:
        p = payload.split(":")
        if len(p) != 4 or p[0] != "fvpn" or p[2] not in TARIFFS:
            return None
        return int(p[1]), p[2], p[3]
    except Exception:
        return None


def paymaster_provider_data(user_id, code, nonce):
    t = TARIFFS[code]
    return json.dumps(
        {"invoice": {"description": f"FatherVPN: {t['name']}", "orderNo": f"FV-{user_id}-{nonce}"[:64]}},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def fulfill_payment(user_id, code, sp):
    tariff = TARIFFS[code]
    c = db()
    try:
        c.execute("BEGIN IMMEDIATE")
        if c.execute("SELECT 1 FROM payments WHERE telegram_charge_id=?", (sp.telegram_payment_charge_id,)).fetchone():
            c.rollback()
            return None, False
        user = c.execute("SELECT * FROM users WHERE user_id=?", (int(user_id),)).fetchone()
        if not user:
            c.execute("INSERT INTO users(user_id,username,first_name,created_at) VALUES(?,?,?,?)", (int(user_id), "", "", now_iso()))
            user = c.execute("SELECT * FROM users WHERE user_id=?", (int(user_id),)).fetchone()
        current = parse_dt(user["expires_at"])
        start = current if current and current > utc_now() else utc_now()
        expires = start + timedelta(days=tariff["days"])
        c.execute("UPDATE users SET tariff=?,expires_at=? WHERE user_id=?", (tariff["name"], expires.isoformat(), int(user_id)))
        if c.execute("SELECT COUNT(*) FROM devices WHERE user_id=?", (int(user_id),)).fetchone()[0] == 0:
            c.execute("INSERT INTO devices(user_id,name,token,created_at) VALUES(?,?,?,?)", (int(user_id), "Устройство 1", secrets.token_urlsafe(24), now_iso()))
        c.execute(
            "INSERT INTO payments(user_id,telegram_charge_id,provider_charge_id,payload,tariff_code,currency,amount,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (int(user_id), sp.telegram_payment_charge_id, sp.provider_payment_charge_id or "", sp.invoice_payload, code, sp.currency, int(sp.total_amount), now_iso()),
        )
        c.commit()
        return expires, True
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def validate_config():
    missing = []
    if not BOT_TOKEN:
        missing.append("BOT_TOKEN")
    if not ADMIN_ID:
        missing.append("ADMIN_ID")
    if PAYMENTS_ENABLED and not PAYMENT_PROVIDER_TOKEN:
        missing.append("PAYMENT_PROVIDER_TOKEN")
    if missing:
        raise RuntimeError("Missing environment variables: " + ", ".join(missing))
    if not 1 <= MAX_DEVICES <= 20:
        raise RuntimeError("MAX_DEVICES must be 1..20")
    if not active_servers():
        raise RuntimeError("No subscription servers found")
