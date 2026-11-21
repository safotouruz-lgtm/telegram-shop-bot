"""Admin panel inside Telegram: products, stock, prices, orders."""
from aiogram import F, Router
from aiogram.filters import BaseFilter, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, TelegramObject

from .. import keyboards as kb
from ..config import Config
from ..db import Database

router = Router(name="admin")


class IsAdmin(BaseFilter):
    async def __call__(self, event: TelegramObject, config: Config) -> bool:
        return event.from_user is not None and event.from_user.id in config.admin_ids


router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


class AddProduct(StatesGroup):
    title = State()
    description = State()
    price = State()
    stock = State()
    photo = State()


class SetPrice(StatesGroup):
    value = State()


def parse_price(text: str) -> int | None:
    try:
        cents = round(float(text.replace(",", ".").strip()) * 100)
    except ValueError:
        return None
    return cents if cents > 0 else None


@router.message(Command("admin"))
@router.message(F.text == "⚙️ Admin")
async def admin_home(message: Message):
    await message.answer("Admin panel:", reply_markup=kb.admin_menu())


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Cancelled.", reply_markup=kb.admin_menu())


# ---------- add product ----------
@router.callback_query(F.data == "adm:add")
async def add_start(call: CallbackQuery, state: FSMContext):
    await state.set_state(AddProduct.title)
    await call.message.answer("Product title? (/cancel to stop)")
    await call.answer()


@router.message(AddProduct.title, F.text)
async def add_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip()[:100])
    await state.set_state(AddProduct.description)
    await message.answer("Short description:")


@router.message(AddProduct.description, F.text)
async def add_desc(message: Message, state: FSMContext):
    await state.update_data(description=message.text.strip()[:800])
    await state.set_state(AddProduct.price)
    await message.answer("Price (e.g. 19.99):")


@router.message(AddProduct.price, F.text)
async def add_price(message: Message, state: FSMContext):
    cents = parse_price(message.text)
    if cents is None:
        return await message.answer("Please send a positive number, e.g. 19.99")
    await state.update_data(price_cents=cents)
    await state.set_state(AddProduct.stock)
    await message.answer("Units in stock:")


@router.message(AddProduct.stock, F.text)
async def add_stock(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        return await message.answer("Please send a whole number, e.g. 25")
    await state.update_data(stock=int(message.text.strip()))
    await state.set_state(AddProduct.photo)
    await message.answer("Send a product photo, or type 'skip'.")


@router.message(AddProduct.photo, F.photo | F.text)
async def add_photo(message: Message, state: FSMContext, db: Database):
    data = await state.get_data()
    photo_id = message.photo[-1].file_id if message.photo else None
    await state.clear()
    try:
        pid = await db.add_product(data["title"], data["description"], data["price_cents"], data["stock"], photo_id)
    except ValueError as e:
        return await message.answer(str(e), reply_markup=kb.admin_menu())
    await message.answer(f"✅ Product #{pid} added.", reply_markup=kb.admin_menu())


# ---------- product list / stock ----------
@router.callback_query(F.data == "adm:list")
async def list_products(call: CallbackQuery, db: Database, config: Config):
    products = await db.list_products(only_active=False)
    if not products:
        await call.message.answer("No products yet.", reply_markup=kb.admin_menu())
        return await call.answer()
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    rows = [[InlineKeyboardButton(
        text=f"{'' if p.is_active else '🙈 '}{p.title} · {kb.money(p.price_cents, config.currency)} · stock {p.stock}"
             + (" ⚠️" if p.stock <= 3 else ""),
        callback_data=f"adm:prod:{p.id}")] for p in products]
    await call.message.answer(f"Products ({len(products)}/30):", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await call.answer()


async def _show_admin_product(call: CallbackQuery, db: Database, config: Config, pid: int, edit: bool):
    p = await db.get_product(pid)
    text = (f"<b>{p.title}</b> ({'visible' if p.is_active else 'hidden'})\n"
            f"Price: {kb.money(p.price_cents, config.currency)}\nStock: {p.stock}")
    if edit:
        await call.message.edit_text(text, reply_markup=kb.admin_product(p))
    else:
        await call.message.answer(text, reply_markup=kb.admin_product(p))


@router.callback_query(F.data.startswith("adm:prod:"))
async def admin_product(call: CallbackQuery, db: Database, config: Config):
    await _show_admin_product(call, db, config, int(call.data.split(":")[2]), edit=False)
    await call.answer()


@router.callback_query(F.data.startswith("adm:stock:"))
async def change_stock(call: CallbackQuery, db: Database, config: Config):
    _, _, pid, delta = call.data.split(":")
    p = await db.get_product(int(pid))
    await db.set_stock(p.id, max(0, p.stock + int(delta)))
    await _show_admin_product(call, db, config, p.id, edit=True)
    await call.answer("Stock updated")


@router.callback_query(F.data.startswith("adm:toggle:"))
async def toggle(call: CallbackQuery, db: Database, config: Config):
    pid = int(call.data.split(":")[2])
    await db.toggle_active(pid)
    await _show_admin_product(call, db, config, pid, edit=True)
    await call.answer()


@router.callback_query(F.data.startswith("adm:price:"))
async def price_start(call: CallbackQuery, state: FSMContext):
    await state.set_state(SetPrice.value)
    await state.update_data(pid=int(call.data.split(":")[2]))
    await call.message.answer("New price (e.g. 24.50):")
    await call.answer()


@router.message(SetPrice.value, F.text)
async def price_set(message: Message, state: FSMContext, db: Database):
    cents = parse_price(message.text)
    if cents is None:
        return await message.answer("Please send a positive number, e.g. 24.50")
    data = await state.get_data()
    await state.clear()
    await db.set_price(data["pid"], cents)
    await message.answer("✅ Price updated.", reply_markup=kb.admin_menu())


# ---------- orders ----------
@router.callback_query(F.data == "adm:orders")
async def orders(call: CallbackQuery, db: Database, config: Config):
    recent = await db.recent_orders()
    if not recent:
        text = "No orders yet."
    else:
        text = "\n".join(
            f"#{o['id']} · {o['status']} · {kb.money(o['total_cents'], config.currency)} · {o['customer']}"
            for o in recent)
    await call.message.answer(text)
    await call.answer()


@router.callback_query(F.data.startswith("adm:ord:"))
async def order_status(call: CallbackQuery, db: Database):
    _, _, oid, status = call.data.split(":")
    order = await db.get_order(int(oid))
    if not order:
        return await call.answer("Order not found.", show_alert=True)
    await db.set_order_status(order["id"], status)
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(f"Order #{oid} marked as {status}.")
    try:
        note = "is on its way 📦" if status == "shipped" else "was cancelled ❌"
        await call.bot.send_message(order["user_id"], f"Your order #{oid} {note}")
    except Exception:
        pass
    await call.answer()
