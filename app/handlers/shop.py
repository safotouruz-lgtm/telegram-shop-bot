"""Customer side: catalog, product cards, cart, checkout, payment."""
from aiogram import Bot, F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
    ReplyKeyboardRemove,
)

from .. import keyboards as kb
from ..config import Config
from ..db import Database, OutOfStock

router = Router(name="shop")


class Checkout(StatesGroup):
    name = State()
    phone = State()
    address = State()


@router.message(CommandStart())
async def start(message: Message, config: Config):
    await message.answer(
        "Welcome! Browse the catalog, add items to your cart and check out in a few taps.",
        reply_markup=kb.main_menu(message.from_user.id in config.admin_ids),
    )


@router.message(F.text == "🛍 Catalog")
async def show_catalog(message: Message, db: Database, config: Config):
    await message.answer("Our products:", reply_markup=kb.catalog(await db.list_products(), config.currency))


@router.callback_query(F.data == "catalog")
async def cb_catalog(call: CallbackQuery, db: Database, config: Config):
    await call.message.answer("Our products:", reply_markup=kb.catalog(await db.list_products(), config.currency))
    await call.answer()


async def _in_cart(db: Database, user_id: int, product_id: int) -> int:
    return next((l.qty for l in await db.cart(user_id) if l.product.id == product_id), 0)


def _card_text(p, currency: str) -> str:
    stock = f"In stock: {p.stock}" if p.stock else "Sold out"
    return f"<b>{p.title}</b>\n{p.description}\n\nPrice: {kb.money(p.price_cents, currency)}\n{stock}"


@router.callback_query(F.data.startswith("prod:"))
async def cb_product(call: CallbackQuery, db: Database, config: Config):
    p = await db.get_product(int(call.data.split(":")[1]))
    if not p or not p.is_active:
        return await call.answer("This product is no longer available.", show_alert=True)
    markup = kb.product_card(p, await _in_cart(db, call.from_user.id, p.id))
    if p.photo_id:
        await call.message.answer_photo(p.photo_id, caption=_card_text(p, config.currency), reply_markup=markup)
    else:
        await call.message.answer(_card_text(p, config.currency), reply_markup=markup)
    await call.answer()


@router.callback_query(F.data.startswith("qty:"))
async def cb_qty(call: CallbackQuery, db: Database):
    _, pid, delta = call.data.split(":")
    p = await db.get_product(int(pid))
    before = await _in_cart(db, call.from_user.id, int(pid))
    qty = await db.change_qty(call.from_user.id, int(pid), int(delta))
    if int(delta) > 0 and qty == before:
        return await call.answer("No more stock for this item.", show_alert=True)
    await call.message.edit_reply_markup(reply_markup=kb.product_card(p, qty))
    await call.answer("Cart updated")


def _cart_text(lines, currency: str) -> str:
    if not lines:
        return "Your cart is empty."
    body = "\n".join(f"• {l.product.title} × {l.qty} = {kb.money(l.subtotal, currency)}" for l in lines)
    return f"<b>Your cart</b>\n{body}\n\n<b>Total: {kb.money(sum(l.subtotal for l in lines), currency)}</b>"


@router.message(F.text == "🛒 Cart")
async def show_cart(message: Message, db: Database, config: Config):
    lines = await db.cart(message.from_user.id)
    await message.answer(_cart_text(lines, config.currency), reply_markup=kb.cart(lines))


@router.callback_query(F.data == "cart")
async def cb_cart(call: CallbackQuery, db: Database, config: Config):
    lines = await db.cart(call.from_user.id)
    await call.message.answer(_cart_text(lines, config.currency), reply_markup=kb.cart(lines))
    await call.answer()


@router.callback_query(F.data.startswith("cqty:"))
async def cb_cart_qty(call: CallbackQuery, db: Database, config: Config):
    _, pid, delta = call.data.split(":")
    await db.change_qty(call.from_user.id, int(pid), int(delta))
    lines = await db.cart(call.from_user.id)
    await call.message.edit_text(_cart_text(lines, config.currency), reply_markup=kb.cart(lines))
    await call.answer()


