import asyncio
import uvicorn

from core import BASE_URL, PORT, validate_config
from telegram_bot import bot, dp
from webapp import app


async def run_web():
    server = uvicorn.Server(
        uvicorn.Config(app, host="0.0.0.0", port=PORT, log_level="info", access_log=True)
    )
    await server.serve()


async def main():
    validate_config()
    me = await bot.get_me()
    print(f"FatherVPN @{me.username} started; web={BASE_URL}; port={PORT}")
    await asyncio.gather(dp.start_polling(bot), run_web())


if __name__ == "__main__":
    asyncio.run(main())
