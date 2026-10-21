import asyncio
import html
import os

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Message, PreCheckoutQuery, WebAppInfo

from core import ADMIN_ID, BASE_URL, BOT_TOKEN, PAYMENT_CURRENCY, PAYMENT_PROVIDER_TOKEN, PAYMENTS_ENABLED, TARIFFS, consume_account_link, create_announcement, deactivate_announcement, ensure_cabinet_token, fmt_dt, fulfill_payment, get_user, grant_subscription, list_announcements, list_telegram_user_ids, log_action, parse_payload, payment_payload, paymaster_provider_data, resolve_target, set_user_blocked, subscription_active, subscription_url, upsert_user

bot=Bot(BOT_TOKEN or '1:TEST');dp=Dispatcher();router=Router();dp.include_router(router)
ADMIN_WEB_TOKEN=os.environ.get('ADMIN_WEB_TOKEN','').strip()
def ik(rows):return InlineKeyboardMarkup(inline_keyboard=rows)
def admin_web_url():return f'{BASE_URL}/admin/login/{ADMIN_WEB_TOKEN}' if ADMIN_WEB_TOKEN else f'{BASE_URL}/admin/login'
def has_paid_subscription(uid):
    user=get_user(uid)
    return bool(user and user['tariff'] and any(t['price']>0 and t['name']==user['tariff'] for t in TARIFFS.values()))

def menu(uid):
    cabinet=ensure_cabinet_token(uid)
    buy_label='🔄 Продлить VPN' if has_paid_subscription(uid) else '🚀 Купить VPN'
    rows=[
        [InlineKeyboardButton(text='✨ Открыть FatherVPN',web_app=WebAppInfo(url=f'{BASE_URL}/miniapp'))],
        [InlineKeyboardButton(text=buy_label,callback_data='buy'),InlineKeyboardButton(text='👤 Подписка',callback_data='profile')],
        [InlineKeyboardButton(text='📣 Объявления',callback_data='announcements'),InlineKeyboardButton(text='☰ Ещё',callback_data='more')],
    ]
    return ik(rows)
def plans():
    rows=[]
    for code,t in TARIFFS.items():
        price=f"{t['price']} ₽" if t['price'] else 'через администратора';rows.append([InlineKeyboardButton(text=f"{t['emoji']} {t['name']} — {price}",callback_data=f'tariff:{code}')])
    rows.append([InlineKeyboardButton(text='⬅️ Назад',callback_data='menu')]);return ik(rows)
def access(uid):
    url=subscription_url(uid);return f'🔗 <b>Ваша персональная ссылка:</b>\n<code>{html.escape(url)}</code>\n\nОткройте её в браузере — там будет QR-код и удобная панель. Эту же ссылку добавляйте в VPN-клиент.',ik([[InlineKeyboardButton(text='🌐 Открыть подписку и QR',url=url)],[InlineKeyboardButton(text='⬅️ В меню',callback_data='menu')]])
@router.message(CommandStart())
async def start(m:Message,command:CommandObject):
    u=m.from_user
    upsert_user(u.id,u.username or '',u.first_name or '')
    ensure_cabinet_token(u.id)
    payload=(command.args or '').strip()
    if payload.startswith('link_'):
        linked,email,error=consume_account_link(payload[5:],u.id,u.username or '',u.first_name or '')
        if linked:
            await m.answer(f'✅ <b>Telegram привязан!</b>\nАккаунт: <code>{html.escape(email)}</code>\n\nТеперь подписка и данные Telegram доступны в личном кабинете FatherVPN.',reply_markup=menu(u.id),parse_mode='HTML')
        else:
            await m.answer(f'⚠️ <b>Не удалось привязать Telegram</b>\n{html.escape(error)}',reply_markup=menu(u.id),parse_mode='HTML')
        return
    await m.answer('☁️ <b>FatherVPN</b>\nОдна подписка — одна персональная ссылка. После оплаты ссылка и QR-код появляются автоматически.',reply_markup=menu(u.id),parse_mode='HTML')
