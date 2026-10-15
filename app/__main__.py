import asyncio
import os
import sys

import uvicorn
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher

from app.db import init_db
from app.bot import router

load_dotenv()


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        print(f"[fatal] Environment variable {name} is not set", file=sys.stderr)
        sys.exit(1)
    return value


async def main():
    # Fail fast on missing config BEFORE starting anything.
    token = require_env("BOT_TOKEN")
    # JWT_SECRET is required by app.api at import time, but we check here too
    # so the error message is friendlier.
    require_env("JWT_SECRET")

    init_db()

    bot = Bot(token=token)
    dp = Dispatcher()
    dp.include_router(router)

    # Render injects PORT for web services. Fall back to API_PORT, then 8080.
    port = int(os.getenv("PORT") or os.getenv("API_PORT") or "8080")
    host = os.getenv("API_HOST", "0.0.0.0")

    config = uvicorn.Config(
        "app.api:app",
        host=host,
        port=port,
        log_level="info",
    )
    server = uvicorn.Server(config)

    await asyncio.gather(
        dp.start_polling(bot),
        server.serve(),
    )


if __name__ == "__main__":
    asyncio.run(main())
