import html
import os
import re

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Message, PreCheckoutQuery, WebAppInfo

from core import ADMIN_ID, BASE_URL, BOT_TOKEN, PAYMENT_CURRENCY, PAYMENT_PROVIDER_TOKEN, PAYMENTS_ENABLED, TARIFFS, delete_pending_payment_contact, ensure_cabinet_token, fmt_dt, fulfill_payment, get_pending_payment_contact, get_user, grant_subscription, legal_documents_available, log_action, parse_payload, payment_payload, paymaster_provider_data, resolve_target, save_pending_payment_contact, set_user_blocked, set_user_contact, subscription_active, subscription_url, upsert_user

bot=Bot(BOT_TOKEN or '1:TEST');dp=Dispatcher();router=Router();dp.include_router(router)
pending_email_tariffs: dict[int, str] = {}
ADMIN_WEB_TOKEN=os.environ.get('ADMIN_WEB_TOKEN','').strip()
def ik(rows):return InlineKeyboardMarkup(inline_keyboard=rows)
def admin_web_url():return f'{BASE_URL}/admin/login/{ADMIN_WEB_TOKEN}' if ADMIN_WEB_TOKEN else f'{BASE_URL}/admin/login'
def menu(uid):
    cabinet=ensure_cabinet_token(uid);rows=[[InlineKeyboardButton(text='✨ Открыть FatherVPN',web_app=WebAppInfo(url=f'{BASE_URL}/miniapp'))],[InlineKeyboardButton(text='🚀 Купить VPN',callback_data='buy')],[InlineKeyboardButton(text='👤 Моя подписка',callback_data='profile')],[InlineKeyboardButton(text='🌐 Личный кабинет',url=f'{BASE_URL}/cabinet/{cabinet}')],[InlineKeyboardButton(text='📖 Инструкция',callback_data='help'),InlineKeyboardButton(text='🆘 Поддержка',url='https://t.me/Father_vpn_support')],[InlineKeyboardButton(text='ℹ️ Информация и документы',callback_data='info')]]
    if int(uid)==ADMIN_ID:rows.append([InlineKeyboardButton(text='🛠 Веб-админка',url=admin_web_url()),InlineKeyboardButton(text='⚙️ Команды',callback_data='admin')])
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
    u=m.from_user;upsert_user(u.id,u.username or '',u.first_name or '');ensure_cabinet_token(u.id);await m.answer('☁️ <b>FatherVPN</b>\nОдна подписка — одна персональная ссылка. После оплаты ссылка и QR-код появляются автоматически.',reply_markup=menu(u.id),parse_mode='HTML')
@router.callback_query(F.data=='menu')
async def cb_menu(q:CallbackQuery):await q.message.edit_text('☁️ <b>FatherVPN</b>\nГлавное меню',reply_markup=menu(q.from_user.id),parse_mode='HTML');await q.answer()
@router.callback_query(F.data=='buy')
async def cb_buy(q:CallbackQuery):await q.message.edit_text('🚀 <b>Выберите тариф</b>\nПосле успешной оплаты доступ активируется автоматически.',reply_markup=plans(),parse_mode='HTML');await q.answer()
@router.callback_query(F.data.startswith('tariff:'))
async def cb_tariff(q:CallbackQuery):
    code=q.data.split(':',1)[1];t=TARIFFS.get(code)
    if not t:return await q.answer('Тариф не найден',show_alert=True)
    rows=[[InlineKeyboardButton(text='💳 Оплатить TEST',callback_data=f'pay:{code}')]] if t['price'] and PAYMENTS_ENABLED else [[InlineKeyboardButton(text='🆘 Получить через поддержку',url='https://t.me/Father_vpn_support')]];rows.append([InlineKeyboardButton(text='⬅️ Назад',callback_data='buy')]);await q.message.edit_text(f"{t['emoji']} <b>{t['name']}</b>\n💰 {t['price']} ₽\n📅 {t['days']} дней\n\nПосле оплаты персональная ссылка и QR-код появятся сразу.",reply_markup=ik(rows),parse_mode='HTML');await q.answer()
