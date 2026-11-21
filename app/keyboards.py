from aiogram.types import (
    InlineKeyboardButton as Btn,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from .db import CartLine, Product


def money(cents: int, currency: str) -> str:
    return f"{cents / 100:,.2f} {currency}"


def main_menu(is_admin: bool) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text="🛍 Catalog"), KeyboardButton(text="🛒 Cart")]]
    if is_admin:
        rows.append([KeyboardButton(text="⚙️ Admin")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def catalog(products: list[Product], currency: str) -> InlineKeyboardMarkup:
    rows = [
        [Btn(text=f"{p.title} — {money(p.price_cents, currency)}" + ("" if p.stock else " (sold out)"),
             callback_data=f"prod:{p.id}")]
        for p in products
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows or [[Btn(text="No products yet", callback_data="noop")]])


def product_card(p: Product, in_cart: int) -> InlineKeyboardMarkup:
    rows = []
    if p.stock:
        rows.append([
            Btn(text="➖", callback_data=f"qty:{p.id}:-1"),
            Btn(text=f"In cart: {in_cart}", callback_data="noop"),
            Btn(text="➕", callback_data=f"qty:{p.id}:1"),
        ])
    rows.append([Btn(text="⬅️ Catalog", callback_data="catalog"), Btn(text="🛒 Cart", callback_data="cart")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def cart(lines: list[CartLine]) -> InlineKeyboardMarkup:
    rows = [
        [
            Btn(text="➖", callback_data=f"cqty:{l.product.id}:-1"),
            Btn(text=f"{l.product.title} × {l.qty}", callback_data=f"prod:{l.product.id}"),
            Btn(text="➕", callback_data=f"cqty:{l.product.id}:1"),
        ]
        for l in lines
    ]
    if lines:
        rows.append([Btn(text="🗑 Clear", callback_data="cart_clear"), Btn(text="✅ Checkout", callback_data="checkout")])
    rows.append([Btn(text="⬅️ Catalog", callback_data="catalog")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def share_phone() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Share phone number", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True,
    )


def admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [Btn(text="➕ Add product", callback_data="adm:add")],
        [Btn(text="📦 Products & stock", callback_data="adm:list")],
        [Btn(text="🧾 Recent orders", callback_data="adm:orders")],
    ])


def admin_product(p: Product) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [Btn(text="Stock −1", callback_data=f"adm:stock:{p.id}:-1"),
         Btn(text="Stock +1", callback_data=f"adm:stock:{p.id}:1"),
         Btn(text="Stock +10", callback_data=f"adm:stock:{p.id}:10")],
        [Btn(text="💲 Set price", callback_data=f"adm:price:{p.id}"),
         Btn(text="🙈 Hide" if p.is_active else "👁 Show", callback_data=f"adm:toggle:{p.id}")],
        [Btn(text="⬅️ Back", callback_data="adm:list")],
    ])


def order_actions(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        Btn(text="📦 Shipped", callback_data=f"adm:ord:{order_id}:shipped"),
        Btn(text="❌ Cancel", callback_data=f"adm:ord:{order_id}:cancelled"),
    ]])
