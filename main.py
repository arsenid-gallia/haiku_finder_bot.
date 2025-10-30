import os
import re
import random
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# === НАСТРОЙКИ ===
BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_PATH = "/webhook"
PORT = int(os.environ.get("PORT", 10000))
# Render сам задаёт PORT, но на всякий случай — дефолт 10000

HAiku_RESPONSES = [
    "нифига ты самурай",
    "вот это хокку!",
    "ты поэт, братишка",
    "сакура расцвела в твоих словах",
    "даже цикада замолчала"
]

# === СЧЁТ СЛОГОВ (только русский) ===
def count_syllables(word):
    word = word.lower()
    vowels = "аеёиоуыэюя"
    count = 0
    prev_vowel = False
    for ch in word:
        is_vowel = ch in vowels
        if is_vowel and not prev_vowel:
            count += 1
        prev_vowel = is_vowel
    return max(1, count)

# === ПОИСК ХОККУ В ЛЮБОМ ФОРМАТЕ ===
def is_haiku(text):
    words = re.findall(r'[а-яА-ЯёЁ]+', text)
    if len(words) < 3:
        return False

    syllables = [count_syllables(w) for w in words]
    n = len(syllables)

    for i in range(n):
        s1, j = 0, i
        while j < n and s1 < 5:
            s1 += syllables[j]
            j += 1
        if s1 != 5:
            continue

        s2, k = 0, j
        while k < n and s2 < 7:
            s2 += syllables[k]
            k += 1
        if s2 != 7:
            continue

        s3, l = 0, k
        while l < n and s3 < 5:
            s3 += syllables[l]
            l += 1
        if s3 == 5:
            return True
    return False

# === ОБРАБОТЧИК СООБЩЕНИЙ ===
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if msg and msg.text and is_haiku(msg.text):
        await msg.reply_text(random.choice(HAiku_RESPONSES))

# === Flask-приложение ===
app = Flask(__name__)

# Глобальное приложение (для доступа в webhook)
application = None

@app.route(WEBHOOK_PATH, methods=["POST"])
def telegram_webhook():
    if request.headers.get("content-type") == "application/json":
        json_data = request.get_json()
        update = Update.de_json(json_data, application.bot)
        application.update_queue.put_nowait(update)
        return "OK", 200
    else:
        return "Invalid content type", 400

@app.route("/", methods=["GET"])
def health_check():
    return "✅ Бот жив! Webhook активен.", 200

# === ЗАПУСК ===
if __name__ == "__main__":
    # Инициализация Telegram-приложения
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Установка webhook
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    if not WEBHOOK_URL:
        raise ValueError("❌ WEBHOOK_URL не задан! Добавьте его в Environment Variables.")
    print(f"✅ Устанавливаю webhook на URL: {WEBHOOK_URL}")
    application.bot.set_webhook(url=WEBHOOK_URL)

    # Запуск Flask-сервера
    app.run(host="0.0.0.0", port=PORT)
