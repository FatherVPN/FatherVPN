from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from core import (
    BASE_URL,
    BLOCKED_SUBSCRIPTION,
    INDEX_FILE,
    MAX_DEVICES,
    active_servers,
    create_device,
    db,
    delete_device,
    esc,
    fmt_dt,
    get_device,
    get_user_by_cabinet_token,
    list_devices,
    now_iso,
    parse_dt,
    set_device_blocked,
    subscription_active,
    utc_now,
)

app = FastAPI(title="FatherVPN", version="5.0")


def no_cache_headers():
    return {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
        "X-Content-Type-Options": "nosniff",
        "X-Robots-Tag": "noindex, nofollow, noarchive",
        "Referrer-Policy": "no-referrer",
    }


def sub_response(text, status=200):
    return PlainTextResponse(text, status_code=status, media_type="text/plain; charset=utf-8", headers=no_cache_headers())


def page_response(text, status=200):
    return HTMLResponse(text, status_code=status, headers=no_cache_headers())


def shell(title, body, script=""):
    return f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="referrer" content="no-referrer"><meta name="robots" content="noindex,nofollow,noarchive"><meta name="theme-color" content="#6750A4"><title>{esc(title)} — FatherVPN</title><style>
:root{{--p:#6750A4;--pc:#EADDFF;--opc:#21005D;--s:#FEF7FF;--sc:#F3EDF7;--sh:#ECE6F0;--t:#1D1B20;--v:#49454F;--o:#CAC4D0;--ok:#166534;--bad:#B3261E}}@media(prefers-color-scheme:dark){{:root{{--p:#D0BCFF;--pc:#4F378B;--opc:#EADDFF;--s:#141218;--sc:#211F26;--sh:#2B2930;--t:#E6E1E9;--v:#CAC4D0;--o:#49454F;--ok:#86efac;--bad:#F2B8B5}}}}*{{box-sizing:border-box}}body{{margin:0;background:var(--s);color:var(--t);font:15px/1.5 Inter,Roboto,system-ui,-apple-system,sans-serif}}a{{color:inherit;text-decoration:none}}.wrap{{max-width:900px;margin:auto;padding:20px}}header{{display:flex;justify-content:space-between;align-items:center;padding:8px 0 20px}}.brand{{font-size:20px;font-weight:900;display:flex;align-items:center;gap:10px}}.logo{{width:40px;height:40px;border-radius:14px;background:var(--p);color:#fff;display:grid;place-items:center;font-weight:900}}.card{{background:var(--sc);border:1px solid color-mix(in srgb,var(--o) 45%,transparent);border-radius:28px;padding:24px;margin:12px 0}}.hero{{padding:30px}}h1{{font-size:clamp(30px,8vw,50px);line-height:1.05;margin:12px 0}}h2{{font-size:20px;margin:0 0 14px}}p{{color:var(--v)}}.pill{{display:inline-flex;padding:8px 13px;border-radius:99px;background:var(--pc);color:var(--opc);font-weight:800}}.pill.ok{{color:var(--ok)}}.pill.bad{{color:var(--bad)}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}.stat{{background:var(--sh);border-radius:20px;padding:16px}}.stat small{{display:block;color:var(--v)}}.stat strong{{font-size:17px}}.btn{{display:inline-flex;align-items:center;justify-content:center;min-height:48px;padding:0 20px;border:0;border-radius:99px;background:var(--p);color:#fff;font:inherit;font-weight:800;cursor:pointer}}.btn.tonal{{background:var(--pc);color:var(--opc)}}.btn.ghost{{background:transparent;color:var(--t);border:1px solid var(--o)}}.btn.danger{{background:var(--bad)}}.actions{{display:flex;gap:9px;flex-wrap:wrap;margin-top:16px}}.copy{{background:var(--sh);padding:14px;border-radius:16px;word-break:break-all;font-family:ui-monospace,monospace;font-size:13px}}.device{{display:flex;justify-content:space-between;gap:14px;padding:18px 0;border-bottom:1px solid var(--o)}}.device:last-child{{border-bottom:0}}.device span{{color:var(--v);font-size:13px}}footer{{text-align:center;color:var(--v);padding:30px 0;font-size:13px}}form{{display:inline}}@media(max-width:620px){{.grid{{grid-template-columns:1fr}}.device{{display:block}}.device .actions{{margin-top:10px}}.wrap{{padding:14px}}.card{{border-radius:22px;padding:18px}}}}
</style></head><body><div class="wrap"><header><a class="brand" href="/"><span class="logo">F</span>FatherVPN</a><a class="btn tonal" href="https://t.me/Father_VPNs_bot">Telegram</a></header>{body}<footer>FatherVPN · личный кабинет и панель подписки</footer></div>{script}</body></html>'''


def find_device_by_token(token):
    c = db()
    try:
        return c.execute(
            """SELECT d.*,u.username,u.first_name,u.tariff,u.expires_at,u.blocked AS user_blocked
               FROM devices d JOIN users u ON u.user_id=d.user_id WHERE d.token=?""",
            (token,),
        ).fetchone()
    finally:
        c.close()


def device_state(row):
    if not row:
        return False, "Ссылка не найдена"
    if row["blocked"]:
        return False, "Устройство отключено"
    if row["user_blocked"]:
        return False, "Подписка заблокирована"
    exp = parse_dt(row["expires_at"])
    if not exp or exp <= utc_now():
        return False, "Срок подписки истёк"
    return True, "Подписка активна"


def device_panel_html(row, token):
    if not row:
        return shell("Ссылка не найдена", '<div class="card hero"><span class="pill bad">Недоступно</span><h1>Ссылка не найдена</h1><p>Создайте новую ссылку в Telegram-боте.</p></div>')
    active, reason = device_state(row)
    exp = parse_dt(row["expires_at"])
    days = max(0, int((exp - utc_now()).total_seconds() // 86400)) if exp and exp > utc_now() else 0
    raw = f"{BASE_URL}/d/{token}/raw"
    body = f'''<div class="card hero"><span class="pill {'ok' if active else 'bad'}">{esc(reason)}</span><h1>{esc(row['name'])}</h1><p>Это панель подписки. Обычный браузер больше не показывает сырой список серверов.</p></div><div class="grid"><div class="stat"><small>Тариф</small><strong>{esc(row['tariff'] or '—')}</strong></div><div class="stat"><small>Действует до</small><strong>{esc(fmt_dt(row['expires_at']))}</strong></div><div class="stat"><small>Осталось</small><strong>{days} дн.</strong></div><div class="stat"><small>Обновлений</small><strong>{row['request_count']}</strong></div></div><div class="card"><h2>Ссылка для VPN-клиента</h2><div class="copy" id="raw">{esc(raw)}</div><div class="actions"><button class="btn" onclick="copyRaw()">Скопировать</button><a class="btn tonal" href="{esc(raw)}">Открыть RAW</a></div><p>Используйте именно RAW-ссылку в V2rayNG, NekoBox, Hiddify, Shadowrocket и других клиентах.</p></div><div class="card"><h2>Устройство</h2><div class="grid"><div class="stat"><small>Последнее обновление</small><strong>{esc(fmt_dt(row['last_seen']))}</strong></div><div class="stat"><small>Последний IP</small><strong>{esc(row['last_ip'] or '—')}</strong></div></div></div>'''
    script = '<script>async function copyRaw(){let v=document.getElementById("raw").textContent;try{await navigator.clipboard.writeText(v);alert("Ссылка скопирована")}catch(e){prompt("Скопируйте ссылку",v)}}</script>'
    return shell(f"{row['name']} · подписка", body, script)


def cabinet_html(user):
    devices = list_devices(user["user_id"])
    active = subscription_active(user)
    exp = parse_dt(user["expires_at"])
    days = max(0, int((exp - utc_now()).total_seconds() // 86400)) if exp and exp > utc_now() else 0
    status = "Подписка активна" if active else ("Подписка заблокирована" if user["blocked"] else "Подписка неактивна")
    rows = []
    for d in devices:
        panel = f"{BASE_URL}/d/{d['token']}"
        rows.append(f'''<div class="device"><div><b>{esc(d['name'])}</b><br><span>{'Отключено' if d['blocked'] else 'Активно'} · запросов: {d['request_count']} · {esc(fmt_dt(d['last_seen']))}</span></div><div class="actions"><a class="btn tonal" href="{esc(panel)}">Панель</a><form method="post" action="/cabinet/{esc(user['cabinet_token'])}/device/{d['id']}/toggle"><button class="btn ghost">{'Включить' if d['blocked'] else 'Отключить'}</button></form><form method="post" action="/cabinet/{esc(user['cabinet_token'])}/device/{d['id']}/delete" onsubmit="return confirm('Удалить устройство?')"><button class="btn danger">Удалить</button></form></div></div>''')
    add = f'''<form method="post" action="/cabinet/{esc(user['cabinet_token'])}/device/add"><button class="btn">+ Добавить устройство</button></form>''' if active and len(devices) < MAX_DEVICES else ""
    body = f'''<div class="card hero"><span class="pill {'ok' if active else 'bad'}">{esc(status)}</span><h1>Личный кабинет</h1><p>{esc(user['first_name'] or user['username'] or 'Пользователь')}, здесь можно управлять подпиской и устройствами.</p></div><div class="grid"><div class="stat"><small>Тариф</small><strong>{esc(user['tariff'] or '—')}</strong></div><div class="stat"><small>Действует до</small><strong>{esc(fmt_dt(user['expires_at']))}</strong></div><div class="stat"><small>Осталось</small><strong>{days} дн.</strong></div><div class="stat"><small>Устройства</small><strong>{len(devices)} / {MAX_DEVICES}</strong></div></div><div class="card"><h2>Мои устройства</h2>{''.join(rows) or '<p>Устройств пока нет.</p>'}<div class="actions">{add}<a class="btn tonal" href="https://t.me/Father_VPNs_bot">Продлить подписку</a></div></div><div class="card"><h2>Безопасность</h2><p>Адрес этого кабинета — секретная ссылка. Не пересылайте её другим людям.</p></div>'''
    return shell("Личный кабинет", body)


@app.get("/", response_class=HTMLResponse)
async def home():
    try:
        return HTMLResponse(INDEX_FILE.read_text(encoding="utf-8"))
    except OSError:
        return page_response(shell("FatherVPN", '<div class="card"><h1>FatherVPN</h1><p>Сайт временно недоступен.</p></div>'), 503)


@app.get("/health")
async def health():
    return {"ok": bool(active_servers()), "base_url": BASE_URL}


@app.get("/cabinet/{token}", response_class=HTMLResponse)
async def cabinet(token: str):
    user = get_user_by_cabinet_token(token)
    if not user:
        return page_response(shell("Кабинет не найден", '<div class="card"><h1>Кабинет не найден</h1><p>Получите новую ссылку через Telegram-бота.</p></div>'), 404)
    return page_response(cabinet_html(user))


@app.post("/cabinet/{token}/device/add")
async def web_device_add(token: str):
    user = get_user_by_cabinet_token(token)
    if user and subscription_active(user) and len(list_devices(user["user_id"])) < MAX_DEVICES:
        create_device(user["user_id"])
    return RedirectResponse(f"/cabinet/{token}", status_code=303)


@app.post("/cabinet/{token}/device/{device_id}/toggle")
async def web_device_toggle(token: str, device_id: int):
    user = get_user_by_cabinet_token(token)
    d = get_device(device_id)
    if user and d and d["user_id"] == user["user_id"]:
        set_device_blocked(device_id, not bool(d["blocked"]))
    return RedirectResponse(f"/cabinet/{token}", status_code=303)


@app.post("/cabinet/{token}/device/{device_id}/delete")
async def web_device_delete(token: str, device_id: int):
    user = get_user_by_cabinet_token(token)
    d = get_device(device_id)
    if user and d and d["user_id"] == user["user_id"]:
        delete_device(device_id)
    return RedirectResponse(f"/cabinet/{token}", status_code=303)


@app.get("/d/{token}", response_class=HTMLResponse)
async def device_panel(token: str):
    row = find_device_by_token(token)
    return page_response(device_panel_html(row, token), 200 if row else 404)


@app.get("/d/{token}/raw", response_class=PlainTextResponse)
async def device_raw(token: str, request: Request):
    row = find_device_by_token(token)
    if not row:
        return sub_response(BLOCKED_SUBSCRIPTION)
    c = db()
    try:
        xff = request.headers.get("x-forwarded-for", "")
        ip = xff.split(",")[0].strip() if xff else (request.client.host if request.client else "")
        c.execute(
            "UPDATE devices SET last_seen=?,last_ip=?,user_agent=?,request_count=request_count+1 WHERE id=?",
            (now_iso(), ip[:64], request.headers.get("user-agent", "")[:500], row["id"]),
        )
        c.commit()
    finally:
        c.close()
    active, _ = device_state(row)
    if not active:
        return sub_response(BLOCKED_SUBSCRIPTION)
    content = active_servers()
    return sub_response(content if content else "FatherVPN: список серверов пуст", 200 if content else 503)
