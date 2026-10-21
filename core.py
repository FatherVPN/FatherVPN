import hashlib
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
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS subscription_clients(
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    client_name TEXT NOT NULL,
                    is_browser INTEGER NOT NULL DEFAULT 0,
                    ip_address TEXT,
                    user_agent TEXT,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    request_count BIGINT NOT NULL DEFAULT 1,
                    UNIQUE(user_id, fingerprint)
                )
                """
            )
            c.execute("CREATE INDEX IF NOT EXISTS idx_subscription_clients_user_time ON subscription_clients(user_id,last_seen)")
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
                CREATE TABLE IF NOT EXISTS subscription_clients(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    fingerprint TEXT NOT NULL,
                    client_name TEXT NOT NULL,
                    is_browser INTEGER NOT NULL DEFAULT 0,
                    ip_address TEXT,
                    user_agent TEXT,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    request_count INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(user_id, fingerprint)
                );
                CREATE INDEX IF NOT EXISTS idx_subscription_clients_user_time ON subscription_clients(user_id,last_seen);
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


def init_account_tables():
    c = db()
    try:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS account_users(
                email TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                telegram_id BIGINT UNIQUE,
                telegram_username TEXT,
                telegram_first_name TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS account_sessions(
                session_hash TEXT PRIMARY KEY,
                email TEXT NOT NULL REFERENCES account_users(email) ON DELETE CASCADE,
                csrf_token TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS account_link_tokens(
                token_hash TEXT PRIMARY KEY,
                email TEXT NOT NULL REFERENCES account_users(email) ON DELETE CASCADE,
                expires_at TEXT NOT NULL,
                used_at TEXT
            )
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_account_sessions_expiry ON account_sessions(expires_at)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_account_link_expiry ON account_link_tokens(expires_at)")

        if DATABASE_URL:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS announcements(
                    id BIGSERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    created_by BIGINT NOT NULL,
                    created_at TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1
                )
                """
            )
        else:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS announcements(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    created_by INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1
                )
                """
            )
        c.execute("CREATE INDEX IF NOT EXISTS idx_announcements_active ON announcements(active,created_at)")
        c.commit()
    finally:
        c.close()


init_db()
init_account_tables()


def create_announcement(title: str, body: str, created_by: int):
    title = " ".join(str(title or "").split()).strip()[:120]
    body = str(body or "").strip()[:3000]
    if not title or not body:
        raise ValueError("Для объявления нужны заголовок и текст.")
    c = db()
    try:
        result = c.execute(
            "INSERT INTO announcements(title,body,created_by,created_at,active) VALUES(?,?,?,?,1) RETURNING id",
            (title, body, int(created_by), now_iso()),
        )
        row = result.fetchone()
        c.commit()
        return int(row["id"] if hasattr(row, "keys") else row[0])
    finally:
        c.close()


def list_announcements(limit=5, active_only=True):
    safe_limit = max(1, min(int(limit), 20))
    c = db()
    try:
        if active_only:
            result = c.execute(
                "SELECT id,title,body,created_by,created_at,active FROM announcements WHERE active=1 ORDER BY id DESC LIMIT ?",
                (safe_limit,),
            )
        else:
            result = c.execute(
                "SELECT id,title,body,created_by,created_at,active FROM announcements ORDER BY id DESC LIMIT ?",
                (safe_limit,),
            )
        return result.fetchall()
    finally:
        c.close()


def deactivate_announcement(announcement_id: int):
    c = db()
    try:
        result = c.execute(
            "UPDATE announcements SET active=0 WHERE id=? AND active=1",
            (int(announcement_id),),
        )
        c.commit()
        return result.rowcount > 0
    finally:
        c.close()


def list_telegram_user_ids():
    c = db()
    try:
        rows = c.execute("SELECT user_id FROM users ORDER BY user_id").fetchall()
        return [int(row["user_id"] if hasattr(row, "keys") else row[0]) for row in rows]
    finally:
        c.close()


def consume_account_link(token: str, telegram_id: int, username: str = "", first_name: str = ""):
    if not token or len(token) > 100 or telegram_id <= 0:
        return False, "", "Ссылка привязки некорректна."
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = now_iso()
    c = db()
    try:
        link = c.execute(
            "SELECT email FROM account_link_tokens WHERE token_hash=? AND used_at IS NULL AND expires_at>?",
            (token_hash, now),
        ).fetchone()
        if not link:
            return False, "", "Ссылка устарела или уже использована. Создайте новую в кабинете."
        email = str(link["email"])
        current = c.execute(
            "SELECT telegram_id FROM account_users WHERE email=?",
            (email,),
        ).fetchone()
        if not current:
            return False, "", "Аккаунт не найден. Войдите на сайт и попробуйте ещё раз."
        if current["telegram_id"] is not None and int(current["telegram_id"]) != telegram_id:
            return False, "", "К этому аккаунту уже привязан другой Telegram."
        other = c.execute(
            "SELECT email FROM account_users WHERE telegram_id=? AND email<>?",
            (telegram_id, email),
        ).fetchone()
        if other:
            return False, "", "Этот Telegram уже привязан к другому аккаунту FatherVPN."
        changed = c.execute(
            "UPDATE account_users SET telegram_id=?, telegram_username=?, telegram_first_name=?, updated_at=? WHERE email=?",
            (telegram_id, (username or "").strip()[:64], (first_name or "").strip()[:128], now, email),
        )
        if changed.rowcount != 1:
            return False, "", "Не удалось обновить аккаунт. Попробуйте ещё раз."
        marked = c.execute(
            "UPDATE account_link_tokens SET used_at=? WHERE token_hash=? AND used_at IS NULL",
            (now, token_hash),
        )
        if marked.rowcount != 1:
            c.rollback()
            return False, "", "Ссылка уже использована. Создайте новую в кабинете."
        c.commit()
        return True, email, ""
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()
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


def classify_subscription_client(user_agent="", accept="", browser_hint=False):
    ua = (user_agent or "")[:500]
    low = ua.lower()
    apps = (
        ("hiddify", "Hiddify"),
        ("v2rayng", "v2rayNG"),
        ("nekobox", "NekoBox"),
        ("nekoray", "NekoRay"),
        ("shadowrocket", "Shadowrocket"),
        ("v2raytun", "V2RayTun"),
        ("sing-box", "sing-box"),
        ("singbox", "sing-box"),
        ("clash", "Clash"),
        ("mihomo", "Mihomo"),
        ("stash", "Stash"),
        ("surge", "Surge"),
        ("quantumult", "Quantumult"),
        ("loon", "Loon"),
        ("surfboard", "Surfboard"),
        ("outline", "Outline"),
    )
    for marker, name in apps:
        if marker in low:
            return name
    if browser_hint or "text/html" in (accept or "").lower() or any(
        marker in low for marker in ("mozilla/", "chrome/", "safari/", "firefox/", "edg/")
    ):
        return "Браузер"
    if any(marker in low for marker in ("curl/", "wget/", "python-requests", "urllib")):
        return "HTTP-клиент / скрипт"
    return "Неизвестный клиент" if ua else "User-Agent не передан"


def record_subscription_client(user_id, user_agent="", ip_address="", accept="", browser_hint=False):
    ua = (user_agent or "")[:500]
    ip = (ip_address or "")[:64]
    client_name = classify_subscription_client(ua, accept, browser_hint)
    is_browser = int(client_name == "Браузер")
    fingerprint = hashlib.sha256(
        f"{int(user_id)}\0{client_name}\0{ip}\0{ua}".encode("utf-8", "replace")
    ).hexdigest()
    now = now_iso()
    c = db()
    try:
        c.execute(
            """
            INSERT INTO subscription_clients(
                user_id,fingerprint,client_name,is_browser,ip_address,user_agent,
                first_seen,last_seen,request_count
            ) VALUES(?,?,?,?,?,?,?,?,1)
            ON CONFLICT(user_id,fingerprint) DO UPDATE SET
                client_name=excluded.client_name,
                is_browser=excluded.is_browser,
                ip_address=excluded.ip_address,
                user_agent=excluded.user_agent,
                last_seen=excluded.last_seen,
                request_count=subscription_clients.request_count+1
            """,
            (int(user_id), fingerprint, client_name, is_browser, ip, ua, now, now),
        )
        c.commit()
    finally:
        c.close()


def list_subscription_clients(user_id, limit=20):
    safe_limit = max(1, min(int(limit), 50))
    c = db()
    try:
        return c.execute(
            "SELECT * FROM subscription_clients WHERE user_id=? ORDER BY last_seen DESC LIMIT ?",
            (int(user_id), safe_limit),
        ).fetchall()
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
