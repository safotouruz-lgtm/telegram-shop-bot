import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_ids: frozenset[int]
    payment_token: str
    currency: str
    db_path: str


def load_config() -> Config:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")
    admins = frozenset(
        int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x
    )
    return Config(
        bot_token=token,
        admin_ids=admins,
        payment_token=os.getenv("PAYMENT_PROVIDER_TOKEN", "").strip(),
        currency=os.getenv("CURRENCY", "USD").strip().upper(),
        db_path=os.getenv("DB_PATH", "shop.db"),
    )