@router.callback_query(F.data == "cart_clear")
async def cb_clear(call: CallbackQuery, db: Database):
    await db.clear_cart(call.from_user.id)
    await call.message.edit_text("Your cart is empty.", reply_markup=kb.cart([]))
    await call.answer()


# ---------- checkout ----------
@router.callback_query(F.data == "checkout")
async def cb_checkout(call: CallbackQuery, state: FSMContext, db: Database):
    if not await db.cart(call.from_user.id):
        return await call.answer("Your cart is empty.", show_alert=True)
    await state.set_state(Checkout.name)
    await call.message.answer("What name should we put on the order?", reply_markup=ReplyKeyboardRemove())
    await call.answer()


@router.message(Checkout.name, F.text)
async def got_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip()[:100])
    await state.set_state(Checkout.phone)
    await message.answer("Your phone number:", reply_markup=kb.share_phone())


@router.message(Checkout.phone, F.contact | F.text)
async def got_phone(message: Message, state: FSMContext):
    phone = message.contact.phone_number if message.contact else message.text.strip()
    await state.update_data(phone=phone[:30])
    await state.set_state(Checkout.address)
    await message.answer("Delivery address:", reply_markup=ReplyKeyboardRemove())


@router.message(Checkout.address, F.text)
async def got_address(message: Message, state: FSMContext, db: Database, config: Config, bot: Bot):
    data = await state.get_data()
    await state.clear()
    try:
        order_id = await db.create_order(message.from_user.id, data["name"], data["phone"], message.text.strip()[:300])
    except OutOfStock as e:
        return await message.answer(
            f"Sorry, <b>{e.title}</b> has only {e.available} left. Please adjust your cart.",
            reply_markup=kb.main_menu(message.from_user.id in config.admin_ids),
        )
    order = await db.get_order(order_id)
    await message.answer(
        f"✅ Order #{order_id} received. Total: {kb.money(order['total_cents'], config.currency)}",
        reply_markup=kb.main_menu(message.from_user.id in config.admin_ids),
    )

    if config.payment_token:
        await bot.send_invoice(
            chat_id=message.chat.id,
            title=f"Order #{order_id}",
            description=", ".join(f"{i['title']} × {i['qty']}" for i in order["items"])[:255],
            payload=f"order:{order_id}",
            provider_token=config.payment_token,
            currency=config.currency,
            prices=[LabeledPrice(label=f"{i['title']} × {i['qty']}", amount=i["price_cents"] * i["qty"])
                    for i in order["items"]],
        )
    else:
        await message.answer("We'll contact you shortly to confirm payment and delivery.")

    await _notify_admins(bot, config, order, "🆕 New order")


async def _notify_admins(bot: Bot, config: Config, order: dict, header: str) -> None:
    items = "\n".join(f"• {i['title']} × {i['qty']}" for i in order["items"])
    text = (f"{header} #{order['id']} — {order['status']}\n{order['customer']}, {order['phone']}\n"
            f"{order['address']}\n\n{items}\n\nTotal: {kb.money(order['total_cents'], config.currency)}")
    for admin_id in config.admin_ids:
        try:
            await bot.send_message(admin_id, text, reply_markup=kb.order_actions(order["id"]))
        except Exception:  # admin hasn't started the bot yet
            pass


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery, db: Database):
    order = await db.get_order(int(query.invoice_payload.split(":")[1]))
    ok = bool(order) and order["status"] == "new"
    await query.answer(ok=ok, error_message=None if ok else "This order can no longer be paid.")


@router.message(F.successful_payment)
async def paid(message: Message, db: Database, config: Config, bot: Bot):
    order_id = int(message.successful_payment.invoice_payload.split(":")[1])
    await db.set_order_status(order_id, "paid")
    await message.answer(f"💳 Payment received for order #{order_id}. Thank you!")
    await _notify_admins(bot, config, await db.get_order(order_id), "💳 Paid order")


@router.callback_query(F.data == "noop")
async def noop(call: CallbackQuery):
    await call.answer()


@router.callback_query()
async def stale_button(call: CallbackQuery):
    """Old or unauthorized buttons: stop the loading spinner instead of hanging."""
    await call.answer("This button is no longer active.")
