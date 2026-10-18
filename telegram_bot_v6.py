import html
from aiogram import Bot,Dispatcher,F,Router
from aiogram.filters import Command,CommandObject,CommandStart
from aiogram.types import CallbackQuery,InlineKeyboardButton,InlineKeyboardMarkup,LabeledPrice,Message,PreCheckoutQuery
from core import ADMIN_ID,BASE_URL,BOT_TOKEN,PAYMENT_CURRENCY,PAYMENT_PROVIDER_TOKEN,PAYMENTS_ENABLED,TARIFFS,ensure_cabinet_token,fmt_dt,fulfill_payment,get_user,grant_subscription,log_action,parse_payload,payment_payload,paymaster_provider_data,resolve_target,set_user_blocked,subscription_active,subscription_url,upsert_user
bot=Bot(BOT_TOKEN or '1:TEST');dp=Dispatcher();router=Router();dp.include_router(router)
def ik(r):return InlineKeyboardMarkup(inline_keyboard=r)
def menu(uid):
 rows=[[InlineKeyboardButton(text='🚀 Купить VPN',callback_data='buy')],[InlineKeyboardButton(text='👤 Моя подписка',callback_data='profile')],[InlineKeyboardButton(text='🌐 Личный кабинет',url=f'{BASE_URL}/cabinet/{ensure_cabinet_token(uid)}')],[InlineKeyboardButton(text='📖 Инструкция',callback_data='help'),InlineKeyboardButton(text='🆘 Поддержка',url='https://t.me/Father_vpn_support')]]
 if uid==ADMIN_ID:rows.append([InlineKeyboardButton(text='🛠 Админ',callback_data='admin')])
 return ik(rows)
def plans():
 r=[]
 for c,t in TARIFFS.items():r.append([InlineKeyboardButton(text=f"{t['emoji']} {t['name']} — {t['price']} ₽" if t['price'] else f"{t['emoji']} {t['name']}",callback_data=f'tariff:{c}')])
 r.append([InlineKeyboardButton(text='⬅️ Назад',callback_data='menu')]);return ik(r)
def access(uid):
 url=subscription_url(uid);return f'🔗 <b>Ваша ссылка:</b>\n<code>{html.escape(url)}</code>',ik([[InlineKeyboardButton(text='🌐 Открыть подписку и QR',url=url)],[InlineKeyboardButton(text='⬅️ Меню',callback_data='menu')]])
@router.message(CommandStart())
async def start(m:Message,command:CommandObject):
 u=m.from_user;upsert_user(u.id,u.username or '',u.first_name or '');await m.answer('☁️ <b>FatherVPN</b>\nОдна подписка — одна персональная ссылка.',reply_markup=menu(u.id),parse_mode='HTML')
@router.callback_query(F.data=='menu')
async def cm(q:CallbackQuery):await q.message.edit_text('☁️ <b>FatherVPN</b>\nГлавное меню',reply_markup=menu(q.from_user.id),parse_mode='HTML');await q.answer()
@router.callback_query(F.data=='buy')
async def buy(q:CallbackQuery):await q.message.edit_text('🚀 <b>Выберите тариф</b>',reply_markup=plans(),parse_mode='HTML');await q.answer()
@router.callback_query(F.data.startswith('tariff:'))
async def tariff(q:CallbackQuery):
 c=q.data.split(':',1)[1];t=TARIFFS.get(c)
 if not t:return await q.answer('Тариф не найден',show_alert=True)
 r=[[InlineKeyboardButton(text='💳 Оплатить TEST',callback_data=f'pay:{c}')]] if t['price'] and PAYMENTS_ENABLED else [[InlineKeyboardButton(text='🆘 Получить через поддержку',url='https://t.me/Father_vpn_support')]]
 r.append([InlineKeyboardButton(text='⬅️ Назад',callback_data='buy')]);await q.message.edit_text(f"{t['emoji']} <b>{t['name']}</b>\n💰 {t['price']} ₽\n📅 {t['days']} дней\n\nПосле оплаты ссылка и QR появятся автоматически.",reply_markup=ik(r),parse_mode='HTML');await q.answer()
@router.callback_query(F.data.startswith('pay:'))
async def pay(q:CallbackQuery):
 c=q.data.split(':',1)[1];t=TARIFFS.get(c)
 if not t or not t['price'] or not PAYMENTS_ENABLED:return await q.answer('Оплата недоступна',show_alert=True)
 p=payment_payload(q.from_user.id,c);uid,code,nonce=parse_payload(p)
 await bot.send_invoice(chat_id=q.from_user.id,title=f"FatherVPN · {t['name']}",description='Персональная подписка FatherVPN',payload=p,provider_token=PAYMENT_PROVIDER_TOKEN,currency=PAYMENT_CURRENCY,prices=[LabeledPrice(label=f"FatherVPN · {t['name']}",amount=t['price']*100)],provider_data=paymaster_provider_data(uid,code,nonce),start_parameter=f'fathervpn-{c}');await q.answer('Счёт отправлен')
