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
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
INDEX_FILE = BASE_DIR / "index.html"
SERVERS_FILE = BASE_DIR / "subscription_servers.txt"
SERVERS_DIR = BASE_DIR / "servers"

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0") or "0")
BASE_URL = (os.environ.get("BASE_URL") or os.environ.get("RENDER_EXTERNAL_URL") or "http://127.0.0.1:8080").rstrip("/")
PORT = int(os.environ.get("PORT", "8080") or "8080")
PAYMENTS_ENABLED = os.environ.get("PAYMENTS_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
PAYMENT_PROVIDER_TOKEN = os.environ.get("PAYMENT_PROVIDER_TOKEN", "").strip()
PAYMENT_CURRENCY = os.environ.get("PAYMENT_CURRENCY", "RUB").upper()

TARIFFS = {
    "1d": {"name": "1 день", "price": 0, "days": 1, "emoji": "🕐"},
    "7d": {"name": "7 дней", "price": 0, "days": 7, "emoji": "🗓"},
    "1m": {"name": "1 месяц", "price": 80, "days": 30, "emoji": "🌙"},
    "3m": {"name": "3 месяца", "price": 220, "days": 90, "emoji": "🔥"},
    "6m": {"name": "6 месяцев", "price": 420, "days": 180, "emoji": "💎"},
    "12m": {"name": "12 месяцев", "price": 760, "days": 365, "emoji": "👑"},
}

BLOCKED_SERVER_NAME = "⛔ ПОДПИСКА ЗАБЛОКИРОВАНА"
BLOCKED_SUBSCRIPTION = (
    "#profile-title: FatherVPN | ПОДПИСКА ЗАБЛОКИРОВАНА\n"
    "#profile-update-interval: 1\n"
    "#subscription-userinfo: upload=0; download=0; total=0; expire=0\n"
    "#announce: ⛔ FatherVPN | ПОДПИСКА ЗАБЛОКИРОВАНА\n"
    "#hide-settings: 1\n"
    + "vless://633f424e-2b11-48da-a6b3-a849dd71456f@45.12.75.242:224"
      "?encryption=none&fp=chrome"
      "&pbk=l8AubqcxQO-HRFJy4pZL1vbLOo-eXit69s-XulSELE0"
      "&security=reality&sid=23103e1e&sni=ya.ru&type=raw#"
    + quote(BLOCKED_SERVER_NAME)
    + "\n"
)


def utc_now():
    return datetime.now(timezone.utc)


def now_iso():
    return utc_now().isoformat(timespec="seconds")


def parse_dt(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
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


class HybridRow:
    __slots__ = ("_values", "_map")

    def __init__(self, columns, values):
        self._values = tuple(values)
        self._map = {columns[i]: self._values[i] for i in range(len(columns))}

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return self._map[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def keys(self):
        return self._map.keys()

    def get(self, key, default=None):
        return self._map.get(key, default)


class PgResult:
    __slots__ = ("cursor", "columns")

    def __init__(self, cursor):
        self.cursor = cursor
        self.columns = [d.name if hasattr(d, "name") else d[0] for d in (cursor.description or [])]

    def _wrap(self, row):
        if row is None:
            return None
        return HybridRow(self.columns, row)

    def fetchone(self):
        return self._wrap(self.cursor.fetchone())

    def fetchall(self):
        return [self._wrap(row) for row in self.cursor.fetchall()]

    @property
    def rowcount(self):
        return self.cursor.rowcount


class PgConnection:
    def __init__(self, url):
        import psycopg
        self.conn = psycopg.connect(url, autocommit=False)

    @staticmethod
    def _sql(sql):
        return sql.replace("?", "%s")

    def execute(self, sql, args=()):
        cur = self.conn.cursor()
        cur.execute(self._sql(sql), tuple(args or ()))
        return PgResult(cur)

    def executemany(self, sql, seq):
        cur = self.conn.cursor()
        cur.executemany(self._sql(sql), seq)
        return PgResult(cur)

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.conn.close()


def using_postgres():
    return bool(DATABASE_URL)


def db():
    if DATABASE_URL:
        return PgConnection(DATABASE_URL)
    c = sqlite3.connect(DB_PATH, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA busy_timeout=15000")
    return c


def init_db():
    c = db()
    try:
        if DATABASE_URL:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS users(
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    tariff TEXT,
                    expires_at TEXT,
                    created_at TEXT NOT NULL,
                    blocked INTEGER NOT NULL DEFAULT 0,
                    cabinet_token TEXT UNIQUE,
                    legacy_token TEXT,
                    subscription_token TEXT UNIQUE
                )
                """
            )
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS payments(
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    telegram_charge_id TEXT NOT NULL UNIQUE,
                    provider_charge_id TEXT,
                    payload TEXT NOT NULL,
                    tariff_code TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log(
                    id BIGSERIAL PRIMARY KEY,
                    actor_id BIGINT,
                    action TEXT NOT NULL,
                    target_type TEXT,
                    target_id TEXT,
                    details TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            c.execute("CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_users_expires_at ON users(expires_at)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_users_blocked ON users(blocked)")
            c.commit()
        else:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS users(
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    tariff TEXT,
                    expires_at TEXT,
                    created_at TEXT NOT NULL,
                    blocked INTEGER NOT NULL DEFAULT 0,
                    cabinet_token TEXT,
                    legacy_token TEXT,
                    subscription_token TEXT
                );
                CREATE TABLE IF NOT EXISTS payments(
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
                CREATE TABLE IF NOT EXISTS audit_log(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor_id INTEGER,
                    action TEXT NOT NULL,
                    target_type TEXT,
                    target_id TEXT,
                    details TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id);
                """
            )
            cols = {r[1] for r in c.execute("PRAGMA table_info(users)")}
            for col, sql in {
                "blocked": "ALTER TABLE users ADD COLUMN blocked INTEGER NOT NULL DEFAULT 0",
                "cabinet_token": "ALTER TABLE users ADD COLUMN cabinet_token TEXT",
                "legacy_token": "ALTER TABLE users ADD COLUMN legacy_token TEXT",
                "tariff": "ALTER TABLE users ADD COLUMN tariff TEXT",
                "expires_at": "ALTER TABLE users ADD COLUMN expires_at TEXT",
                "subscription_token": "ALTER TABLE users ADD COLUMN subscription_token TEXT",
            }.items():
                if col not in cols:
                    c.execute(sql)
            c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_cabinet_token ON users(cabinet_token)")
            c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_subscription_token ON users(subscription_token)")
            c.commit()
    finally:
        c.close()


init_db()


def get_user(uid):
    c = db()
    try:
        return c.execute("SELECT * FROM users WHERE user_id=?", (int(uid),)).fetchone()
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


def get_user_by_subscription_token(token):
    c = db()
    try:
        return c.execute("SELECT * FROM users WHERE subscription_token=?", (token,)).fetchone()
    finally:
        c.close()


def upsert_user(uid, username="", first_name=""):
    c = db()
    try:
        c.execute(
            """
            INSERT INTO users(user_id,username,first_name,created_at)
            VALUES(?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name
            """,
            (int(uid), username or "", first_name or "", now_iso()),
        )
        c.commit()
    finally:
        c.close()


def _token(uid, column):
    user = get_user(uid)
    if not user:
        upsert_user(uid)
        user = get_user(uid)
    if user[column]:
        return user[column]
    for _ in range(12):
        token = secrets.token_urlsafe(32)
        c = db()
        try:
            c.execute(f"UPDATE users SET {column}=? WHERE user_id=?", (token, int(uid)))
            c.commit()
            return token
        except Exception as exc:
            c.rollback()
            if "unique" not in str(exc).lower() and "duplicate" not in str(exc).lower():
                raise
        finally:
            c.close()
    raise RuntimeError("Cannot create unique token")


def ensure_cabinet_token(uid):
    return _token(uid, "cabinet_token")


def ensure_subscription_token(uid):
    return _token(uid, "subscription_token")


def subscription_url(uid):
    return f"{BASE_URL}/s/{ensure_subscription_token(uid)}"


def set_user_blocked(uid, blocked):
    c = db()
    try:
        c.execute("UPDATE users SET blocked=? WHERE user_id=?", (1 if blocked else 0, int(uid)))
        c.commit()
    finally:
        c.close()


def subscription_active(user):
    if not user or user["blocked"] or not user["expires_at"]:
        return False
    expires = parse_dt(user["expires_at"])
    return bool(expires and expires > utc_now())


def grant_subscription(uid, code):
    tariff = TARIFFS[code]
    user = get_user(uid)
    if not user:
        upsert_user(uid)
        user = get_user(uid)
    current = parse_dt(user["expires_at"])
    start = current if current and current > utc_now() else utc_now()
    expires = start + timedelta(days=tariff["days"])
    c = db()
    try:
        c.execute(
            "UPDATE users SET tariff=?,expires_at=? WHERE user_id=?",
            (tariff["name"], expires.isoformat(), int(uid)),
        )
        c.commit()
    finally:
        c.close()
    ensure_subscription_token(uid)
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
            if text:
                return text + "\n"
        except OSError:
            pass
    parts = []
    if SERVERS_DIR.exists():
        for path in sorted(SERVERS_DIR.glob("*.txt")):
            try:
                text = path.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if text:
                parts.append(text)
    return "\n".join(parts) + ("\n" if parts else "")


def payment_payload(uid, code):
    return f"fvpn:{int(uid)}:{code}:{secrets.token_hex(8)}"


def parse_payload(payload):
    try:
        parts = payload.split(":")
        if len(parts) == 4 and parts[0] == "fvpn" and parts[2] in TARIFFS:
            return int(parts[1]), parts[2], parts[3]
    except Exception:
        pass
    return None


def paymaster_provider_data(uid, code, nonce):
    tariff = TARIFFS[code]
    return json.dumps(
        {"invoice": {"description": f"FatherVPN: {tariff['name']}", "orderNo": f"FV-{uid}-{nonce}"[:64]}},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def fulfill_payment(uid, code, sp):
    tariff = TARIFFS[code]
    c = db()
    try:
        if not DATABASE_URL:
            c.execute("BEGIN IMMEDIATE")
        else:
            c.execute("BEGIN")

        if c.execute("SELECT 1 FROM payments WHERE telegram_charge_id=?", (sp.telegram_payment_charge_id,)).fetchone():
            c.rollback()
            return None, False

        user = c.execute("SELECT * FROM users WHERE user_id=?", (int(uid),)).fetchone()
        if not user:
            c.execute(
                "INSERT INTO users(user_id,username,first_name,created_at) VALUES(?,?,?,?)",
                (int(uid), "", "", now_iso()),
            )
            user = c.execute("SELECT * FROM users WHERE user_id=?", (int(uid),)).fetchone()

        current = parse_dt(user["expires_at"])
        start = current if current and current > utc_now() else utc_now()
        expires = start + timedelta(days=tariff["days"])
        token = user["subscription_token"] or secrets.token_urlsafe(32)
        c.execute(
            "UPDATE users SET tariff=?,expires_at=?,subscription_token=? WHERE user_id=?",
            (tariff["name"], expires.isoformat(), token, int(uid)),
        )
        c.execute(
            """
            INSERT INTO payments(
                user_id,telegram_charge_id,provider_charge_id,payload,tariff_code,currency,amount,created_at
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                int(uid),
                sp.telegram_payment_charge_id,
                sp.provider_payment_charge_id or "",
                sp.invoice_payload,
                code,
                sp.currency,
                int(sp.total_amount),
                now_iso(),
            ),
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
    if not active_servers():
        raise RuntimeError("No subscription servers found")


def storage_backend():
    return "postgres" if DATABASE_URL else "sqlite-ephemeral"
