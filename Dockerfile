FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY bot.py core.py telegram_bot.py telegram_bot_v6.py webapp.py smart_webapp.py index.html ./
COPY servers ./servers
CMD ["sh", "-c", "sed -e 's/from telegram_bot import bot, dp/from telegram_bot_v6 import bot, dp/' -e 's/from webapp import app/from smart_webapp import app/' bot.py > run.py && python run.py"]
