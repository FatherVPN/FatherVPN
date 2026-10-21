import html

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Message, PreCheckoutQuery

from core import (
    ADMIN_ID,
    BASE_URL,
    BOT_TOKEN,
    MAX_DEVICES,
    PAYMENT_CURRENCY,
    PAYMENT_PROVIDER_TOKEN,
    PAYMENTS_ENABLED,
    TARIFFS,
    create_device,
    delete_device,
    ensure_cabinet_token,
    fmt_dt,
    fulfill_payment,
    get_device,
    get_user,
    grant_subscription,
    list_devices,
    log_action,
    parse_payload,
    payment_payload,
    paymaster_provider_data,
    resolve_target,
    set_device_blocked,
    set_user_blocked,
    subscription_active,
    upsert_user,
)

bot = Bot(BOT_TOKEN or "1:TEST")
dp = Dispatcher()
router = Router()
dp.include_router(router)


def ik(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


def main_menu(user_id):
    cabinet = ensure_cabinet_token(user_id)
    rows = [
        [InlineKeyboardButton(text="🚀 Купить VPN", callback_data="buy")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile"), InlineKeyboardButton(text="📱 Устройства", callback_data="devices")],
        [InlineKeyboardButton(text="🌐 Личный кабинет", url=f"{BASE_URL}/cabinet/{cabinet}")],
        [InlineKeyboardButton(text="📖 Инструкция", callback_data="help"), InlineKeyboardButton(text="🆘 Поддержка", url="https://t.me/Father_vpn_support")],
    ]
    if int(user_id) == ADMIN_ID:
        rows.append([InlineKeyboardButton(text="🛠 Админ-панель", callback_data="admin")])
    return ik(rows)


def tariffs_keyboard():
    rows = []
    for code, t in TARIFFS.items():
        price = f"{t['price']} ₽" if t["price"] else "через администратора"
        rows.append([InlineKeyboardButton(text=f"{t['emoji']} {t['name']} — {price}", callback_data=f"tariff:{code}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu")])
    return ik(rows)


def devices_keyboard(user_id):
    rows = []
    devices = list_devices(user_id)
    for d in devices:
        icon = "⛔" if d["blocked"] else "📱"
        rows.append([InlineKeyboardButton(text=f"{icon} {d['name']}", callback_data=f"dev:{d['id']}")])
    if len(devices) < MAX_DEVICES:
        rows.append([InlineKeyboardButton(text="➕ Добавить устройство", callback_data="device:add")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu")])
    return ik(rows)


def device_view(d):
    panel = f"{BASE_URL}/d/{d['token']}"
    toggle = "on" if d["blocked"] else "off"
    toggle_text = "✅ Включить" if d["blocked"] else "⛔ Отключить"
    text = (
        f"📱 <b>{html.escape(d['name'])}</b>\n"
        f"Статус: {'⛔ Отключено' if d['blocked'] else '✅ Активно'}\n"
        f"Последнее обновление: {html.escape(fmt_dt(d['last_seen']))}\n"
        f"Запросов: {d['request_count']}\n\n"
        f"🌐 <b>Панель подписки:</b>\n<code>{html.escape(panel)}</code>"
    )
    keyboard = ik([
        [InlineKeyboardButton(text="🌐 Открыть панель", url=panel)],
        [InlineKeyboardButton(text=toggle_text, callback_data=f"devtoggle:{toggle}:{d['id']}")],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"devdel:{d['id']}")],
        [InlineKeyboardButton(text="⬅️ К устройствам", callback_data="devices")],
    ])
    return text, keyboard


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject):
    u = message.from_user
    upsert_user(u.id, u.username or "", u.first_name or "")
    if (command.args or "").strip().lower() == "cabinet":
        token = ensure_cabinet_token(u.id)
        await message.answer(
            "🌐 <b>Личный кабинет FatherVPN</b>\nЗдесь можно проверить подписку и управлять устройствами.",
            reply_markup=ik([[InlineKeyboardButton(text="Открыть кабинет", url=f"{BASE_URL}/cabinet/{token}")]]),
            parse_mode="HTML",
        )
        return
    await message.answer(
        "⛅️ <b>FatherVPN</b>\nНадёжный VPN с персональными ссылками для каждого устройства.",
        reply_markup=main_menu(u.id),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu")
async def cb_menu(q: CallbackQuery):
    await q.message.edit_text("⛅️ <b>FatherVPN</b>\nГлавное меню", reply_markup=main_menu(q.from_user.id), parse_mode="HTML")
    await q.answer()


@router.callback_query(F.data == "buy")
async def cb_buy(q: CallbackQuery):
    await q.message.edit_text(f"🚀 <b>Выбери тариф</b>\nДо {MAX_DEVICES} устройств на одной подписке.", reply_markup=tariffs_keyboard(), parse_mode="HTML")
    await q.answer()


@router.callback_query(F.data.startswith("tariff:"))
async def cb_tariff(q: CallbackQuery):
    code = q.data.split(":", 1)[1]
    t = TARIFFS.get(code)
    if not t:
        return await q.answer("Тариф не найден", show_alert=True)
    rows = []
    if t["price"] > 0 and PAYMENTS_ENABLED:
        rows.append([InlineKeyboardButton(text="💳 Оплатить TEST", callback_data=f"pay:{code}")])
    else:
        rows.append([InlineKeyboardButton(text="🆘 Получить через поддержку", url="https://t.me/Father_vpn_support")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="buy")])
    await q.message.edit_text(
        f"{t['emoji']} <b>{t['name']}</b>\n💰 {t['price']} ₽\n📅 {t['days']} дней\n📱 до {MAX_DEVICES} устройств",
        reply_markup=ik(rows), parse_mode="HTML"
    )
    await q.answer()


@router.callback_query(F.data.startswith("pay:"))
async def cb_pay(q: CallbackQuery):
    code = q.data.split(":", 1)[1]
    t = TARIFFS.get(code)
    if not PAYMENTS_ENABLED or not PAYMENT_PROVIDER_TOKEN:
        return await q.answer("Оплата временно недоступна", show_alert=True)
    user = get_user(q.from_user.id)
    if user and user["blocked"]:
        return await q.answer("Учётная запись заблокирована", show_alert=True)
    if not t or t["price"] <= 0:
        return await q.answer("Этот тариф выдаёт администратор", show_alert=True)
    payload = payment_payload(q.from_user.id, code)
    uid, tariff_code, nonce = parse_payload(payload)
    try:
        await bot.send_invoice(
            chat_id=q.from_user.id,
            title=f"FatherVPN · {t['name']}",
            description=f"Тестовая оплата FatherVPN на {t['days']} дней, до {MAX_DEVICES} устройств.",
            payload=payload,
            provider_token=PAYMENT_PROVIDER_TOKEN,
            currency=PAYMENT_CURRENCY,
            prices=[LabeledPrice(label=f"FatherVPN · {t['name']}", amount=t["price"] * 100)],
            provider_data=paymaster_provider_data(uid, tariff_code, nonce),
            start_parameter=f"fathervpn-{code}",
        )
        log_action(q.from_user.id, "invoice_created", "user", q.from_user.id, code)
        await q.answer("Счёт отправлен")
    except Exception as e:
        print("invoice error:", repr(e))
        await q.answer(f"Ошибка счёта: {type(e).__name__}", show_alert=True)


@router.pre_checkout_query()
async def pre_checkout(pcq: PreCheckoutQuery):
    parsed = parse_payload(pcq.invoice_payload)
    if not parsed:
        return await pcq.answer(ok=False, error_message="Некорректный заказ")
    uid, code, _ = parsed
    t = TARIFFS[code]
    user = get_user(pcq.from_user.id)
    if uid != pcq.from_user.id:
        return await pcq.answer(ok=False, error_message="Счёт создан для другого пользователя")
    if user and user["blocked"]:
        return await pcq.answer(ok=False, error_message="Учётная запись заблокирована")
    if pcq.currency != PAYMENT_CURRENCY or pcq.total_amount != t["price"] * 100:
        return await pcq.answer(ok=False, error_message="Сумма или валюта счёта изменилась")
    await pcq.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message):
    sp = message.successful_payment
    parsed = parse_payload(sp.invoice_payload)
    if not parsed:
        return
    uid, code, _ = parsed
    if uid != message.from_user.id:
        return
    t = TARIFFS[code]
    if sp.currency != PAYMENT_CURRENCY or sp.total_amount != t["price"] * 100:
        return
    expires, applied = fulfill_payment(uid, code, sp)
    if not applied:
        return
    log_action(uid, "payment_success", "user", uid, f"{code}; {sp.telegram_payment_charge_id}")
    await message.answer(
        f"✅ Оплата подтверждена. Подписка активна до <b>{html.escape(fmt_dt(expires.isoformat()))}</b>.",
        parse_mode="HTML", reply_markup=main_menu(uid)
    )


