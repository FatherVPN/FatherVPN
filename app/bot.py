import os

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, LabeledPrice, PreCheckoutQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db import save_user, activate_subscription, current_subscription
from app.vpn_provider import get_or_create_config, VPNProviderNotConfigured

router = Router()

STARS = int(os.getenv("SUBSCRIPTION_STARS", "100"))
DAYS = int(os.getenv("SUBSCRIPTION_DAYS", "30"))


def menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="Купить подписку ⭐", callback_data="buy")
    kb.button(text="Моя подписка", callback_data="status")
    kb.button(text="Получить конфигурацию", callback_data="config")
    kb.button(text="Поддержка", url="https://t.me/Father_vpn_support")
    kb.adjust(1)
    return kb.as_markup()


@router.message(CommandStart())
async def start(message: Message):
    save_user(message.from_user)
    await message.answer(
        f"FatherVPN\n\n"
        f"Подписка на {DAYS} дней.\n"
        f"Цена внутри Telegram: {STARS} ⭐ Stars.\n\n"
        f"Выберите действие:",
        reply_markup=menu(),
    )


@router.callback_query(F.data == "buy")
async def buy(call: CallbackQuery):
    await call.answer()
    await call.message.answer_invoice(
        title=f"FatherVPN — {DAYS} дней",
        description="VPN-подписка. Конфигурация станет доступна после подключения VPN-сервера.",
        payload=f"fathervpn:{call.from_user.id}:{DAYS}",
        currency="XTR",
        prices=[LabeledPrice(label=f"FatherVPN на {DAYS} дней", amount=STARS)],
        provider_token="",
    )


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message):
    p = message.successful_payment
    activate_subscription(message.from_user.id, p.telegram_payment_charge_id, DAYS)
    await message.answer(
        "Оплата подтверждена, подписка записана. "
        "Выдача VPN-конфигурации появится после настройки VPN-сервера.",
        reply_markup=menu(),
    )


@router.callback_query(F.data == "status")
async def status(call: CallbackQuery):
    await call.answer()
    sub = current_subscription(call.from_user.id)
    await call.message.answer(
        f"Подписка активна до: {sub['expires_at']} UTC"
        if sub
        else "Активной подписки нет.",
        reply_markup=menu(),
    )


@router.callback_query(F.data == "config")
async def config(call: CallbackQuery):
    await call.answer()
    if not current_subscription(call.from_user.id):
        await call.message.answer("Сначала оформи подписку.", reply_markup=menu())
        return
    try:
        cfg = await get_or_create_config(call.from_user.id)
        await call.message.answer_document(
            document=cfg,
            caption="Не передавай конфигурацию другим людям.",
        )
    except VPNProviderNotConfigured as exc:
        await call.message.answer(str(exc), reply_markup=menu())
