import hashlib
import hmac
import json
import time
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qsl

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from core import (
    BOT_TOKEN,
    db,
    get_user,
    log_action,
    now_iso,
    parse_dt,
    subscription_active,
    subscription_url,
    upsert_user,
    utc_now,
    using_postgres,
)

router = APIRouter()
MAX_CYCLE_MINUTES = 350
COOLDOWN_SECONDS = 3 * 60 * 60
MAX_INIT_DATA_AGE_SECONDS = 24 * 60 * 60
HTML_FILE = Path(__file__).with_name("miniapp.html")
HTML_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow, noarchive",
}


def _init_progress_table() -> None:
    connection = db()
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS miniapp_progress (
                telegram_id BIGINT PRIMARY KEY,
                cycle_minutes INTEGER NOT NULL DEFAULT 0,
                cooldown_until TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.commit()
    finally:
        connection.close()


_init_progress_table()


def _verify_init_data(raw: str) -> dict:
    if not BOT_TOKEN:
        raise HTTPException(status_code=503, detail="Вход через Telegram не настроен.")
    if not raw or len(raw) > 8192:
        raise HTTPException(status_code=401, detail="Откройте приложение через Telegram.")

    pairs = parse_qsl(raw, keep_blank_values=True)
    if len({key for key, _ in pairs}) != len(pairs):
        raise HTTPException(status_code=401, detail="Некорректные данные Telegram.")
    data = dict(pairs)
    received_hash = data.pop("hash", "")
    if not received_hash:
        raise HTTPException(status_code=401, detail="Telegram не передал подпись.")

    check_string = "\n".join(f"{key}={value}" for key, value in sorted(data.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        raise HTTPException(status_code=401, detail="Не удалось подтвердить аккаунт Telegram.")

    try:
        auth_date = int(data.get("auth_date", "0"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Некорректная дата авторизации Telegram.")

    now = int(time.time())
    if auth_date <= 0 or now - auth_date > MAX_INIT_DATA_AGE_SECONDS or auth_date > now + 60:
        raise HTTPException(
            status_code=401,
            detail="Сессия Telegram устарела. Закройте и снова откройте приложение.",
        )

    try:
        user = json.loads(data.get("user", "{}"))
        telegram_id = int(user.get("id", 0))
    except (TypeError, ValueError, json.JSONDecodeError):
        raise HTTPException(status_code=401, detail="В данных Telegram нет пользователя.")

    if telegram_id <= 0:
        raise HTTPException(status_code=401, detail="В данных Telegram нет пользователя.")
    return user


def _authenticate(request: Request) -> tuple[int, dict]:
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("tma "):
        raw_init_data = authorization[4:].strip()
    else:
        raw_init_data = request.headers.get("x-telegram-init-data", "").strip()

    user = _verify_init_data(raw_init_data)
    telegram_id = int(user["id"])
    upsert_user(
        telegram_id,
        str(user.get("username") or ""),
        str(user.get("first_name") or ""),
    )
    return telegram_id, user


def _progress(telegram_id: int) -> dict:
    now = utc_now().replace(microsecond=0)
    connection = db()
    try:
        connection.execute(
            """
            INSERT INTO miniapp_progress
                (telegram_id, cycle_minutes, cooldown_until, updated_at)
            VALUES(?, 0, NULL, ?)
            ON CONFLICT(telegram_id) DO NOTHING
            """,
            (telegram_id, now.isoformat(timespec="seconds")),
        )
        row = connection.execute(
            "SELECT cycle_minutes, cooldown_until FROM miniapp_progress WHERE telegram_id=?",
            (telegram_id,),
        ).fetchone()
        cycle_minutes = int(row["cycle_minutes"] or 0)
        cooldown_raw = row["cooldown_until"]
        cooldown_until = parse_dt(cooldown_raw)

        if cooldown_raw and (not cooldown_until or now >= cooldown_until):
            cycle_minutes = 0
            cooldown_until = None
            connection.execute(
                """
                UPDATE miniapp_progress
                SET cycle_minutes=0, cooldown_until=NULL, updated_at=?
                WHERE telegram_id=?
                """,
                (now.isoformat(timespec="seconds"), telegram_id),
            )
        elif cycle_minutes >= MAX_CYCLE_MINUTES and not cooldown_until:
            cooldown_until = now + timedelta(seconds=COOLDOWN_SECONDS)
            connection.execute(
                "UPDATE miniapp_progress SET cooldown_until=?, updated_at=? WHERE telegram_id=?",
                (
                    cooldown_until.isoformat(timespec="seconds"),
                    now.isoformat(timespec="seconds"),
                    telegram_id,
                ),
            )

        connection.commit()
        return {
            "cycle_minutes": cycle_minutes,
            "cooldown_until": cooldown_until.isoformat(timespec="seconds") if cooldown_until else None,
        }
    finally:
        connection.close()


def _state(telegram_id: int, telegram_user: dict) -> dict:
    user = get_user(telegram_id)
    if not user:
        upsert_user(
            telegram_id,
            str(telegram_user.get("username") or ""),
            str(telegram_user.get("first_name") or ""),
        )
        user = get_user(telegram_id)

    progress = _progress(telegram_id)
    now = utc_now().replace(microsecond=0)
    expires_at = parse_dt(user["expires_at"]) if user and user["expires_at"] else None
    cooldown_until = parse_dt(progress["cooldown_until"])
    expires_in_seconds = max(0, int((expires_at - now).total_seconds())) if expires_at else 0
    cooldown_seconds = max(0, int((cooldown_until - now).total_seconds())) if cooldown_until else 0
    blocked = bool(int(user["blocked"] or 0)) if user else False
    cycle_minutes = int(progress["cycle_minutes"])

    return {
        "telegram_id": telegram_id,
        "first_name": str(telegram_user.get("first_name") or (user["first_name"] if user else "") or "Пользователь"),
        "username": str(telegram_user.get("username") or (user["username"] if user else "") or ""),
        "cycle_minutes": cycle_minutes,
        "max_cycle_minutes": MAX_CYCLE_MINUTES,
        "cooldown_until": progress["cooldown_until"],
        "cooldown_seconds": cooldown_seconds,
        "can_click": not blocked and cooldown_seconds == 0 and cycle_minutes < MAX_CYCLE_MINUTES,
        "blocked": blocked,
        "subscription_active": subscription_active(user),
        "expires_at": expires_at.isoformat(timespec="seconds") if expires_at else None,
        "expires_in_seconds": expires_in_seconds,
        "subscription_url": subscription_url(telegram_id),
        "server_now": now.isoformat(timespec="seconds"),
    }


@router.get("/miniapp")
async def miniapp_page():
    try:
        content = HTML_FILE.read_text(encoding="utf-8")
    except OSError:
        raise HTTPException(status_code=503, detail="Интерфейс приложения временно недоступен.")
    # Do not set X-Frame-Options: DENY here. Telegram Web may embed Mini Apps.
    return HTMLResponse(content, headers=HTML_HEADERS)


@router.get("/api/miniapp/state")
async def miniapp_state(request: Request):
    telegram_id, telegram_user = _authenticate(request)
    return _state(telegram_id, telegram_user)


@router.post("/api/miniapp/click")
async def miniapp_click(request: Request):
    telegram_id, telegram_user = _authenticate(request)
    now = utc_now().replace(microsecond=0)
    connection = db()
    new_cycle = 0
    new_expiry = None

    try:
        # Serialize clicks for a user so parallel requests cannot exceed the cap.
        if not using_postgres():
            connection.execute("BEGIN IMMEDIATE")

        connection.execute(
            """
            INSERT INTO miniapp_progress
                (telegram_id, cycle_minutes, cooldown_until, updated_at)
            VALUES(?, 0, NULL, ?)
            ON CONFLICT(telegram_id) DO NOTHING
            """,
            (telegram_id, now.isoformat(timespec="seconds")),
        )
        lock_suffix = " FOR UPDATE" if using_postgres() else ""
        progress = connection.execute(
            "SELECT cycle_minutes, cooldown_until FROM miniapp_progress WHERE telegram_id=?" + lock_suffix,
            (telegram_id,),
        ).fetchone()
        user = connection.execute(
            "SELECT * FROM users WHERE user_id=?" + lock_suffix,
            (telegram_id,),
        ).fetchone()

        if not user:
            connection.rollback()
            raise HTTPException(status_code=401, detail="Профиль не найден. Перезапустите приложение.")
        if bool(int(user["blocked"] or 0)):
            connection.rollback()
            raise HTTPException(status_code=403, detail="Доступ к FatherVPN заблокирован.")

        cycle_minutes = int(progress["cycle_minutes"] or 0)
        cooldown_raw = progress["cooldown_until"]
        cooldown_until = parse_dt(cooldown_raw)

        if cooldown_until and now < cooldown_until:
            connection.rollback()
            raise HTTPException(
                status_code=429,
                detail={
                    "message": "Лимит достигнут. Дождитесь обновления цикла.",
                    "cooldown_until": cooldown_until.isoformat(timespec="seconds"),
                },
            )

        if cooldown_raw and (not cooldown_until or now >= cooldown_until):
            cycle_minutes = 0
            cooldown_until = None

        if cycle_minutes >= MAX_CYCLE_MINUTES:
            cooldown_until = now + timedelta(seconds=COOLDOWN_SECONDS)
            connection.execute(
                "UPDATE miniapp_progress SET cooldown_until=?, updated_at=? WHERE telegram_id=?",
                (
                    cooldown_until.isoformat(timespec="seconds"),
                    now.isoformat(timespec="seconds"),
                    telegram_id,
                ),
            )
            connection.commit()
            raise HTTPException(
                status_code=429,
                detail={
                    "message": "Лимит достигнут. Дождитесь обновления цикла.",
                    "cooldown_until": cooldown_until.isoformat(timespec="seconds"),
                },
            )

        current_expiry = parse_dt(user["expires_at"]) if user["expires_at"] else None
        base_expiry = current_expiry if current_expiry and current_expiry > now else now
        new_expiry = (base_expiry + timedelta(minutes=1)).replace(microsecond=0)
        new_cycle = cycle_minutes + 1
        new_cooldown = (
            now + timedelta(seconds=COOLDOWN_SECONDS)
            if new_cycle >= MAX_CYCLE_MINUTES
            else None
        )

        connection.execute(
            """
            UPDATE users
            SET expires_at=?,
                tariff=CASE WHEN tariff IS NULL OR tariff='' THEN 'Бонусные минуты' ELSE tariff END
            WHERE user_id=?
            """,
            (new_expiry.isoformat(timespec="seconds"), telegram_id),
        )
        connection.execute(
            """
            UPDATE miniapp_progress
            SET cycle_minutes=?, cooldown_until=?, updated_at=?
            WHERE telegram_id=?
            """,
            (
                new_cycle,
                new_cooldown.isoformat(timespec="seconds") if new_cooldown else None,
                now.isoformat(timespec="seconds"),
                telegram_id,
            ),
        )
        connection.commit()
    except HTTPException:
        raise
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    try:
        log_action(
            telegram_id,
            "miniapp_minute_claimed",
            "user",
            telegram_id,
            f"cycle={new_cycle}/{MAX_CYCLE_MINUTES}; expires_at={new_expiry.isoformat(timespec='seconds')}",
        )
    except Exception:
        pass

    return _state(telegram_id, telegram_user)
