import hashlib
import hmac
import time

from fastapi import Request
from fastapi.responses import RedirectResponse

import smart_webapp as web
from core import ADMIN_ID, BASE_URL, BOT_TOKEN, esc, log_action

app = web.app

# Register the customer-facing Telegram Mini App on the existing web service.
from miniapp import router as miniapp_router
app.include_router(miniapp_router)

# Keep the existing admin secret/magic-link login as a fallback, but also allow
# the Telegram account configured by ADMIN_ID to authenticate securely.
if not web.ADMIN_SESSION and BOT_TOKEN:
    web.ADMIN_SESSION = hashlib.sha256((BOT_TOKEN + ":telegram-admin-session").encode()).hexdigest()
if not web.ADMIN_CSRF and BOT_TOKEN:
    web.ADMIN_CSRF = hashlib.sha256((BOT_TOKEN + ":telegram-admin-csrf").encode()).hexdigest()[:32]

_original_admin_login_page = web.admin_login_page


def _telegram_widget() -> str:
    if not BOT_TOKEN or not ADMIN_ID:
        return ""
    auth_url = f"{BASE_URL}/admin/telegram-login"
    return f'''
<div style="display:flex;align-items:center;gap:12px;margin:20px 0 14px">
  <div style="height:1px;background:var(--ov);flex:1"></div>
  <span class="muted">или</span>
  <div style="height:1px;background:var(--ov);flex:1"></div>
</div>
<div style="display:grid;place-items:center;min-height:50px">
  <script async src="https://telegram.org/js/telegram-widget.js?22"
          data-telegram-login="Father_VPNs_bot"
          data-size="large"
          data-radius="20"
          data-userpic="false"
          data-auth-url="{esc(auth_url)}"></script>
</div>
<p style="text-align:center;font-size:12px;margin:12px 0 0">Доступ разрешён только Telegram-аккаунту администратора.</p>
'''


def admin_login_page(message: str = "") -> str:
    page = _original_admin_login_page(message)
    widget = _telegram_widget()
    if not widget:
        return page
    # Insert Telegram login after the existing secret-key form.
    return page.replace("</form>", "</form>" + widget, 1)


# Existing FastAPI route handlers resolve this module global at request time,
# so replacing the renderer upgrades /admin/login without rewriting smart_webapp.
web.admin_login_page = admin_login_page


def _verify_telegram_login(params: dict[str, str]) -> tuple[bool, str]:
    if not BOT_TOKEN or not ADMIN_ID:
        return False, "Telegram-вход не настроен"

    received_hash = params.get("hash", "")
    if not received_hash:
        return False, "Telegram не передал подпись"

    check_data = {k: v for k, v in params.items() if k != "hash"}
    data_check_string = "\n".join(f"{k}={check_data[k]}" for k in sorted(check_data))
    secret_key = hashlib.sha256(BOT_TOKEN.encode()).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        return False, "Неверная подпись Telegram"

    try:
        auth_date = int(params.get("auth_date", "0"))
        telegram_id = int(params.get("id", "0"))
    except (TypeError, ValueError):
        return False, "Некорректные данные Telegram"

    now = int(time.time())
    if auth_date <= 0 or abs(now - auth_date) > 300:
        return False, "Авторизация Telegram устарела. Войдите ещё раз"
    if telegram_id != ADMIN_ID:
        return False, "У этого Telegram-аккаунта нет доступа к админ-панели"

    return True, ""


@app.get("/admin/telegram-login")
async def admin_telegram_login(request: Request):
    params = {k: v for k, v in request.query_params.items()}
    ok, error = _verify_telegram_login(params)
    if not ok:
        return web.html_response(admin_login_page(error), 403)

    try:
        log_action(ADMIN_ID, "web_admin_login_telegram", "admin", ADMIN_ID, params.get("username", ""))
    except Exception:
        pass

    response = RedirectResponse("/admin", status_code=303)
    response.set_cookie(
        "fvpn_admin",
        web.ADMIN_SESSION,
        max_age=30 * 86400,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    return response