@router.pre_checkout_query()
async def checkout(p:PreCheckoutQuery):
 x=parse_payload(p.invoice_payload)
 if not x:return await p.answer(ok=False,error_message='Некорректный заказ')
 uid,c,_=x;t=TARIFFS[c]
 await p.answer(ok=uid==p.from_user.id and p.currency==PAYMENT_CURRENCY and p.total_amount==t['price']*100,error_message='Сумма заказа изменилась')
@router.message(F.successful_payment)
async def success(m:Message):
 sp=m.successful_payment;x=parse_payload(sp.invoice_payload)
 if not x:return
 uid,c,_=x
 if uid!=m.from_user.id:return
 exp,applied=fulfill_payment(uid,c,sp)
 if not applied:return
 text,kb=access(uid);await m.answer(f'✅ <b>Оплата подтверждена</b>\nПодписка до {html.escape(fmt_dt(exp.isoformat()))}.\n\n{text}',reply_markup=kb,parse_mode='HTML')
@router.callback_query(F.data=='profile')
async def profile(q:CallbackQuery):
 u=get_user(q.from_user.id);status='✅ Активна' if subscription_active(u) else ('⛔ Заблокирована' if u and u['blocked'] else '⚪ Неактивна');text,kb=access(q.from_user.id);await q.message.edit_text(f"👤 <b>Моя подписка</b>\nСтатус: {status}\nТариф: <b>{html.escape((u['tariff'] if u else '') or '—')}</b>\nДо: <b>{html.escape(fmt_dt(u['expires_at'] if u else None))}</b>\n\n{text}",reply_markup=kb,parse_mode='HTML');await q.answer()
@router.callback_query(F.data=='help')
async def helpme(q:CallbackQuery):await q.message.edit_text('📖 <b>Подключение</b>\n1. Купите подписку.\n2. Бот сразу выдаст персональную ссылку.\n3. Откройте её в браузере, чтобы увидеть QR.\n4. Эту же ссылку добавьте в VPN-клиент.\n\nОтдельного RAW-адреса нет.',reply_markup=ik([[InlineKeyboardButton(text='⬅️ Назад',callback_data='menu')]]),parse_mode='HTML');await q.answer()
@router.callback_query(F.data=='admin')
async def admin(q:CallbackQuery):
 if q.from_user.id!=ADMIN_ID:return await q.answer('Нет доступа',show_alert=True)
 await q.message.edit_text('🛠 <b>Админ</b>\n<code>/grant ID 1d|7d|1m|3m|6m|12m</code>\n<code>/block ID</code>\n<code>/unblock ID</code>',reply_markup=ik([[InlineKeyboardButton(text='⬅️ Назад',callback_data='menu')]]),parse_mode='HTML');await q.answer()
@router.message(Command('grant'))
async def grant(m:Message,command:CommandObject):
 if m.from_user.id!=ADMIN_ID:return
 p=(command.args or '').split()
 if len(p)!=2 or p[1] not in TARIFFS:return await m.answer('Использование: /grant ID 1d|7d|1m|3m|6m|12m')
 u=resolve_target(p[0])
 if not u:return await m.answer('Пользователь не найден')
 exp=grant_subscription(u['user_id'],p[1]);url=subscription_url(u['user_id']);await m.answer(f"✅ Выдано до {html.escape(fmt_dt(exp.isoformat()))}\n<code>{html.escape(url)}</code>",parse_mode='HTML');await bot.send_message(u['user_id'],f"🎁 <b>Подписка FatherVPN активирована</b>\nДо: {html.escape(fmt_dt(exp.isoformat()))}\n\n<code>{html.escape(url)}</code>",reply_markup=ik([[InlineKeyboardButton(text='🌐 Открыть подписку и QR',url=url)]]),parse_mode='HTML')
@router.message(Command('block','unblock'))
async def block(m:Message,command:CommandObject):
 if m.from_user.id!=ADMIN_ID:return
 u=resolve_target((command.args or '').strip())
 if not u:return await m.answer('Пользователь не найден')
 b=m.text.split()[0].split('@')[0]=='/block';set_user_blocked(u['user_id'],b);await m.answer('⛔ Заблокирован' if b else '✅ Разблокирован')
