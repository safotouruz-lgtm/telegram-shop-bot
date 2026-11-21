"""SQLite storage: products, carts and orders."""
from __future__ import annotations

from dataclasses import dataclass

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    price_cents INTEGER NOT NULL CHECK (price_cents > 0),
    stock       INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
    photo_id    TEXT,
    is_active   INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS cart_items (
    user_id    INTEGER NOT NULL,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    qty        INTEGER NOT NULL CHECK (qty > 0),
    PRIMARY KEY (user_id, product_id)
);
CREATE TABLE IF NOT EXISTS orders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    customer    TEXT    NOT NULL,
    phone       TEXT    NOT NULL,
    address     TEXT    NOT NULL,
    total_cents INTEGER NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'new',  -- new | paid | shipped | cancelled
    created_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS order_items (
    order_id    INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id  INTEGER NOT NULL,
    title       TEXT    NOT NULL,
    price_cents INTEGER NOT NULL,
    qty         INTEGER NOT NULL
);
"""

MAX_PRODUCTS = 30


@dataclass
class Product:
    id: int
    title: str
    description: str
    price_cents: int
    stock: int
    photo_id: str | None
    is_active: bool


@dataclass
class CartLine:
    product: Product
    qty: int

    @property
    def subtotal(self) -> int:
        return self.product.price_cents * self.qty


class OutOfStock(Exception):
    def __init__(self, title: str, available: int):
        super().__init__(f"{title}: only {available} left")
        self.title, self.available = title, available


class Database:
    def __init__(self, path: str):
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA foreign_keys = ON")
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()

    # ---------- products ----------
    @staticmethod
    def _product(row) -> Product:
        return Product(
            row["id"], row["title"], row["description"], row["price_cents"],
            row["stock"], row["photo_id"], bool(row["is_active"]),
        )

    async def list_products(self, only_active: bool = True) -> list[Product]:
        q = "SELECT * FROM products"
        if only_active:
            q += " WHERE is_active = 1"
        async with self.conn.execute(q + " ORDER BY id") as cur:
            return [self._product(r) for r in await cur.fetchall()]

    async def get_product(self, product_id: int) -> Product | None:
        async with self.conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)) as cur:
            row = await cur.fetchone()
        return self._product(row) if row else None

    async def count_products(self) -> int:
        async with self.conn.execute("SELECT COUNT(*) FROM products") as cur:
            return (await cur.fetchone())[0]

    async def add_product(self, title: str, description: str, price_cents: int,
                          stock: int, photo_id: str | None) -> int:
        if await self.count_products() >= MAX_PRODUCTS:
            raise ValueError(f"Catalog limit reached ({MAX_PRODUCTS} products).")
        cur = await self.conn.execute(
            "INSERT INTO products (title, description, price_cents, stock, photo_id) VALUES (?,?,?,?,?)",
            (title, description, price_cents, stock, photo_id),
        )
        await self.conn.commit()
        return cur.lastrowid

    async def set_stock(self, product_id: int, stock: int) -> None:
        await self.conn.execute("UPDATE products SET stock = ? WHERE id = ?", (stock, product_id))
        await self.conn.commit()

    async def set_price(self, product_id: int, price_cents: int) -> None:
        await self.conn.execute("UPDATE products SET price_cents = ? WHERE id = ?", (price_cents, product_id))
        await self.conn.commit()

    async def toggle_active(self, product_id: int) -> None:
        await self.conn.execute(
            "UPDATE products SET is_active = 1 - is_active WHERE id = ?", (product_id,)
        )
        await self.conn.commit()

    # ---------- cart ----------
    async def cart(self, user_id: int) -> list[CartLine]:
        q = """SELECT p.*, c.qty FROM cart_items c JOIN products p ON p.id = c.product_id
               WHERE c.user_id = ? ORDER BY p.id"""
        async with self.conn.execute(q, (user_id,)) as cur:
            return [CartLine(self._product(r), r["qty"]) for r in await cur.fetchall()]

    async def change_qty(self, user_id: int, product_id: int, delta: int) -> int:
        """Add delta to the cart line, capped by stock. Returns the new quantity (0 = removed)."""
        product = await self.get_product(product_id)
        if not product or not product.is_active:
            return 0
        async with self.conn.execute(
            "SELECT qty FROM cart_items WHERE user_id = ? AND product_id = ?", (user_id, product_id)
        ) as cur:
            row = await cur.fetchone()
        new_qty = max(0, min((row["qty"] if row else 0) + delta, product.stock))
        if new_qty == 0:
            await self.conn.execute(
                "DELETE FROM cart_items WHERE user_id = ? AND product_id = ?", (user_id, product_id)
            )
        else:
            await self.conn.execute(
                """INSERT INTO cart_items (user_id, product_id, qty) VALUES (?,?,?)
                   ON CONFLICT(user_id, product_id) DO UPDATE SET qty = excluded.qty""",
                (user_id, product_id, new_qty),
            )
        await self.conn.commit()
        return new_qty

    async def clear_cart(self, user_id: int) -> None:
        await self.conn.execute("DELETE FROM cart_items WHERE user_id = ?", (user_id,))
        await self.conn.commit()

    # ---------- orders ----------
    async def create_order(self, user_id: int, customer: str, phone: str, address: str) -> int:
        """Atomically re-checks stock, reserves it, saves the order and empties the cart."""
        lines = await self.cart(user_id)
        if not lines:
            raise ValueError("Cart is empty.")
        await self.conn.execute("BEGIN IMMEDIATE")
        try:
            for line in lines:
                cur = await self.conn.execute(
                    "UPDATE products SET stock = stock - ? WHERE id = ? AND stock >= ?",
                    (line.qty, line.product.id, line.qty),
                )
                if cur.rowcount == 0:
                    fresh = await self.get_product(line.product.id)
                    raise OutOfStock(line.product.title, fresh.stock if fresh else 0)
            total = sum(l.subtotal for l in lines)
            cur = await self.conn.execute(
                "INSERT INTO orders (user_id, customer, phone, address, total_cents) VALUES (?,?,?,?,?)",
                (user_id, customer, phone, address, total),
            )
            order_id = cur.lastrowid
            await self.conn.executemany(
                "INSERT INTO order_items (order_id, product_id, title, price_cents, qty) VALUES (?,?,?,?,?)",
                [(order_id, l.product.id, l.product.title, l.product.price_cents, l.qty) for l in lines],
            )
            await self.conn.execute("DELETE FROM cart_items WHERE user_id = ?", (user_id,))
            await self.conn.commit()
            return order_id
        except Exception:
            await self.conn.rollback()
            raise

    async def get_order(self, order_id: int) -> dict | None:
        async with self.conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)) as cur:
            order = await cur.fetchone()
        if not order:
            return None
        async with self.conn.execute("SELECT * FROM order_items WHERE order_id = ?", (order_id,)) as cur:
            items = [dict(r) for r in await cur.fetchall()]
        return {**dict(order), "items": items}

    async def set_order_status(self, order_id: int, status: str) -> None:
        if status == "cancelled":
            order = await self.get_order(order_id)
            if order and order["status"] != "cancelled":  # return stock
                await self.conn.executemany(
                    "UPDATE products SET stock = stock + ? WHERE id = ?",
                    [(i["qty"], i["product_id"]) for i in order["items"]],
                )
        await self.conn.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
        await self.conn.commit()

    async def recent_orders(self, limit: int = 10) -> list[dict]:
        async with self.conn.execute(
            "SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]
