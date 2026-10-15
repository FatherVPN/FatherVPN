import asyncio, os
import uvicorn
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from app.db import init_db
from app.bot import router

load_dotenv()

async def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("Set BOT_TOKEN in .env")
    init_db()
    bot = Bot(token=token)
    dp = Dispatcher()
    dp.include_router(router)
    server = uvicorn.Server(uvicorn.Config(
        "app.api:app", host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", "8080")), log_level="info"))
    await asyncio.gather(dp.start_polling(bot), server.serve())

if __name__ == "__main__":
    asyncio.run(main())