@router.callback_query(F.data=='menu')
async def cb_menu(q:CallbackQuery):await q.message.edit_text('☁️ <b>FatherVPN</b>\nГлавное меню',reply_markup=menu(q.from_user.id),parse_mode='HTML');await q.answer()
@router.callback_query(F.data=='more')
async def cb_more(q:CallbackQuery):
    rows=[
        [InlineKeyboardButton(text='👤 Аккаунт на сайте',url=f'{BASE_URL}/account')],
        [InlineKeyboardButton(text='📖 Инструкция',callback_data='help'),InlineKeyboardButton(text='🆘 Поддержка',url='https://t.me/Father_vpn_support')],
        [InlineKeyboardButton(text='ℹ️ Документы',callback_data='info')],
    ]
    if q.from_user.id==ADMIN_ID:
        rows.append([InlineKeyboardButton(text='🛠 Администрирование',callback_data='admin')])
    rows.append([InlineKeyboardButton(text='⬅️ Главное меню',callback_data='menu')])
    await q.message.edit_text('☰ <b>Ещё</b>\nАккаунт, помощь и настройки FatherVPN.',reply_markup=ik(rows),parse_mode='HTML')
    await q.answer()

@router.callback_query(F.data=='announcements')
async def cb_announcements(q:CallbackQuery):
    items=list_announcements(5)
    if not items:
        body='📣 <b>Объявления</b>\n\nПока новых объявлений нет. Когда появятся важные новости сервиса, они будут здесь.'
    else:
        parts=['📣 <b>Объявления FatherVPN</b>']
        for item in items:
            parts.append(f"\n<b>{html.escape(str(item['title']))}</b>\n{html.escape(str(item['body']))}\n<i>{html.escape(fmt_dt(item['created_at']))}</i>")
        body='\n'.join(parts)
    await q.message.edit_text(body,reply_markup=ik([[InlineKeyboardButton(text='⬅️ Главное меню',callback_data='menu')]]),parse_mode='HTML')
    await q.answer()

@router.callback_query(F.data=='buy')
async def cb_buy(q:CallbackQuery):await q.message.edit_text('🚀 <b>Выберите тариф</b>\nПосле успешной оплаты доступ активируется автоматически.',reply_markup=plans(),parse_mode='HTML');await q.answer()
@router.callback_query(F.data.startswith('tariff:'))
async def cb_tariff(q:CallbackQuery):
    code=q.data.split(':',1)[1];t=TARIFFS.get(code)
    if not t:return await q.answer('Тариф не найден',show_alert=True)
    rows=[[InlineKeyboardButton(text='💳 Оплатить TEST',callback_data=f'pay:{code}')]] if t['price'] and PAYMENTS_ENABLED else [[InlineKeyboardButton(text='🆘 Получить через поддержку',url='https://t.me/Father_vpn_support')]];rows.append([InlineKeyboardButton(text='⬅️ Назад',callback_data='buy')]);await q.message.edit_text(f"{t['emoji']} <b>{t['name']}</b>\n💰 {t['price']} ₽\n📅 {t['days']} дней\n\nПосле оплаты персональная ссылка и QR-код появятся сразу.",reply_markup=ik(rows),parse_mode='HTML');await q.answer()
@router.callback_query(F.data.startswith('pay:'))
async def cb_pay(q:CallbackQuery):
    code=q.data.split(':',1)[1];t=TARIFFS.get(code)
    if not t or not t['price'] or not PAYMENTS_ENABLED or not PAYMENT_PROVIDER_TOKEN:return await q.answer('Оплата временно недоступна',show_alert=True)
    user=get_user(q.from_user.id)
    if user and user['blocked']:return await q.answer('Учётная запись заблокирована',show_alert=True)
    payload=payment_payload(q.from_user.id,code);uid,tariff_code,nonce=parse_payload(payload)
    try:
        await bot.send_invoice(chat_id=q.from_user.id,title=f"FatherVPN · {t['name']}",description='Персональная подписка FatherVPN. Доступ активируется автоматически после успешной оплаты.',payload=payload,provider_token=PAYMENT_PROVIDER_TOKEN,currency=PAYMENT_CURRENCY,prices=[LabeledPrice(label=f"FatherVPN · {t['name']}",amount=t['price']*100)],provider_data=paymaster_provider_data(uid,tariff_code,nonce),start_parameter=f'fathervpn-{code}');log_action(q.from_user.id,'invoice_created','user',q.from_user.id,code);await q.answer('Счёт отправлен')
    except Exception as exc:print('invoice error:',repr(exc));await q.answer('Не удалось создать счёт. Проверьте настройки тестового провайдера.',show_alert=True)
