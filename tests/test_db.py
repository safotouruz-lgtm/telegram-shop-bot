import pytest

from app.db import MAX_PRODUCTS, Database, OutOfStock


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


async def test_cart_quantity_is_capped_by_stock(db):
    pid = await db.add_product("Mug", "Ceramic", 1250, 2, None)
    assert await db.change_qty(1, pid, 5) == 2
    assert await db.change_qty(1, pid, -2) == 0
    assert await db.cart(1) == []


async def test_order_reserves_stock_and_clears_cart(db):
    mug = await db.add_product("Mug", "", 1250, 3, None)
    tee = await db.add_product("Tee", "", 1999, 5, None)
    await db.change_qty(1, mug, 2)
    await db.change_qty(1, tee, 1)

    order_id = await db.create_order(1, "Ali", "+998900000000", "Tashkent")
    order = await db.get_order(order_id)

    assert order["total_cents"] == 2 * 1250 + 1999
    assert (await db.get_product(mug)).stock == 1
    assert await db.cart(1) == []


async def test_last_item_cannot_be_oversold(db):
    pid = await db.add_product("Mug", "", 1250, 1, None)
    await db.change_qty(1, pid, 1)
    await db.change_qty(2, pid, 1)

    await db.create_order(1, "A", "1", "x")
    with pytest.raises(OutOfStock):
        await db.create_order(2, "B", "2", "y")
    assert (await db.get_product(pid)).stock == 0


async def test_cancelling_returns_stock(db):
    pid = await db.add_product("Mug", "", 1250, 2, None)
    await db.change_qty(1, pid, 2)
    order_id = await db.create_order(1, "A", "1", "x")

    await db.set_order_status(order_id, "cancelled")
    await db.set_order_status(order_id, "cancelled")  # idempotent
    assert (await db.get_product(pid)).stock == 2


async def test_catalog_limit(db):
    for i in range(MAX_PRODUCTS):
        await db.add_product(f"P{i}", "", 100, 1, None)
    with pytest.raises(ValueError):
        await db.add_product("One too many", "", 100, 1, None)
