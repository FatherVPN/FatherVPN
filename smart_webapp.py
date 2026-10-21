import hashlib
import io
import os
import secrets
from urllib.parse import parse_qs, quote

import qrcode
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response

from core import BASE_URL, BLOCKED_SUBSCRIPTION, INDEX_FILE, TARIFFS, active_servers, db, ensure_cabinet_token, esc, fmt_dt, get_user, get_user_by_cabinet_token, get_user_by_subscription_token, grant_subscription, list_subscription_clients, log_action, parse_dt, record_subscription_client, resolve_target, set_user_blocked, subscription_active, subscription_url, utc_now

app = FastAPI(title="FatherVPN", version="7.0")
ADMIN_WEB_TOKEN = os.environ.get("ADMIN_WEB_TOKEN", "").strip()
ADMIN_SESSION = hashlib.sha256((ADMIN_WEB_TOKEN + ":session").encode()).hexdigest() if ADMIN_WEB_TOKEN else ""
ADMIN_CSRF = hashlib.sha256((ADMIN_WEB_TOKEN + ":csrf").encode()).hexdigest()[:32] if ADMIN_WEB_TOKEN else ""
NO_CACHE={"Cache-Control":"no-store, no-cache, must-revalidate, max-age=0","Pragma":"no-cache","Expires":"0","X-Content-Type-Options":"nosniff","X-Frame-Options":"DENY","Referrer-Policy":"no-referrer","X-Robots-Tag":"noindex, nofollow, noarchive"}

def browser(request: Request) -> bool:
    accept=request.headers.get("accept","").lower();ua=request.headers.get("user-agent","").lower()
    return "text/html" in accept or any(x in ua for x in ("mozilla/","chrome/","safari/","firefox/","edg/"))
