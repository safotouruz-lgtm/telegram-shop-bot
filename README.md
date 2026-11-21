# Telegram Shop Bot

A small, production-minded Telegram store built with **Python + aiogram 3**.
Customers browse a catalog, build a cart and check out; the owner manages
products, stock, prices and orders **inside Telegram** — no separate admin site.

## Features

**Customers**
- Catalog of up to 30 products with photos, descriptions and prices
- Product cards with ➖ / ➕ quantity controls (capped by available stock)
- Cart with per-item editing, totals and "clear cart"
- Checkout: name → phone (one-tap contact share) → delivery address
- Optional online payment via **Telegram Payments** (Stripe, Click, Payme, etc.)
- Status messages when an order is shipped or cancelled

**Owner / admins**
- `/admin` panel: add products step-by-step (with photo), change price, hide/show
- Inventory: stock +/−, low-stock ⚠️ flag, "sold out" shown automatically
- Instant notification for every new and paid order, with **Shipped / Cancel** buttons
- Cancelling an order returns its items to stock
- Recent orders list

## How it's built

| Part | Choice | Why |
|---|---|---|
| Bot framework | aiogram 3 (async) | Modern, typed, FSM for multi-step forms |
| Storage | SQLite via aiosqlite | Zero setup; easy to swap for PostgreSQL |
| Stock safety | Atomic `UPDATE … WHERE stock >= qty` in one transaction | Two buyers can't oversell the last item |
| Payments | Telegram Payments (`send_invoice`) | No card data touches the bot |

```
app/
  main.py          # startup, dependency injection
  config.py        # .env settings
  db.py            # schema + all queries (products, cart, orders)
  keyboards.py     # inline / reply keyboards
  handlers/
    shop.py        # customer flow + payments
    admin.py       # admin panel (admin-only filter)
```

## Run it locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # then fill in BOT_TOKEN and ADMIN_IDS
python -m app.main
```

- Get a token from [@BotFather](https://t.me/BotFather).
- Get your numeric Telegram ID from [@userinfobot](https://t.me/userinfobot) and put it in `ADMIN_IDS`.
- For payments, connect a provider in BotFather → *Payments* and set `PAYMENT_PROVIDER_TOKEN`.
  Leave it empty to take orders without online payment.

## Deploy

Runs anywhere Python 3.10+ runs (Railway, a VPS, Docker). For production, switch
`MemoryStorage` to Redis storage so checkout steps survive restarts, and point
`DB_PATH` at a persistent volume (or migrate to PostgreSQL).

## License

MIT