async def send_invoice_for_user(user_id: int, code: str, contact_method: str, contact_value: str):
    if not PAYMENTS_ENABLED or not PAYMENT_PROVIDER_TOKEN:
        return False, "Оплата временно недоступна. Напишите в поддержку."
    tariff = TARIFFS.get(code)
    if not tariff or not tariff["price"]:
        return False, "Этот тариф выдаёт администратор."
    if contact_method not in {"telegram", "email"} or not contact_value:
        return False, "Выберите контакт для связи перед оплатой."
    if contact_method == "email" and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", contact_value.strip()):
        return False, "Проверьте адрес электронной почты."

    user = get_user(user_id)
    if user and user["blocked"]:
        return False, "Учётная запись заблокирована."
    if not user:
        upsert_user(user_id)
    set_user_contact(user_id, contact_method, contact_value)
    payload = payment_payload(user_id, code)
    uid, tariff_code, nonce = parse_payload(payload)
    save_pending_payment_contact(payload, user_id, contact_method, contact_value)
    try:
        await bot.send_invoice(
            chat_id=user_id,
            title=f"FatherVPN · {tariff['name']}",
            description="Персональная подписка FatherVPN. Доступ активируется после успешной оплаты.",
            payload=payload,
            provider_token=PAYMENT_PROVIDER_TOKEN,
            currency=PAYMENT_CURRENCY,
            prices=[LabeledPrice(label=f"FatherVPN · {tariff['name']}", amount=tariff["price"] * 100)],
            provider_data=paymaster_provider_data(uid, tariff_code, nonce),
            start_parameter=f"fathervpn-{code}",
        )
    except Exception as exc:
        delete_pending_payment_contact(payload)
        print("invoice error:", repr(exc))
        return False, "Не удалось создать счёт. Попробуйте ещё раз или обратитесь в поддержку."
    try:
        log_action(user_id, "invoice_created", "user", user_id, f"{code}; contact={contact_method}")
    except Exception as exc:
        print("invoice audit log error:", repr(exc))
    return True, None


@router.callback_query(F.data.startswith('pay:'))
async def cb_pay(q: CallbackQuery):
    code = q.data.split(':', 1)[1]
    tariff = TARIFFS.get(code)
    if not tariff or not tariff["price"] or not PAYMENTS_ENABLED or not PAYMENT_PROVIDER_TOKEN:
        return await q.answer('Оплата временно недоступна', show_alert=True)
    user = get_user(q.from_user.id)
    if user and user['blocked']:
        return await q.answer('Учётная запись заблокирована', show_alert=True)
    await q.message.edit_text(
        f"{tariff['emoji']} <b>{tariff['name']}</b>\n\n"
        "Перед оплатой выберите контакт для связи по заказу, возврату или спорному платежу. "
        "Контакт будет сохранён вместе с данными заказа.\n\n"
        "Можно указать Telegram username или адрес электронной почты.",
        reply_markup=ik([
            [InlineKeyboardButton(text='Telegram username', callback_data=f'contactmethod:telegram:{code}')],
            [InlineKeyboardButton(text='Email', callback_data=f'contactmethod:email:{code}')],
            [InlineKeyboardButton(text='⬅️ Назад', callback_data=f'tariff:{code}')],
        ]),
        parse_mode='HTML',
    )
    await q.answer()


@router.callback_query(F.data.startswith('contactmethod:'))
async def cb_contact_method(q: CallbackQuery):
    _, method, code = q.data.split(':', 2)
    tariff = TARIFFS.get(code)
    if method not in {'telegram', 'email'} or not tariff or not tariff['price']:
        return await q.answer('Не удалось определить способ связи или тариф', show_alert=True)
    if not PAYMENTS_ENABLED or not PAYMENT_PROVIDER_TOKEN:
        return await q.answer('Оплата временно недоступна', show_alert=True)
    user = get_user(q.from_user.id)
    if user and user['blocked']:
        return await q.answer('Учётная запись заблокирована', show_alert=True)

    if method == 'email':
        pending_email_tariffs[q.from_user.id] = code
        await q.message.answer(
            'Отправьте email для связи по этому заказу. Адрес будет сохранён вместе с данными платежа и использован для вопросов по оплате, возврату или спорной операции.\n\n'
            'Чтобы отменить, отправьте /cancel.',
            reply_markup=ForceReply(input_field_placeholder='name@example.com', selective=True),
        )
        await q.answer()
        return

    if not q.from_user.username:
        return await q.answer('У аккаунта нет Telegram username. Выберите Email для связи.', show_alert=True)
    contact_value = f"@{q.from_user.username}"
    ok, error = await send_invoice_for_user(q.from_user.id, code, 'telegram', contact_value)
    if ok:
        await q.answer('Счёт отправлен')
    else:
        await q.answer(error or 'Не удалось создать счёт', show_alert=True)