def html_response(text,status=200): return HTMLResponse(text,status_code=status,headers=NO_CACHE)
def raw_response(text,status=200): return PlainTextResponse(text,status_code=status,media_type="text/plain; charset=utf-8",headers=NO_CACHE)
def actual_days(v):
    e=parse_dt(v)
    return max(0,int((e-utc_now()).total_seconds()//86400)) if e and e>utc_now() else 0
def status_info(u):
    if not u:return "Не найдена","bad","error"
    if u["blocked"]:return "Заблокирована","bad","block"
    if subscription_active(u):return "Активна","ok","verified"
    return "Неактивна","warn","schedule"
def material_head(title):
    return f'''<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#FEF7FF"><meta name="color-scheme" content="light dark"><meta name="robots" content="noindex,nofollow,noarchive"><title>{esc(title)} — FatherVPN</title><link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700;900&family=Roboto+Flex:opsz,wght@8..144,400..900&family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,400,0,0" rel="stylesheet">'''
BASE_CSS=r''':root{--p:#6750A4;--op:#fff;--pc:#EADDFF;--opc:#21005D;--sc:#E8DEF8;--osc:#1D192B;--tc:#FFD8E4;--otc:#31111D;--s:#FEF7FF;--sl:#F7F2FA;--sm:#F3EDF7;--sh:#ECE6F0;--shh:#E6E0E9;--t:#1D1B20;--v:#49454F;--o:#79747E;--ov:#CAC4D0;--err:#B3261E;--errc:#F9DEDC;--ok:#146C2E;--okc:#C4EED0;--warn:#7A5800;--warnc:#FFE08A;--shadow:0 1px 2px rgba(0,0,0,.13),0 3px 12px rgba(0,0,0,.08);color-scheme:light}:root[data-theme=dark]{--p:#D0BCFF;--op:#381E72;--pc:#4F378B;--opc:#EADDFF;--sc:#4A4458;--osc:#E8DEF8;--tc:#633B48;--otc:#FFD8E4;--s:#141218;--sl:#1D1B20;--sm:#211F26;--sh:#2B2930;--shh:#36343B;--t:#E6E1E9;--v:#CAC4D0;--o:#938F99;--ov:#49454F;--err:#F2B8B5;--errc:#8C1D18;--ok:#8FD49F;--okc:#113B20;--warn:#FFD66D;--warnc:#4C3A00;color-scheme:dark}@media(prefers-color-scheme:dark){:root[data-theme=system]{--p:#D0BCFF;--op:#381E72;--pc:#4F378B;--opc:#EADDFF;--sc:#4A4458;--osc:#E8DEF8;--tc:#633B48;--otc:#FFD8E4;--s:#141218;--sl:#1D1B20;--sm:#211F26;--sh:#2B2930;--shh:#36343B;--t:#E6E1E9;--v:#CAC4D0;--o:#938F99;--ov:#49454F;--err:#F2B8B5;--errc:#8C1D18;--ok:#8FD49F;--okc:#113B20;--warn:#FFD66D;--warnc:#4C3A00;color-scheme:dark}}*{box-sizing:border-box}body{margin:0;background:var(--s);color:var(--t);font:15px/1.5 Roboto,system-ui,-apple-system,sans-serif;-webkit-font-smoothing:antialiased}a{text-decoration:none;color:inherit}button,input,select{font:inherit}.material-symbols-rounded{font-variation-settings:'FILL' 0,'wght' 400,'GRAD' 0,'opsz' 24}.wrap{width:min(1040px,calc(100% - 28px));margin:auto}.top{position:sticky;top:0;z-index:40;background:color-mix(in srgb,var(--s) 88%,transparent);backdrop-filter:blur(18px);border-bottom:1px solid color-mix(in srgb,var(--ov) 55%,transparent)}.bar{height:70px;display:flex;align-items:center;justify-content:space-between;gap:12px}.brand{display:flex;align-items:center;gap:10px;font:900 19px 'Roboto Flex',Roboto,sans-serif}.logo{width:40px;height:40px;border-radius:14px;background:var(--p);color:var(--op);display:grid;place-items:center;box-shadow:var(--shadow)}.top-actions{display:flex;gap:8px;align-items:center}.icon-btn{width:46px;height:46px;border:0;border-radius:50%;background:transparent;color:var(--v);display:grid;place-items:center;cursor:pointer}.icon-btn:hover{background:var(--sh)}.btn{border:0;border-radius:999px;min-height:46px;padding:0 20px;display:inline-flex;align-items:center;justify-content:center;gap:8px;font-weight:700;cursor:pointer;transition:.15s}.btn:active{transform:scale(.98)}.filled{background:var(--p);color:var(--op);box-shadow:var(--shadow)}.tonal{background:var(--sc);color:var(--osc)}.outline{background:transparent;color:var(--t);box-shadow:inset 0 0 0 1px var(--o)}.danger{background:var(--err);color:white}.main{padding:28px 0 56px}.card{background:var(--sm);border-radius:28px;padding:24px;margin:12px 0}.hero{padding:30px}.hero h1{font:900 clamp(34px,7vw,58px)/1.02 'Roboto Flex',Roboto,sans-serif;letter-spacing:-.035em;margin:12px 0}.hero p{color:var(--v);font-size:16px;max-width:650px}.chip{display:inline-flex;align-items:center;gap:7px;min-height:34px;padding:0 12px;border-radius:10px;font-weight:700;font-size:13px}.chip.ok{background:var(--okc);color:var(--ok)}.chip.bad{background:var(--errc);color:var(--err)}.chip.warn{background:var(--warnc);color:var(--warn)}.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.stat{background:var(--sl);border-radius:22px;padding:19px}.stat small{display:block;color:var(--v);margin-bottom:5px}.stat strong{font:800 18px 'Roboto Flex',Roboto,sans-serif}.connect{display:grid;grid-template-columns:240px 1fr;gap:28px;align-items:center}.qr-wrap{background:white;border-radius:26px;padding:14px;box-shadow:var(--shadow);width:240px;height:240px}.qr-wrap img{width:100%;height:100%;display:block}.linkbox{display:flex;align-items:center;gap:8px;background:var(--sh);border-radius:18px;padding:7px 8px 7px 14px}.linkbox code{min-width:0;flex:1;word-break:break-all;font:13px ui-monospace,SFMono-Regular,Consolas,monospace;color:var(--v)}.linkbox .icon-btn{flex:none}.actions{display:flex;gap:9px;flex-wrap:wrap;margin-top:16px}.guide{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.guide-item{background:var(--sl);padding:17px;border-radius:20px}.guide-item b{display:block;margin:7px 0 3px}.guide-item span{color:var(--v);font-size:13px}.snackbar{position:fixed;left:50%;bottom:24px;z-index:100;transform:translate(-50%,18px);opacity:0;background:var(--t);color:var(--s);padding:12px 18px;border-radius:10px;transition:.2s;pointer-events:none}.snackbar.show{opacity:1;transform:translate(-50%,0)}@media(max-width:700px){.connect{grid-template-columns:1fr}.qr-wrap{margin:auto}.stats,.guide{grid-template-columns:1fr}.card{padding:18px;border-radius:23px}.main{padding-top:16px}.hide-mobile{display:none}}'''
THEME_JS=r'''<script>(function(){const r=document.documentElement,b=document.getElementById('themeBtn'),i=document.getElementById('themeIcon'),m=document.querySelector('meta[name="theme-color"]');r.dataset.theme=localStorage.getItem('fvpn-theme')||'system';function a(){const t=r.dataset.theme;return t==='system'?(matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light'):t}function p(){const d=a()==='dark';if(i)i.textContent=d?'light_mode':'dark_mode';if(m)m.content=d?'#141218':'#FEF7FF'}p();b&&b.addEventListener('click',()=>{r.dataset.theme=a()==='dark'?'light':'dark';localStorage.setItem('fvpn-theme',r.dataset.theme);p()});window.fvSnack=(x)=>{const s=document.getElementById('snackbar');if(!s)return;s.textContent=x;s.classList.add('show');clearTimeout(window._fst);window._fst=setTimeout(()=>s.classList.remove('show'),1800)}})();</script>'''
def user_panel(u):
    active=subscription_active(u);state,tone,icon=status_info(u);days=actual_days(u["expires_at"]);url=subscription_url(u["user_id"]);token=u["subscription_token"] or ""
    body=f'''<header class="top"><div class="wrap bar"><a class="brand" href="/"><span class="logo"><span class="material-symbols-rounded">shield_lock</span></span>FatherVPN</a><div class="top-actions"><button class="icon-btn" id="themeBtn"><span class="material-symbols-rounded" id="themeIcon">dark_mode</span></button><a class="btn tonal hide-mobile" href="https://t.me/Father_VPNs_bot">Telegram</a></div></div></header><main class="main"><div class="wrap"><section class="card hero"><span class="chip {tone}"><span class="material-symbols-rounded">{icon}</span>{esc(state)}</span><h1>Моя подписка</h1><p>Одна персональная ссылка для FatherVPN. В браузере она открывает эту панель, а VPN-клиент получает конфигурацию автоматически.</p></section><div class="stats"><div class="stat"><small>Тариф</small><strong>{esc(u['tariff'] or '—')}</strong></div><div class="stat"><small>Действует до</small><strong>{esc(fmt_dt(u['expires_at']))}</strong></div><div class="stat"><small>Осталось</small><strong>{days} дн.</strong></div></div><section class="card connect"><div class="qr-wrap"><img src="/s/{esc(token)}/qr" alt="QR-код подписки"></div><div><span class="chip {'ok' if active else 'warn'}"><span class="material-symbols-rounded">{'qr_code_2' if active else 'info'}</span>{'Готово к подключению' if active else 'Подписка неактивна'}</span><h2 style="font:850 28px 'Roboto Flex',Roboto,sans-serif;margin:14px 0 7px">Подключить FatherVPN</h2><p style="color:var(--v);margin-top:0">Отсканируйте QR-код в VPN-клиенте или скопируйте ссылку.</p><div class="linkbox"><code id="subUrl">{esc(url)}</code><button class="icon-btn" onclick="copySub()"><span class="material-symbols-rounded">content_copy</span></button></div><div class="actions"><button class="btn filled" onclick="copySub()"><span class="material-symbols-rounded">content_copy</span>Скопировать ссылку</button><a class="btn tonal" href="https://t.me/Father_VPNs_bot"><span class="material-symbols-rounded">event_repeat</span>Продлить</a></div></div></section><section class="card"><h2 style="font:800 22px 'Roboto Flex',Roboto,sans-serif;margin-top:0">Как подключиться</h2><div class="guide"><div class="guide-item"><span class="material-symbols-rounded">download</span><b>1. Откройте VPN-клиент</b><span>V2rayNG, Hiddify, NekoBox, Shadowrocket или совместимый.</span></div><div class="guide-item"><span class="material-symbols-rounded">qr_code_scanner</span><b>2. Добавьте подписку</b><span>Отсканируйте QR или вставьте персональную ссылку.</span></div><div class="guide-item"><span class="material-symbols-rounded">power_settings_new</span><b>3. Подключитесь</b><span>Серверы будут обновляться автоматически.</span></div></div></section></div></main><div class="snackbar" id="snackbar">Ссылка скопирована</div><script>async function copySub(){{const v=document.getElementById('subUrl').textContent;try{{await navigator.clipboard.writeText(v);fvSnack('Ссылка скопирована')}}catch(e){{prompt('Скопируйте ссылку',v)}}}}</script>{THEME_JS}'''
    return f'<!doctype html><html lang="ru" data-theme="system"><head>{material_head("Моя подписка")}<style>{BASE_CSS}</style></head><body>{body}</body></html>'
ADMIN_CSS=BASE_CSS+r'''.admin-layout{display:grid;grid-template-columns:248px 1fr;min-height:100vh}.side{position:sticky;top:0;height:100vh;background:var(--sl);padding:18px 14px;border-right:1px solid var(--ov);display:flex;flex-direction:column}.side .brand{padding:8px 10px 20px}.nav-item{display:flex;align-items:center;gap:12px;min-height:52px;padding:0 16px;border-radius:26px;color:var(--v);font-weight:700;margin:2px 0}.nav-item:hover,.nav-item.active{background:var(--sc);color:var(--osc)}.side-spacer{flex:1}.admin-main{min-width:0}.admin-top{position:sticky;top:0;z-index:20;background:color-mix(in srgb,var(--s) 90%,transparent);backdrop-filter:blur(18px);height:72px;display:flex;align-items:center;justify-content:space-between;gap:12px;padding:0 24px;border-bottom:1px solid var(--ov)}.admin-content{padding:24px;max-width:1440px;margin:auto}.admin-title{font:900 clamp(30px,4vw,44px)/1.05 'Roboto Flex',Roboto,sans-serif;letter-spacing:-.03em;margin:0}.admin-sub{color:var(--v);margin:5px 0 0}.metric-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin:22px 0}.metric{background:var(--sm);border-radius:24px;padding:19px;min-height:118px}.metric .mi{width:38px;height:38px;border-radius:13px;background:var(--pc);color:var(--opc);display:grid;place-items:center;margin-bottom:12px}.metric small{display:block;color:var(--v)}.metric strong{font:900 26px 'Roboto Flex',Roboto,sans-serif}.admin-grid{display:grid;grid-template-columns:1fr 360px;gap:14px}.panel{background:var(--sm);border-radius:28px;padding:20px;margin-bottom:14px}.panel h2{font:800 20px 'Roboto Flex',Roboto,sans-serif;margin:0 0 15px}.searchbar{display:flex;gap:9px;align-items:center}.field{min-height:48px;border:1px solid var(--o);background:transparent;color:var(--t);border-radius:14px;padding:0 14px;outline:none}.field:focus{border:2px solid var(--p);padding:0 13px}.searchbar .field{flex:1}.filter-row{display:flex;gap:7px;flex-wrap:wrap;margin-top:12px}.filter-chip{display:inline-flex;align-items:center;min-height:34px;padding:0 12px;border-radius:10px;border:1px solid var(--o);color:var(--v);font-weight:700;font-size:13px}.filter-chip.active{background:var(--sc);color:var(--osc);border-color:transparent}.table-wrap{overflow:auto;border-radius:20px}.table{width:100%;border-collapse:collapse;min-width:760px}.table th{text-align:left;color:var(--v);font-size:12px;font-weight:800;padding:12px 13px;border-bottom:1px solid var(--ov)}.table td{padding:13px;border-bottom:1px solid color-mix(in srgb,var(--ov) 75%,transparent);vertical-align:middle}.table tr:last-child td{border-bottom:0}.user-name{font-weight:800}.muted{color:var(--v);font-size:13px}.mini{min-height:36px;padding:0 13px;font-size:13px}.quick-form{display:grid;grid-template-columns:1fr 150px auto;gap:8px}.activity{display:grid;gap:8px}.activity-item{background:var(--sl);border-radius:18px;padding:13px}.activity-item b{display:block}.empty{text-align:center;color:var(--v);padding:34px}.user-head{display:flex;justify-content:space-between;gap:20px;align-items:flex-start}.user-actions{display:flex;gap:8px;flex-wrap:wrap}.grant-grid{display:grid;grid-template-columns:repeat(6,1fr);gap:8px}.copy-row{display:flex;gap:8px;align-items:center}.copy-row code{flex:1;background:var(--sl);padding:12px 14px;border-radius:14px;word-break:break-all;font-size:12px}.login{min-height:100vh;display:grid;place-items:center;padding:20px}.login-card{width:min(460px,100%);background:var(--sm);border-radius:32px;padding:30px}.login-card .logo{margin-bottom:22px}.login-card h1{font:900 36px 'Roboto Flex',Roboto,sans-serif;margin:0 0 8px}.login-card p{color:var(--v)}@media(max-width:1100px){.metric-grid{grid-template-columns:repeat(3,1fr)}.admin-grid{grid-template-columns:1fr}.side{width:86px}.admin-layout{grid-template-columns:86px 1fr}.side .brand{justify-content:center}.side .brand span:last-child,.nav-item span:last-child{display:none}.nav-item{justify-content:center;padding:0}.grant-grid{grid-template-columns:repeat(3,1fr)}}@media(max-width:720px){.admin-layout{display:block}.side{position:fixed;z-index:50;left:0;right:0;bottom:0;top:auto;width:auto;height:72px;display:flex;flex-direction:row;padding:8px;background:color-mix(in srgb,var(--s) 94%,transparent);backdrop-filter:blur(18px);border:0;border-top:1px solid var(--ov)}.side .brand,.side-spacer,.side .nav-item:nth-of-type(n+5){display:none}.nav-item{flex:1;display:grid;place-items:center;gap:0;height:54px;min-height:54px}.nav-item .material-symbols-rounded{font-size:23px}.admin-content{padding:16px 12px 92px}.admin-top{padding:0 14px}.metric-grid{grid-template-columns:repeat(2,1fr)}.quick-form{grid-template-columns:1fr}.grant-grid{grid-template-columns:repeat(2,1fr)}.user-head{display:block}.admin-title{font-size:32px}.hide-sm{display:none}}'''
def admin_authed(request): return bool(ADMIN_SESSION) and secrets.compare_digest(request.cookies.get("fvpn_admin",""),ADMIN_SESSION)
def admin_shell(title,content,active="dashboard"):
    nav=[("dashboard","dashboard","Обзор","/admin"),("users","group","Пользователи","/admin#users"),("payments","payments","Платежи","/admin#payments"),("audit","history","Журнал","/admin#audit")]
    items="".join(f'<a class="nav-item {"active" if k==active else ""}" href="{h}"><span class="material-symbols-rounded">{i}</span><span>{l}</span></a>' for k,i,l,h in nav)
    return f'''<!doctype html><html lang="ru" data-theme="system"><head>{material_head(title)}<style>{ADMIN_CSS}</style></head><body><div class="admin-layout"><aside class="side"><a class="brand" href="/admin"><span class="logo"><span class="material-symbols-rounded">admin_panel_settings</span></span><span>FatherVPN</span></a>{items}<div class="side-spacer"></div><a class="nav-item" href="/" target="_blank"><span class="material-symbols-rounded">open_in_new</span><span>Открыть сайт</span></a><a class="nav-item" href="/admin/logout"><span class="material-symbols-rounded">logout</span><span>Выйти</span></a></aside><div class="admin-main"><header class="admin-top"><div><b>Панель управления</b></div><div class="top-actions"><button class="icon-btn" id="themeBtn"><span class="material-symbols-rounded" id="themeIcon">dark_mode</span></button><a class="btn tonal hide-sm" href="https://t.me/Father_VPNs_bot"><span class="material-symbols-rounded">send</span>Бот</a></div></header><main class="admin-content">{content}</main></div></div><div class="snackbar" id="snackbar">Готово</div>{THEME_JS}<script>async function cp(id){{const v=document.getElementById(id).textContent;try{{await navigator.clipboard.writeText(v);fvSnack('Скопировано')}}catch(e){{prompt('Скопируйте',v)}}}}</script></body></html>'''
def admin_login_page(message=""):
    err=f'<div class="chip bad" style="margin:10px 0"><span class="material-symbols-rounded">error</span>{esc(message)}</div>' if message else ""
    return f'''<!doctype html><html lang="ru" data-theme="system"><head>{material_head("Вход в админ-панель")}<style>{ADMIN_CSS}</style></head><body><div class="login"><div class="login-card"><div class="logo"><span class="material-symbols-rounded">admin_panel_settings</span></div><h1>Админ-панель</h1><p>Введите секретный ключ администратора. Удобнее открыть панель кнопкой из Telegram-бота — вход выполнится автоматически.</p>{err}<form method="post" action="/admin/login"><input class="field" name="token" type="password" autocomplete="current-password" placeholder="Секретный ключ" style="width:100%;margin:10px 0"><button class="btn filled" style="width:100%;margin-top:6px"><span class="material-symbols-rounded">login</span>Войти</button></form></div></div>{THEME_JS}</body></html>'''
def admin_stats():
    from datetime import timedelta
    now=utc_now().isoformat();soon=(utc_now()+timedelta(days=3)).isoformat();c=db()
    try:
        total=c.execute("SELECT COUNT(*) FROM users").fetchone()[0];active=c.execute("SELECT COUNT(*) FROM users WHERE blocked=0 AND expires_at IS NOT NULL AND expires_at>?",(now,)).fetchone()[0];blocked=c.execute("SELECT COUNT(*) FROM users WHERE blocked=1").fetchone()[0];expiring=c.execute("SELECT COUNT(*) FROM users WHERE blocked=0 AND expires_at>? AND expires_at<=?",(now,soon)).fetchone()[0];pay_count,pay_sum=c.execute("SELECT COUNT(*),COALESCE(SUM(amount),0) FROM payments").fetchone();return total,active,blocked,expiring,pay_count,pay_sum
    finally:c.close()
def user_where(q,flt):
    clauses=[];args=[];now=utc_now().isoformat()
    if q:clauses.append("(CAST(user_id AS TEXT) LIKE ? OR lower(username) LIKE ? OR lower(first_name) LIKE ?)");term=f"%{q.lower()}%";args.extend([term,term,term])
    if flt=="active":clauses.append("blocked=0 AND expires_at IS NOT NULL AND expires_at>?");args.append(now)
    elif flt=="blocked":clauses.append("blocked=1")
    elif flt=="expired":clauses.append("blocked=0 AND (expires_at IS NULL OR expires_at<=?)");args.append(now)
    return (" WHERE "+" AND ".join(clauses) if clauses else ""),args
def admin_dashboard(q="",flt="all"):
    total,active,blocked,expiring,pay_count,pay_sum=admin_stats();where,args=user_where(q,flt);c=db()
    try:users=c.execute(f"SELECT * FROM users{where} ORDER BY created_at DESC LIMIT 200",args).fetchall();payments=c.execute("SELECT p.*,u.username,u.first_name FROM payments p LEFT JOIN users u ON u.user_id=p.user_id ORDER BY p.id DESC LIMIT 25").fetchall();audit=c.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 20").fetchall()
    finally:c.close()
    servers=sum(1 for line in active_servers().splitlines() if line and not line.startswith("#"));metrics=[("group","Пользователей",total),("verified","Активных",active),("block","Заблокировано",blocked),("schedule","Истекает ≤ 3 дн.",expiring),("dns","Серверов",servers)];cards="".join(f'<div class="metric"><div class="mi"><span class="material-symbols-rounded">{ic}</span></div><small>{esc(label)}</small><strong>{value}</strong></div>' for ic,label,value in metrics);tabs=[("all","Все"),("active","Активные"),("expired","Неактивные"),("blocked","Заблокированные")];chips="".join(f'<a class="filter-chip {"active" if flt==key else ""}" href="/admin?filter={key}&q={quote(q)}#users">{label}</a>' for key,label in tabs)
    rows=[]
    for u in users:
        st,tone,_=status_info(u);ident="@"+u["username"] if u["username"] else (u["first_name"] or "Без имени");rows.append(f'''<tr><td><div class="user-name">{esc(ident)}</div><div class="muted">ID {u['user_id']}</div></td><td><span class="chip {tone}">{esc(st)}</span></td><td>{esc(u['tariff'] or '—')}</td><td>{esc(fmt_dt(u['expires_at']))}</td><td><a class="btn tonal mini" href="/admin/user/{u['user_id']}"><span class="material-symbols-rounded">manage_accounts</span>Открыть</a></td></tr>''')
    user_table=''.join(rows) or '<tr><td colspan="5" class="empty">Пользователи не найдены</td></tr>';pay_rows=[]
    for p in payments:
        name=("@"+p["username"]) if p["username"] else (p["first_name"] or str(p["user_id"]));pay_rows.append(f'''<tr><td><b>{esc(name)}</b><div class="muted">ID {p['user_id']}</div></td><td>{esc(p['tariff_code'])}</td><td><b>{p['amount']/100:.2f} {esc(p['currency'])}</b></td><td>{esc(fmt_dt(p['created_at']))}</td></tr>''')
    pay_table=''.join(pay_rows) or '<tr><td colspan="4" class="empty">Платежей пока нет</td></tr>';audit_items=''.join(f'<div class="activity-item"><b>{esc(a["action"])}</b><span class="muted">{esc(a["target_type"] or "")} {esc(a["target_id"] or "")} · {esc(fmt_dt(a["created_at"]))}</span></div>' for a in audit) or '<div class="empty">Журнал пуст</div>'
    content=f'''<div><h1 class="admin-title">Панель FatherVPN</h1><p class="admin-sub">Пользователи, подписки и платежи — в одном месте.</p></div><div class="metric-grid">{cards}</div><div class="admin-grid"><div><section class="panel"><h2>Быстро выдать подписку</h2><form class="quick-form" method="post" action="/admin/action"><input type="hidden" name="csrf" value="{ADMIN_CSRF}"><input class="field" name="target" placeholder="ID или @username" required><select class="field" name="action"><option value="grant:1d">+ 1 день</option><option value="grant:7d">+ 7 дней</option><option value="grant:1m" selected>+ 1 месяц</option><option value="grant:3m">+ 3 месяца</option><option value="grant:6m">+ 6 месяцев</option><option value="grant:12m">+ 12 месяцев</option></select><button class="btn filled"><span class="material-symbols-rounded">add_circle</span>Выдать</button></form></section><section class="panel" id="users"><h2>Пользователи</h2><form class="searchbar" method="get" action="/admin"><input class="field" name="q" value="{esc(q)}" placeholder="Поиск по ID, username или имени"><input type="hidden" name="filter" value="{esc(flt)}"><button class="btn tonal"><span class="material-symbols-rounded">search</span><span class="hide-sm">Найти</span></button></form><div class="filter-row">{chips}</div><div class="table-wrap" style="margin-top:12px"><table class="table"><thead><tr><th>Пользователь</th><th>Статус</th><th>Тариф</th><th>До</th><th></th></tr></thead><tbody>{user_table}</tbody></table></div></section><section class="panel" id="payments"><div class="user-head"><div><h2>Последние платежи</h2><div class="muted">Всего: {pay_count} · Сумма: {pay_sum/100:.2f} {esc(os.environ.get('PAYMENT_CURRENCY','RUB'))}</div></div></div><div class="table-wrap"><table class="table"><thead><tr><th>Пользователь</th><th>Тариф</th><th>Сумма</th><th>Дата</th></tr></thead><tbody>{pay_table}</tbody></table></div></section></div><aside><section class="panel" id="audit"><h2>Последние действия</h2><div class="activity">{audit_items}</div></section><section class="panel"><h2>Состояние</h2><div class="activity"><div class="activity-item"><b>API и сайт</b><span class="muted">Один Render Web Service</span></div><div class="activity-item"><b>VPN-серверы</b><span class="muted">{servers} конфигураций загружено</span></div></div></section></aside></div>''';return admin_shell("Админ-панель",content)
def admin_user_page(uid):
    u=get_user(uid)
    if not u:return admin_shell("Пользователь не найден",'<div class="panel"><h1 class="admin-title">Пользователь не найден</h1><div class="actions"><a class="btn tonal" href="/admin">Назад</a></div></div>',"users")
    st,tone,icon=status_info(u);sub=subscription_url(uid);cab=f"{BASE_URL}/cabinet/{ensure_cabinet_token(uid)}";username="@"+u["username"] if u["username"] else "Без username";grant=''.join(f'''<form method="post" action="/admin/action"><input type="hidden" name="csrf" value="{ADMIN_CSRF}"><input type="hidden" name="user_id" value="{uid}"><input type="hidden" name="action" value="grant:{code}"><button class="btn tonal" style="width:100%">{t['emoji']} +{t['name']}</button></form>''' for code,t in TARIFFS.items());ba="unblock" if u["blocked"] else "block";bt="Разблокировать" if u["blocked"] else "Заблокировать";bi="lock_open" if u["blocked"] else "block"
    content=f'''<div class="user-head"><div><a class="muted" href="/admin">← Все пользователи</a><h1 class="admin-title" style="margin-top:8px">{esc(u['first_name'] or username)}</h1><p class="admin-sub">{esc(username)} · Telegram ID {uid}</p></div><span class="chip {tone}"><span class="material-symbols-rounded">{icon}</span>{esc(st)}</span></div><div class="metric-grid" style="grid-template-columns:repeat(3,1fr)"><div class="metric"><small>Тариф</small><strong>{esc(u['tariff'] or '—')}</strong></div><div class="metric"><small>Действует до</small><strong style="font-size:19px">{esc(fmt_dt(u['expires_at']))}</strong></div><div class="metric"><small>Осталось</small><strong>{actual_days(u['expires_at'])} дн.</strong></div></div><section class="panel"><h2>Продлить подписку</h2><div class="grant-grid">{grant}</div></section><div class="admin-grid"><div><section class="panel"><h2>Персональная ссылка</h2><div class="copy-row"><code id="subLink">{esc(sub)}</code><button class="icon-btn" onclick="cp('subLink')"><span class="material-symbols-rounded">content_copy</span></button></div><div class="actions"><a class="btn filled" target="_blank" href="{esc(sub)}"><span class="material-symbols-rounded">open_in_new</span>Открыть подписку</a><form method="post" action="/admin/action" onsubmit="return confirm('Старая ссылка сразу перестанет работать. Создать новую?')"><input type="hidden" name="csrf" value="{ADMIN_CSRF}"><input type="hidden" name="user_id" value="{uid}"><input type="hidden" name="action" value="rotate"><button class="btn outline"><span class="material-symbols-rounded">refresh</span>Сменить ссылку</button></form></div></section><section class="panel"><h2>Личный кабинет</h2><div class="copy-row"><code id="cabLink">{esc(cab)}</code><button class="icon-btn" onclick="cp('cabLink')"><span class="material-symbols-rounded">content_copy</span></button></div></section></div><aside><section class="panel"><h2>Управление</h2><form method="post" action="/admin/action"><input type="hidden" name="csrf" value="{ADMIN_CSRF}"><input type="hidden" name="user_id" value="{uid}"><input type="hidden" name="action" value="{ba}"><button class="btn {'tonal' if u['blocked'] else 'danger'}" style="width:100%"><span class="material-symbols-rounded">{bi}</span>{bt}</button></form>{f'<a class="btn outline" style="width:100%;margin-top:8px" href="https://t.me/{esc(u["username"])}" target="_blank"><span class="material-symbols-rounded">send</span>Открыть Telegram</a>' if u['username'] else ''}</section></aside></div>''';clients = list_subscription_clients(uid, 20)
    client_rows = "".join(
        f'<tr><td>{esc(c["client_name"])}</td><td>{esc(c["ip_address"] or "—")}</td><td>{int(c["request_count"] or 0)}</td><td>{esc(fmt_dt(c["first_seen"]))}</td><td>{esc(fmt_dt(c["last_seen"]))}</td><td><details><summary>Показать</summary><code>{esc((c["user_agent"] or "—")[:350])}</code></details></td></tr>'
        for c in clients
    ) or '<tr><td colspan="6" class="empty">Пока нет обращений к персональной ссылке.</td></tr>'
    last_seen = fmt_dt(clients[0]["last_seen"]) if clients else "—"
    content += f'''<section class="panel"><h2>Трафик и VPN-клиенты</h2>
<div class="stats" style="grid-template-columns:repeat(3,1fr)">
  <div class="stat"><small>Использовано трафика</small><strong>Нет данных</strong></div>
  <div class="stat"><small>Клиентских профилей по запросам</small><strong>{len(clients)}</strong></div>
  <div class="stat"><small>Последнее обновление ссылки</small><strong>{esc(last_seen)}</strong></div>
</div>
<div class="chip warn" style="margin:14px 0"><span class="material-symbols-rounded">info</span>Это обращения к ссылке подписки, а не список активных VPN-соединений.</div>
<p class="muted">Сейчас в подписке сторонние серверы без доступной для FatherVPN статистики. Чтобы показывать реальные гигабайты, нужны собственные управляемые Xray/3x-ui узлы, статистический API и отдельные UUID пользователей. До подключения такой интеграции трафик намеренно показан как «Нет данных».</p>
<h2 style="margin-top:24px">Клиенты, обновлявшие подписку</h2>
<div class="table-wrap"><table class="table" style="min-width:850px"><thead><tr><th>Клиент</th><th>IP</th><th>Запросов</th><th>Первый запрос</th><th>Последний запрос</th><th>User-Agent</th></tr></thead><tbody>{client_rows}</tbody></table></div>
<p class="muted">Клиент определяется по User-Agent, если приложение его передаёт. Группировка по приложению, IP и User-Agent приблизительная: она не гарантирует подсчёт физических устройств и не подтверждает, что VPN прямо сейчас подключён.</p>
</section>'''
    return admin_shell(str(u['first_name'] or uid),content,"users")
@app.get('/')
async def home():
    try:return HTMLResponse(INDEX_FILE.read_text(encoding='utf-8'))
    except OSError:return html_response('FatherVPN',503)
@app.get('/health')
async def health():return {'ok':bool(active_servers()),'version':'7.0','admin':bool(ADMIN_WEB_TOKEN)}
@app.get('/cabinet/{token}')
async def cabinet(token:str):
    u=get_user_by_cabinet_token(token);return html_response(user_panel(u)) if u else html_response('<h1>Ссылка не найдена</h1>',404)
@app.get('/s/{token}')
async def smart_subscription(token:str,request:Request):
    u=get_user_by_subscription_token(token)
    if not u:
        return html_response('<h1>Ссылка не найдена</h1>',404) if browser(request) else raw_response(BLOCKED_SUBSCRIPTION)
    forwarded = request.headers.get("x-forwarded-for", "")
    ip_address = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "")
    is_browser = browser(request)
    try:
        record_subscription_client(
            int(u["user_id"]),
            request.headers.get("user-agent", ""),
            ip_address,
            request.headers.get("accept", ""),
            is_browser,
        )
    except Exception:
        # Monitoring must never prevent a customer from loading their subscription.
        pass
    if is_browser:
        return html_response(user_panel(u))
    if not subscription_active(u):
        return raw_response(BLOCKED_SUBSCRIPTION)
    content=active_servers()
    return raw_response(content if content else 'FatherVPN: список серверов пуст',200 if content else 503)
@app.get('/s/{token}/qr')
async def qr(token:str):
    u=get_user_by_subscription_token(token)
    if not u:return Response(status_code=404)
    image=qrcode.make(subscription_url(u['user_id']));buf=io.BytesIO();image.save(buf,format='PNG');return Response(buf.getvalue(),media_type='image/png',headers=NO_CACHE)
@app.get('/admin/login/{token}')
async def admin_magic_login(token:str):
    if not ADMIN_WEB_TOKEN or not secrets.compare_digest(token,ADMIN_WEB_TOKEN):return html_response(admin_login_page('Ссылка входа недействительна'),403)
    r=RedirectResponse('/admin',status_code=303);r.set_cookie('fvpn_admin',ADMIN_SESSION,max_age=30*86400,httponly=True,secure=True,samesite='strict',path='/');return r
@app.get('/admin/login')
async def admin_login_get(request:Request):return RedirectResponse('/admin',status_code=303) if admin_authed(request) else html_response(admin_login_page())
@app.post('/admin/login')
async def admin_login_post(request:Request):
    f=parse_qs((await request.body()).decode('utf-8','ignore'));token=(f.get('token') or [''])[0]
    if not ADMIN_WEB_TOKEN or not secrets.compare_digest(token,ADMIN_WEB_TOKEN):return html_response(admin_login_page('Неверный секретный ключ'),403)
    r=RedirectResponse('/admin',status_code=303);r.set_cookie('fvpn_admin',ADMIN_SESSION,max_age=30*86400,httponly=True,secure=True,samesite='strict',path='/');return r
@app.get('/admin/logout')
async def admin_logout():
    r=RedirectResponse('/admin/login',status_code=303);r.delete_cookie('fvpn_admin',path='/');return r
@app.get('/admin')
async def admin(request:Request,q:str='',filter:str='all'):
    if not admin_authed(request):return RedirectResponse('/admin/login',status_code=303)
    if filter not in {'all','active','expired','blocked'}:filter='all'
    return html_response(admin_dashboard(q.strip()[:80],filter))
@app.get('/admin/user/{user_id}')
async def admin_user(request:Request,user_id:int):
    if not admin_authed(request):return RedirectResponse('/admin/login',status_code=303)
    return html_response(admin_user_page(user_id))
@app.post('/admin/action')
async def admin_action(request:Request):
    if not admin_authed(request):return RedirectResponse('/admin/login',status_code=303)
    f=parse_qs((await request.body()).decode('utf-8','ignore'));csrf=(f.get('csrf') or [''])[0]
    if not ADMIN_CSRF or not secrets.compare_digest(csrf,ADMIN_CSRF):return html_response(admin_shell('Ошибка','<div class="panel"><h1 class="admin-title">Неверный CSRF-токен</h1></div>'),403)
    action=(f.get('action') or [''])[0];u=None
    if f.get('user_id'):
        try:u=get_user(int(f['user_id'][0]))
        except (ValueError,TypeError):u=None
    elif f.get('target'):u=resolve_target(f['target'][0].strip())
    if not u:return html_response(admin_shell('Пользователь не найден','<div class="panel"><h1 class="admin-title">Пользователь не найден</h1><div class="actions"><a class="btn tonal" href="/admin">Назад</a></div></div>'),404)
    uid=int(u['user_id'])
    if action.startswith('grant:'):
        code=action.split(':',1)[1]
        if code not in TARIFFS:return html_response(admin_shell('Ошибка','<div class="panel">Неизвестный тариф</div>'),400)
        exp=grant_subscription(uid,code);log_action(0,'web_admin_grant','user',uid,f'{code}; {exp.isoformat()}')
    elif action=='block':set_user_blocked(uid,True);log_action(0,'web_admin_block','user',uid,'')
    elif action=='unblock':set_user_blocked(uid,False);log_action(0,'web_admin_unblock','user',uid,'')
    elif action=='rotate':
        c=db()
        try:c.execute('UPDATE users SET subscription_token=? WHERE user_id=?',(secrets.token_urlsafe(32),uid));c.commit()
        finally:c.close()
        log_action(0,'web_admin_rotate_link','user',uid,'')
    else:return html_response(admin_shell('Ошибка','<div class="panel">Неизвестное действие</div>'),400)
    return RedirectResponse(f'/admin/user/{uid}',status_code=303)