@router.pre_checkout_query()
async def checkout(p:PreCheckoutQuery):
    parsed=parse_payload(p.invoice_payload)
    if not parsed:return await p.answer(ok=False,error_message='Некорректный заказ')
    uid,code,_=parsed;t=TARIFFS[code];user=get_user(p.from_user.id)
    if uid!=p.from_user.id:return await p.answer(ok=False,error_message='Счёт создан для другого пользователя')
    if user and user['blocked']:return await p.answer(ok=False,error_message='Учётная запись заблокирована')
    if p.currency!=PAYMENT_CURRENCY or p.total_amount!=t['price']*100:return await p.answer(ok=False,error_message='Сумма или валюта заказа изменилась')
    await p.answer(ok=True)
@router.message(F.successful_payment)
async def success(m:Message):
    sp=m.successful_payment;parsed=parse_payload(sp.invoice_payload)
    if not parsed:return
    uid,code,_=parsed
    if uid!=m.from_user.id:return
    t=TARIFFS[code]
    if sp.currency!=PAYMENT_CURRENCY or sp.total_amount!=t['price']*100:return
    exp,applied=fulfill_payment(uid,code,sp)
    if not applied:return
    log_action(uid,'payment_success','user',uid,f'{code}; {sp.telegram_payment_charge_id}');text,kb=access(uid);await m.answer(f'✅ <b>Оплата подтверждена</b>\nПодписка активна до <b>{html.escape(fmt_dt(exp.isoformat()))}</b>.\n\n{text}',reply_markup=kb,parse_mode='HTML')
@router.callback_query(F.data=='profile')
async def profile(q:CallbackQuery):
    u=get_user(q.from_user.id)
    if not u:return await q.answer('Профиль не найден',show_alert=True)
    status='✅ Активна' if subscription_active(u) else ('⛔ Заблокирована' if u['blocked'] else '⚪ Неактивна');text,kb=access(q.from_user.id);await q.message.edit_text(f"👤 <b>Моя подписка</b>\nСтатус: {status}\nТариф: <b>{html.escape(u['tariff'] or '—')}</b>\nДо: <b>{html.escape(fmt_dt(u['expires_at']))}</b>\n\n{text}",reply_markup=kb,parse_mode='HTML');await q.answer()
@router.callback_query(F.data=='help')
async def helpme(q:CallbackQuery):await q.message.edit_text('📖 <b>Как подключиться</b>\n\n1. Купите подписку.\n2. Бот сразу выдаст персональную ссылку.\n3. Откройте её в браузере — увидите QR-код и статус подписки.\n4. Добавьте эту же ссылку в VPN-клиент или отсканируйте QR.\n\nОтдельного RAW-адреса в интерфейсе нет.',reply_markup=ik([[InlineKeyboardButton(text='⬅️ Назад',callback_data='menu')]]),parse_mode='HTML');await q.answer()
def info_text():
    return (
        'ℹ️ <b>Информация о FatherVPN</b>\n\n'
        'FatherVPN предоставляет VPN-подписку, персональную ссылку и QR-код. '
        'Перед использованием ознакомьтесь с документами ниже.\n\n'
        'По вопросам обработки данных, подписки и работы сервиса: '
        '<a href="https://t.me/Father_vpn_support">@Father_vpn_support</a>.'
    )
def info_keyboard():
    return ik([
        [InlineKeyboardButton(text='🔐 Политика конфиденциальности',url=f'{BASE_URL}/privacy')],
        [InlineKeyboardButton(text='📄 Пользовательское соглашение',url=f'{BASE_URL}/terms')],
        [InlineKeyboardButton(text='⬅️ Главное меню',callback_data='menu')],
    ])
@router.message(Command('info'))
async def info_command(m:Message):
    await m.answer(info_text(),reply_markup=info_keyboard(),parse_mode='HTML')
@router.callback_query(F.data=='info')
async def cb_info(q:CallbackQuery):
    await q.message.edit_text(info_text(),reply_markup=info_keyboard(),parse_mode='HTML')
    await q.answer()
