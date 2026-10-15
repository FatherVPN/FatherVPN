import os
import hashlib
import hmac
import time

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
import jwt

from app.db import profile
from app.vpn_provider import get_or_create_config, VPNProviderNotConfigured

app = FastAPI(title="FatherVPN API", version="0.1.0")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
JWT_SECRET = os.getenv("JWT_SECRET", "")

if not JWT_SECRET:
    # Refuse to start with a guessable secret. This module is imported by
    # uvicorn, so the process will fail loudly instead of silently using
    # "CHANGE_ME_NOW".
    raise RuntimeError(
        "JWT_SECRET is not set. Generate a long random string and set it as "
        "an environment variable (e.g. `openssl rand -hex 32`)."
    )


class TelegramAuth(BaseModel):
    id: int
    first_name: str
    auth_date: int
    hash: str
    username: str | None = None
    photo_url: str | None = None


def verify_telegram(data: dict) -> None:
    if not BOT_TOKEN:
        raise HTTPException(503, "Telegram auth is not configured")

    received = data.get("hash", "")
    fields = {k: str(v) for k, v in data.items() if k != "hash" and v is not None}
    check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hashlib.sha256(BOT_TOKEN.encode()).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected, received):
        raise HTTPException(401, "Invalid Telegram signature")

    if abs(int(time.time()) - int(data["auth_date"])) > 86400:
        raise HTTPException(401, "Telegram auth data expired")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/")
def root():
    # Render's default health check hits "/". Keep this cheap.
    return {"service": "FatherVPN API", "ok": True}


@app.get("/api/plans")
def plans():
    return {
        "plans": [
            {
                "id": "monthly",
                "days": int(os.getenv("SUBSCRIPTION_DAYS", "30")),
                "stars": int(os.getenv("SUBSCRIPTION_STARS", "100")),
                "currency": "XTR",
            }
        ]
    }


@app.post("/api/telegram/auth")
def telegram_auth(payload: TelegramAuth):
    data = payload.model_dump()
    verify_telegram(data)

    token = jwt.encode(
        {"sub": str(payload.id), "exp": int(time.time()) + 3600},
        JWT_SECRET,
        algorithm="HS256",
    )
    return {"access_token": token, "token_type": "bearer", "expires_in": 3600}


def user_id(authorization: str | None) -> int:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token")
    try:
        payload = jwt.decode(authorization[7:], JWT_SECRET, algorithms=["HS256"])
        return int(payload["sub"])
    except Exception:
        raise HTTPException(401, "Invalid or expired token")


@app.get("/api/me")
def me(authorization: str | None = Header(default=None)):
    uid = user_id(authorization)
    user, sub = profile(uid)
    return {
        "telegram_id": uid,
        "username": user["username"] if user else None,
        "subscription": (
            {"status": sub["status"], "expires_at": sub["expires_at"]}
            if sub
            else None
        ),
    }


@app.get("/api/subscription/config")
async def subscription_config(authorization: str | None = Header(default=None)):
    uid = user_id(authorization)
    _, sub = profile(uid)
    if not sub:
        raise HTTPException(403, "No active subscription")
    try:
        return {"config": await get_or_create_config(uid)}
    except VPNProviderNotConfigured as exc:
        raise HTTPException(503, str(exc))