@router.callback_query(F.data == "profile")
async def cb_profile(q: CallbackQuery):
    user = get_user(q.from_user.id)
    status = "✅ Активна" if subscription_active(user) else ("⛔ Заблокирована" if user and user["blocked"] else "⚪ Неактивна")
    await q.message.edit_text(
        f"👤 <b>Профиль</b>\nСтатус: {status}\nТариф: <b>{html.escape(user['tariff'] or '—')}</b>\nДо: <b>{html.escape(fmt_dt(user['expires_at']))}</b>\nУстройств: <b>{len(list_devices(q.from_user.id))}/{MAX_DEVICES}</b>",
        reply_markup=ik([[InlineKeyboardButton(text="🌐 Личный кабинет", url=f"{BASE_URL}/cabinet/{ensure_cabinet_token(q.from_user.id)}")], [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu")]]),
        parse_mode="HTML",
    )
    await q.answer()


@router.callback_query(F.data == "devices")
async def cb_devices(q: CallbackQuery):
    if not subscription_active(get_user(q.from_user.id)):
        return await q.answer("Нужна активная подписка", show_alert=True)
    await q.message.edit_text("📱 <b>Мои устройства</b>", reply_markup=devices_keyboard(q.from_user.id), parse_mode="HTML")
    await q.answer()


@router.callback_query(F.data == "device:add")
async def cb_device_add(q: CallbackQuery):
    if not subscription_active(get_user(q.from_user.id)):
        return await q.answer("Нужна активная подписка", show_alert=True)
    d = create_device(q.from_user.id)
    if not d:
        return await q.answer(f"Лимит: {MAX_DEVICES}", show_alert=True)
    await q.message.edit_text("📱 <b>Мои устройства</b>", reply_markup=devices_keyboard(q.from_user.id), parse_mode="HTML")
    await q.answer("Устройство добавлено")


@router.callback_query(F.data.regexp(r"^dev:\d+$"))
async def cb_device(q: CallbackQuery):
    did = int(q.data.split(":")[1])
    d = get_device(did)
    if not d or d["user_id"] != q.from_user.id:
        return await q.answer("Устройство не найдено", show_alert=True)
    text, keyboard = device_view(d)
    await q.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await q.answer()


@router.callback_query(F.data.startswith("devtoggle:"))
async def cb_dev_toggle(q: CallbackQuery):
    _, action, did_s = q.data.split(":")
    did = int(did_s)
    d = get_device(did)
    if not d or d["user_id"] != q.from_user.id:
        return await q.answer("Устройство не найдено", show_alert=True)
    set_device_blocked(did, action == "off")
    text, keyboard = device_view(get_device(did))
    await q.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await q.answer("Готово")


@router.callback_query(F.data.startswith("devdel:"))
async def cb_dev_delete(q: CallbackQuery):
    did = int(q.data.split(":")[1])
    d = get_device(did)
    if not d or d["user_id"] != q.from_user.id:
        return await q.answer("Устройство не найдено", show_alert=True)
    delete_device(did)
    await q.message.edit_text("📱 <b>Мои устройства</b>", reply_markup=devices_keyboard(q.from_user.id), parse_mode="HTML")
    await q.answer("Ссылка устройства аннулирована")


@router.callback_query(F.data == "help")
async def cb_help(q: CallbackQuery):
    await q.message.edit_text(
        "📖 <b>Как подключиться</b>\n1. Открой «Устройства».\n2. Открой панель нужного устройства.\n3. Нажми «Скопировать ссылку».\n4. Импортируй RAW-ссылку в VPN-клиент.\n\n/d/... — панель, /d/.../raw — подписка для клиента.",
        reply_markup=ik([[InlineKeyboardButton(text="⬅️ Назад", callback_data="menu")]]), parse_mode="HTML"
    )
    await q.answer()


@router.callback_query(F.data == "admin")
async def cb_admin(q: CallbackQuery):
    if q.from_user.id != ADMIN_ID:
        return await q.answer("Нет доступа", show_alert=True)
    await q.message.edit_text(
        "🛠 <b>Админ-панель</b>\n"
        "<code>/grant ID 1d|7d|1m|3m|6m|12m</code>\n"
        "<code>/block ID</code> / <code>/unblock ID</code>\n"
        "<code>/block_device ID</code> / <code>/unblock_device ID</code>\n"
        "<code>/users</code>",
        reply_markup=ik([[InlineKeyboardButton(text="⬅️ Назад", callback_data="menu")]]), parse_mode="HTML"
    )
    await q.answer()


def admin_only(message):
    return bool(message.from_user and message.from_user.id == ADMIN_ID)


@router.message(Command("grant"))
async def cmd_grant(message: Message, command: CommandObject):
    if not admin_only(message): return
    args = (command.args or "").split()
    if len(args) != 2 or args[1] not in TARIFFS:
        return await message.answer("Формат: /grant USER_ID 1d|7d|1m|3m|6m|12m")
    target = resolve_target(args[0])
    if not target:
        try:
            uid = int(args[0]); upsert_user(uid); target = get_user(uid)
        except ValueError:
            return await message.answer("Пользователь не найден")
    exp = grant_subscription(target["user_id"], args[1])
    await message.answer(f"✅ Выдано: {TARIFFS[args[1]]['name']}\nДо: {fmt_dt(exp.isoformat())}")


@router.message(Command("block"))
async def cmd_block(message: Message, command: CommandObject):
    if not admin_only(message): return
    target = resolve_target((command.args or "").strip())
    if not target: return await message.answer("Пользователь не найден")
    set_user_blocked(target["user_id"], True); await message.answer("⛔ Пользователь заблокирован")


@router.message(Command("unblock"))
async def cmd_unblock(message: Message, command: CommandObject):
    if not admin_only(message): return
    target = resolve_target((command.args or "").strip())
    if not target: return await message.answer("Пользователь не найден")
    set_user_blocked(target["user_id"], False); await message.answer("✅ Пользователь разблокирован")


@router.message(Command("block_device"))
async def cmd_block_device(message: Message, command: CommandObject):
    if not admin_only(message): return
    try: did = int((command.args or "").strip())
    except ValueError: return await message.answer("Формат: /block_device DEVICE_ID")
    if not get_device(did): return await message.answer("Устройство не найдено")
    set_device_blocked(did, True); await message.answer("⛔ Устройство заблокировано")


@router.message(Command("unblock_device"))
async def cmd_unblock_device(message: Message, command: CommandObject):
    if not admin_only(message): return
    try: did = int((command.args or "").strip())
    except ValueError: return await message.answer("Формат: /unblock_device DEVICE_ID")
    if not get_device(did): return await message.answer("Устройство не найдено")
    set_device_blocked(did, False); await message.answer("✅ Устройство разблокировано")


@router.message(Command("users"))
async def cmd_users(message: Message):
    if not admin_only(message): return
    from core import db
    c = db()
    try: rows = c.execute("SELECT * FROM users ORDER BY created_at DESC LIMIT 30").fetchall()
    finally: c.close()
    text = ["👥 <b>Последние пользователи</b>"]
    for u in rows:
        text.append(f"<code>{u['user_id']}</code> @{html.escape(u['username'] or '—')} · {html.escape(u['tariff'] or '—')} · {'⛔' if u['blocked'] else '✅'}")
    await message.answer("\n".join(text), parse_mode="HTML")