@router.callback_query(F.data=='admin')
async def admin(q:CallbackQuery):
    if q.from_user.id!=ADMIN_ID:return await q.answer('Нет доступа',show_alert=True)
    await q.message.edit_text('🛠 <b>Администрирование FatherVPN</b>\n\nВ веб-панели есть поиск пользователей, статистика, платежи, выдача тарифов, блокировки и смена персональной ссылки.\n\nКоманды тоже работают:\n<code>/grant ID 1d|7d|1m|3m|6m|12m</code>\n<code>/block ID</code>\n<code>/unblock ID</code>\n<code>/announce Заголовок | Текст</code>\n<code>/announce_off ID</code>',reply_markup=ik([[InlineKeyboardButton(text='🛠 Открыть веб-админку',url=admin_web_url())],[InlineKeyboardButton(text='⬅️ Назад',callback_data='menu')]]),parse_mode='HTML');await q.answer()
async def _broadcast_announcement(title, body):
    text=f'📣 <b>Объявление FatherVPN</b>\n\n<b>{html.escape(title)}</b>\n\n{html.escape(body)}'
    sent=0
    failed=0
    for uid in list_telegram_user_ids():
        try:
            await bot.send_message(uid,text,parse_mode='HTML',disable_web_page_preview=True)
            sent+=1
        except Exception as exc:
            failed+=1
            if failed<=3:
                print('announcement delivery error:',repr(exc))
        await asyncio.sleep(0.05)
    print(f'announcement broadcast complete: sent={sent}, failed={failed}')

@router.message(Command('announce'))
async def announce_command(m:Message,command:CommandObject):
    if m.from_user.id!=ADMIN_ID:
        return
    raw=(command.args or '').strip()
    if '|' not in raw:
        return await m.answer('Формат: /announce Заголовок | Текст объявления')
    title,body=(part.strip() for part in raw.split('|',1))
    if not title or not body:
        return await m.answer('Нужны и заголовок, и текст.\nПример: /announce Плановые работы | Сегодня в 23:00 возможен перерыв.')
    try:
        announcement_id=create_announcement(title,body,m.from_user.id)
    except ValueError as exc:
        return await m.answer(html.escape(str(exc)))
    await m.answer(f'✅ Объявление #{announcement_id} опубликовано на сайте и в боте.\nНачинаю рассылку пользователям.\n\nДля снятия с публикации: <code>/announce_off {announcement_id}</code>',parse_mode='HTML')
    asyncio.create_task(_broadcast_announcement(title,body))

@router.message(Command('announce_off'))
async def announce_off_command(m:Message,command:CommandObject):
    if m.from_user.id!=ADMIN_ID:
        return
    try:
        announcement_id=int((command.args or '').strip())
    except ValueError:
        return await m.answer('Использование: /announce_off ID')
    if deactivate_announcement(announcement_id):
        await m.answer(f'✅ Объявление #{announcement_id} снято с публикации на сайте и в боте.')
    else:
        await m.answer('Активное объявление с таким ID не найдено.')

@router.message(Command('grant'))
async def grant(m:Message,command:CommandObject):
    if m.from_user.id!=ADMIN_ID:return
    p=(command.args or '').split()
    if len(p)!=2 or p[1] not in TARIFFS:return await m.answer('Использование: /grant ID 1d|7d|1m|3m|6m|12m')
    u=resolve_target(p[0])
    if not u:return await m.answer('Пользователь не найден')
    exp=grant_subscription(u['user_id'],p[1]);url=subscription_url(u['user_id']);log_action(m.from_user.id,'grant','user',u['user_id'],p[1]);await m.answer(f'✅ Выдано до {html.escape(fmt_dt(exp.isoformat()))}\n<code>{html.escape(url)}</code>',parse_mode='HTML')
    try:await bot.send_message(u['user_id'],f'🎁 <b>Подписка FatherVPN активирована</b>\nДо: {html.escape(fmt_dt(exp.isoformat()))}\n\n<code>{html.escape(url)}</code>',reply_markup=ik([[InlineKeyboardButton(text='🌐 Открыть подписку и QR',url=url)]]),parse_mode='HTML')
    except Exception as exc:print('grant notify error:',repr(exc))
@router.message(Command('block','unblock'))
async def block(m:Message,command:CommandObject):
    if m.from_user.id!=ADMIN_ID:return
    u=resolve_target((command.args or '').strip())
    if not u:return await m.answer('Пользователь не найден')
    b=m.text.split()[0].split('@')[0]=='/block';set_user_blocked(u['user_id'],b);log_action(m.from_user.id,'block' if b else 'unblock','user',u['user_id'],'');await m.answer('⛔ Заблокирован' if b else '✅ Разблокирован')
