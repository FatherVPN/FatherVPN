import io
import qrcode
from fastapi import FastAPI,Request
from fastapi.responses import HTMLResponse,PlainTextResponse,Response
from core import INDEX_FILE,BLOCKED_SUBSCRIPTION,active_servers,esc,fmt_dt,get_user_by_cabinet_token,get_user_by_subscription_token,parse_dt,subscription_active,subscription_url,utc_now
app=FastAPI(title='FatherVPN',version='6.0')
def browser(r):
    a=r.headers.get('accept','').lower();u=r.headers.get('user-agent','').lower()
    return 'text/html' in a or any(x in u for x in ('mozilla/','chrome/','safari/','firefox/','edg/'))
def panel(u):
    active=subscription_active(u);e=parse_dt(u['expires_at']);days=max(0,int((e-utc_now()).total_seconds()//86400)) if e and e>utc_now() else 0;url=subscription_url(u['user_id']);state='Активна' if active else 'Неактивна'
    return f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>FatherVPN</title><style>body{{margin:0;background:#fdf8ff;color:#1d1b20;font:16px system-ui}}main{{max-width:850px;margin:auto;padding:28px}}.card{{background:#f3edf7;border-radius:28px;padding:28px;margin:14px 0}}h1{{font-size:48px}}.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}.stat{{background:#ece6f0;border-radius:18px;padding:16px}}.connect{{display:flex;gap:28px;align-items:center}}img{{width:210px;height:210px;background:white;padding:12px;border-radius:22px}}code{{display:block;word-break:break-all;background:#ece6f0;padding:14px;border-radius:14px}}button{{border:0;border-radius:99px;padding:14px 22px;background:#6750a4;color:white;font-weight:700}}@media(max-width:650px){{.grid{{grid-template-columns:1fr}}.connect{{display:block}}}}</style></head><body><main><div class="card"><b>{esc(state)}</b><h1>Моя подписка</h1><p>Одна ссылка для подключения FatherVPN.</p></div><div class="grid"><div class="stat">Тариф<br><b>{esc(u['tariff'] or '—')}</b></div><div class="stat">До<br><b>{esc(fmt_dt(u['expires_at']))}</b></div><div class="stat">Осталось<br><b>{days} дн.</b></div></div><div class="card connect"><img src="/s/{esc(u['subscription_token'])}/qr"><div><h2>Подключить VPN</h2><p>Отсканируйте QR или скопируйте ссылку.</p><code id="u">{esc(url)}</code><br><button onclick="navigator.clipboard.writeText(document.getElementById('u').textContent)">Скопировать</button></div></div></main></body></html>'''
@app.get('/')
async def home():return HTMLResponse(INDEX_FILE.read_text(encoding='utf-8'))
@app.get('/health')
async def health():return {'ok':bool(active_servers()),'version':'6.0'}
@app.get('/cabinet/{token}')
async def cabinet(token:str):
    u=get_user_by_cabinet_token(token);return HTMLResponse(panel(u)) if u else HTMLResponse('Not found',404)
@app.get('/s/{token}')
async def smart(token:str,request:Request):
    u=get_user_by_subscription_token(token)
    if not u:return HTMLResponse('Not found',404) if browser(request) else PlainTextResponse(BLOCKED_SUBSCRIPTION)
    if browser(request):return HTMLResponse(panel(u),headers={'Cache-Control':'no-store'})
    if not subscription_active(u):return PlainTextResponse(BLOCKED_SUBSCRIPTION)
    return PlainTextResponse(active_servers(),headers={'Cache-Control':'no-store'})
@app.get('/s/{token}/qr')
async def qr(token:str):
    u=get_user_by_subscription_token(token)
    if not u:return Response(status_code=404)
    image=qrcode.make(subscription_url(u['user_id']));buf=io.BytesIO();image.save(buf,format='PNG');return Response(buf.getvalue(),media_type='image/png')
