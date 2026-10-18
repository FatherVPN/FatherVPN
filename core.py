import html
import json
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
BASE_DIR=Path(__file__).resolve().parent;DATA_DIR=Path(os.environ.get("FATHERVPN_DATA_DIR",str(BASE_DIR)));DATA_DIR.mkdir(parents=True,exist_ok=True);DB_PATH=DATA_DIR/"father_vpn.db";INDEX_FILE=BASE_DIR/"index.html";SERVERS_FILE=BASE_DIR/"subscription_servers.txt";SERVERS_DIR=BASE_DIR/"servers"
BOT_TOKEN=os.environ.get("BOT_TOKEN","").strip();ADMIN_ID=int(os.environ.get("ADMIN_ID","0") or "0");BASE_URL=(os.environ.get("BASE_URL") or os.environ.get("RENDER_EXTERNAL_URL") or "http://127.0.0.1:8080").rstrip("/");PORT=int(os.environ.get("PORT","8080") or "8080");PAYMENTS_ENABLED=os.environ.get("PAYMENTS_ENABLED","true").lower() in {"1","true","yes","on"};PAYMENT_PROVIDER_TOKEN=os.environ.get("PAYMENT_PROVIDER_TOKEN","").strip();PAYMENT_CURRENCY=os.environ.get("PAYMENT_CURRENCY","RUB").upper()
TARIFFS={"1d":{"name":"1 день","price":0,"days":1,"emoji":"🕐"},"7d":{"name":"7 дней","price":0,"days":7,"emoji":"🗓"},"1m":{"name":"1 месяц","price":80,"days":30,"emoji":"🌙"},"3m":{"name":"3 месяца","price":220,"days":90,"emoji":"🔥"},"6m":{"name":"6 месяцев","price":420,"days":180,"emoji":"💎"},"12m":{"name":"12 месяцев","price":760,"days":365,"emoji":"👑"}}
BLOCKED_SUBSCRIPTION="#profile-title: FatherVPN | ПОДПИСКА ЗАБЛОКИРОВАНА\n#profile-update-interval: 1\n#subscription-userinfo: upload=0; download=0; total=0; expire=0\n#announce: ⛔ FatherVPN | ПОДПИСКА ЗАБЛОКИРОВАНА\n#hide-settings: 1\n"+f"vless://633f424e-2b11-48da-a6b3-a849dd71456f@45.12.75.242:224?encryption=none&fp=chrome&pbk=l8AubqcxQO-HRFJy4pZL1vbLOo-eXit69s-XulSELE0&security=reality&sid=23103e1e&sni=ya.ru&type=raw#{quote('⛔ ПОДПИСКА ЗАБЛОКИРОВАНА')}\n"
def utc_now():return datetime.now(timezone.utc)
def now_iso():return utc_now().isoformat(timespec="seconds")
def parse_dt(v):
    if not v:return None
    try:d=datetime.fromisoformat(v)
    except (TypeError,ValueError):return None
    if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)
def fmt_dt(v):
    d=parse_dt(v);return d.astimezone().strftime("%d.%m.%Y %H:%M") if d else "—"
def esc(v):return html.escape(str(v),quote=True)
def db():
    c=sqlite3.connect(DB_PATH,timeout=15);c.row_factory=sqlite3.Row;c.execute("PRAGMA foreign_keys=ON");c.execute("PRAGMA busy_timeout=15000");return c
def init_db():
    c=db()
    try:
        c.execute("PRAGMA journal_mode=WAL");c.executescript("""CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY,username TEXT,first_name TEXT,tariff TEXT,expires_at TEXT,created_at TEXT NOT NULL,blocked INTEGER NOT NULL DEFAULT 0,cabinet_token TEXT,legacy_token TEXT,subscription_token TEXT);CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,telegram_charge_id TEXT NOT NULL UNIQUE,provider_charge_id TEXT,payload TEXT NOT NULL,tariff_code TEXT NOT NULL,currency TEXT NOT NULL,amount INTEGER NOT NULL,created_at TEXT NOT NULL);CREATE TABLE IF NOT EXISTS audit_log(id INTEGER PRIMARY KEY AUTOINCREMENT,actor_id INTEGER,action TEXT NOT NULL,target_type TEXT,target_id TEXT,details TEXT,created_at TEXT NOT NULL);""")
        cols={r[1] for r in c.execute("PRAGMA table_info(users)")}
        for col,sql in {"blocked":"ALTER TABLE users ADD COLUMN blocked INTEGER NOT NULL DEFAULT 0","cabinet_token":"ALTER TABLE users ADD COLUMN cabinet_token TEXT","legacy_token":"ALTER TABLE users ADD COLUMN legacy_token TEXT","tariff":"ALTER TABLE users ADD COLUMN tariff TEXT","expires_at":"ALTER TABLE users ADD COLUMN expires_at TEXT","subscription_token":"ALTER TABLE users ADD COLUMN subscription_token TEXT"}.items():
            if col not in cols:c.execute(sql)
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_cabinet_token ON users(cabinet_token)");c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_subscription_token ON users(subscription_token)");c.commit()
    finally:c.close()
init_db()
def get_user(uid):
    c=db()
    try:return c.execute("SELECT * FROM users WHERE user_id=?",(int(uid),)).fetchone()
    finally:c.close()
def get_user_by_username(u):
    c=db()
    try:return c.execute("SELECT * FROM users WHERE lower(username)=lower(?)",(u.lstrip("@"),)).fetchone()
    finally:c.close()
def get_user_by_cabinet_token(t):
    c=db()
    try:return c.execute("SELECT * FROM users WHERE cabinet_token=?",(t,)).fetchone()
    finally:c.close()