@router.pre_checkout_query()
async def checkout(p:PreCheckoutQuery):
    parsed=parse_payload(p.invoice_payload)
    if not parsed:return await p.answer(ok=False,error_message='Некорректный заказ')
    uid,code,_=parsed;t=TARIFFS[code];user=get_user(p.from_user.id)
    if uid!=p.from_user.id:return await p.answer(ok=False,error_message='Счёт создан для другого пользователя')
    if not get_pending_payment_contact(p.invoice_payload, uid):return await p.answer(ok=False,error_message='Не найден контакт для связи по заказу. Создайте новый счёт.')
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
    lines = [
        'ℹ️ <b>Информация о FatherVPN</b>',
        '',
        'Оператор: <b>Панов Евгений Ринатович</b>, физическое лицо без статуса ИП.',
        'Поддержка и претензии: <a href="https://t.me/Father_vpn_support">@Father_vpn_support</a>.',
        'Для связи по заказу выберите Telegram username или email перед оплатой.',
    ]
    if legal_documents_available():
        lines.extend([
            '',
            f'Политика конфиденциальности: <a href="{BASE_URL}/privacy">открыть</a>',
            f'Пользовательское соглашение: <a href="{BASE_URL}/terms">открыть</a>',
        ])
    else:
        lines.extend([
            '',
            'Юридические документы пока не опубликованы: проверяются обязательные реквизиты и условия обработки данных.',
        ])
    return '\n'.join(lines)


def info_keyboard():
    rows = []
    if legal_documents_available():
        rows.extend([
            [InlineKeyboardButton(text='🔐 Политика конфиденциальности', url=f'{BASE_URL}/privacy')],
            [InlineKeyboardButton(text='📄 Пользовательское соглашение', url=f'{BASE_URL}/terms')],
        ])
    rows.append([InlineKeyboardButton(text='🆘 Поддержка', url='https://t.me/Father_vpn_support')])
    rows.append([InlineKeyboardButton(text='⬅️ Главное меню', callback_data='menu')])
    return ik(rows)


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
    await q.message.edit_text('🛠 <b>Администрирование FatherVPN</b>\n\nВ веб-панели есть поиск пользователей, статистика, платежи, выдача тарифов, блокировки и смена персональной ссылки.\n\nКоманды тоже работают:\n<code>/grant ID 1d|7d|1m|3m|6m|12m</code>\n<code>/block ID</code>\n<code>/unblock ID</code>',reply_markup=ik([[InlineKeyboardButton(text='🛠 Открыть веб-админку',url=admin_web_url())],[InlineKeyboardButton(text='⬅️ Назад',callback_data='menu')]]),parse_mode='HTML');await q.answer()
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


@router.message(Command('cancel'))
async def cancel_email(m: Message):
    if m.from_user and pending_email_tariffs.pop(m.from_user.id, None):
        await m.answer('Ввод email отменён. Счёт не создан.')
    else:
        await m.answer('Нет ожидающего ввода email.')


@router.message(F.text)
async def handle_contact_email(m: Message):
    if not m.from_user or not m.text:
        return
    user_id = m.from_user.id
    code = pending_email_tariffs.get(user_id)
    if not code:
        return
    email_value = m.text.strip()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email_value):
        await m.answer('Не удалось распознать email. Проверьте адрес и отправьте его ещё раз, либо /cancel для отмены.')
        return
    pending_email_tariffs.pop(user_id, None)
    ok, error = await send_invoice_for_user(user_id, code, 'email', email_value)
    if not ok:
        await m.answer(error or 'Не удалось создать счёт. Попробуйте позже.')