def get_user_by_subscription_token(t):
    c=db()
    try:return c.execute("SELECT * FROM users WHERE subscription_token=?",(t,)).fetchone()
    finally:c.close()
def upsert_user(uid,username="",first_name=""):
    c=db()
    try:c.execute("INSERT INTO users(user_id,username,first_name,created_at) VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,first_name=excluded.first_name",(int(uid),username or "",first_name or "",now_iso()));c.commit()
    finally:c.close()
def _token(uid,col):
    u=get_user(uid)
    if not u:upsert_user(uid);u=get_user(uid)
    if u[col]:return u[col]
    for _ in range(10):
        t=secrets.token_urlsafe(32);c=db()
        try:c.execute(f"UPDATE users SET {col}=? WHERE user_id=?",(t,int(uid)));c.commit();return t
        except sqlite3.IntegrityError:pass
        finally:c.close()
    raise RuntimeError("Cannot create token")
def ensure_cabinet_token(uid):return _token(uid,"cabinet_token")
def ensure_subscription_token(uid):return _token(uid,"subscription_token")
def subscription_url(uid):return f"{BASE_URL}/s/{ensure_subscription_token(uid)}"
def set_user_blocked(uid,b):
    c=db()
    try:c.execute("UPDATE users SET blocked=? WHERE user_id=?",(1 if b else 0,int(uid)));c.commit()
    finally:c.close()
def subscription_active(u):
    if not u or u["blocked"] or not u["expires_at"]:return False
    e=parse_dt(u["expires_at"]);return bool(e and e>utc_now())
def grant_subscription(uid,code):
    t=TARIFFS[code];u=get_user(uid)
    if not u:upsert_user(uid);u=get_user(uid)
    cur=parse_dt(u["expires_at"]);start=cur if cur and cur>utc_now() else utc_now();exp=start+timedelta(days=t["days"]);c=db()
    try:c.execute("UPDATE users SET tariff=?,expires_at=? WHERE user_id=?",(t["name"],exp.isoformat(),int(uid)));c.commit()
    finally:c.close()
    ensure_subscription_token(uid);return exp
def resolve_target(v):
    if not v:return None
    if v.startswith("@"):return get_user_by_username(v)
    try:return get_user(int(v))
    except ValueError:return None
def log_action(a,action,target_type="",target_id="",details=""):
    c=db()
    try:c.execute("INSERT INTO audit_log(actor_id,action,target_type,target_id,details,created_at) VALUES(?,?,?,?,?,?)",(a,action,target_type,str(target_id),str(details),now_iso()));c.commit()
    finally:c.close()
def active_servers():
    if SERVERS_FILE.exists():
        try:
            t=SERVERS_FILE.read_text(encoding="utf-8").strip()
            if t:return t+"\n"
        except OSError:pass
    parts=[]
    if SERVERS_DIR.exists():
        for p in sorted(SERVERS_DIR.glob("*.txt")):
            try:t=p.read_text(encoding="utf-8").strip()
            except OSError:continue
            if t:parts.append(t)
    return "\n".join(parts)+("\n" if parts else "")
def payment_payload(uid,code):return f"fvpn:{int(uid)}:{code}:{secrets.token_hex(8)}"
def parse_payload(p):
    try:
        x=p.split(":");return (int(x[1]),x[2],x[3]) if len(x)==4 and x[0]=="fvpn" and x[2] in TARIFFS else None
    except Exception:return None
def paymaster_provider_data(uid,code,nonce):
    t=TARIFFS[code];return json.dumps({"invoice":{"description":f"FatherVPN: {t['name']}","orderNo":f"FV-{uid}-{nonce}"[:64]}},ensure_ascii=False,separators=(",",":"))
def fulfill_payment(uid,code,sp):
    t=TARIFFS[code];c=db()
    try:
        c.execute("BEGIN IMMEDIATE")
        if c.execute("SELECT 1 FROM payments WHERE telegram_charge_id=?",(sp.telegram_payment_charge_id,)).fetchone():c.rollback();return None,False
        u=c.execute("SELECT * FROM users WHERE user_id=?",(int(uid),)).fetchone()
        if not u:c.execute("INSERT INTO users(user_id,username,first_name,created_at) VALUES(?,?,?,?)",(int(uid),"","",now_iso()));u=c.execute("SELECT * FROM users WHERE user_id=?",(int(uid),)).fetchone()
        cur=parse_dt(u["expires_at"]);start=cur if cur and cur>utc_now() else utc_now();exp=start+timedelta(days=t["days"]);token=u["subscription_token"] or secrets.token_urlsafe(32);c.execute("UPDATE users SET tariff=?,expires_at=?,subscription_token=? WHERE user_id=?",(t["name"],exp.isoformat(),token,int(uid)));c.execute("INSERT INTO payments(user_id,telegram_charge_id,provider_charge_id,payload,tariff_code,currency,amount,created_at) VALUES(?,?,?,?,?,?,?,?)",(int(uid),sp.telegram_payment_charge_id,sp.provider_payment_charge_id or "",sp.invoice_payload,code,sp.currency,int(sp.total_amount),now_iso()));c.commit();return exp,True
    except Exception:c.rollback();raise
    finally:c.close()
def validate_config():
    m=[]
    if not BOT_TOKEN:m.append("BOT_TOKEN")
    if not ADMIN_ID:m.append("ADMIN_ID")
    if PAYMENTS_ENABLED and not PAYMENT_PROVIDER_TOKEN:m.append("PAYMENT_PROVIDER_TOKEN")
    if m:raise RuntimeError("Missing environment variables: "+", ".join(m))
    if not active_servers():raise RuntimeError("No subscription servers found")
