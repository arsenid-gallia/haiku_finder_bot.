import os
import re
import random
import asyncio
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, request
from telegram import Update
from telegram.ext import Application as PTBApplication, MessageHandler, filters, ContextTypes

# === НАСТРОЙКИ ===
BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_PATH = "/webhook"
PORT = int(os.environ.get("PORT", 10000))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
if not WEBHOOK_URL:
    raise ValueError("❌ WEBHOOK_URL не задан! Добавьте его в Environment Variables.")

# Глобальная переменная для хранения приложения PTB
application = None

# === ОТВЕТЫ НА ХОККУ ===
HAiku_RESPONSES = [
    "нифига ты самурай",
    "вот это хокку!",
    "ты поэт, братишка",
    "сакура расцвела в твоих словах",
    "даже цикада замолчала"
]

# === ПОДСЧЁТ СЛОГОВ (только русский) ===
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

@app.route(WEBHOOK_PATH, methods=["POST"])
def telegram_webhook():
    if request.headers.get("content-type") == "application/json":
        json_data = request.get_json()
        update = Update.de_json(json_data, application.bot)
        # Используем ThreadPoolExecutor для запуска асинхронной функции в синхронном роуте
        # Это предпочтительнее, чем вызов asyncio.run() внутри каждого вызова
        # Альтернатива: сделать роут асинхронным с помощью Quart, но Flask + ThreadPoolExecutor проще
        # asyncio.run(application.process_update(update)) # Не работает из-за инициализации
        # Вместо этого, инициализируем приложение заранее и используем process_update
        # Проверим, инициализировано ли приложение, хотя оно должно быть
        # asyncio.run внутри Flask-роута создает новый цикл, приложение в нем не инициализировано
        # Решение: инициализировать приложение до запуска Flask

        # Запускаем асинхронную обработку обновления в пуле потоков (на самом деле, это запускает цикл asyncio в потоке)
        # Это менее идеально, чем постоянный цикл, но работает в контексте синхронного Flask
        def run_async_process_update():
            # Создаем новый цикл asyncio для этого потока
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(application.process_update(update))
            finally:
                loop.close()

        # Создаем ThreadPoolExecutor или используем глобальный
        # Для простоты создадим его как глобальный, если еще не создан, и будем использовать
        # или просто запускать в пуле каждый раз
        with ThreadPoolExecutor(max_workers=1) as executor: # Пул на 1 поток для последовательности обновлений, если критично
            future = executor.submit(run_async_process_update)
            future.result() # Ждем завершения (опционально, можно и не ждать, но 200 быстрее вернется)

        return "OK", 200
    else:
        return "Invalid content type", 400

@app.route("/", methods=["GET"])
def health_check():
    return "✅ Бот жив! Webhook активен.", 200

# === Асинхронная функция для инициализации и запуска ===
async def setup_and_run():
    global application
    print(f"✅ Создаю и инициализирую Telegram Application...")
    application = PTBApplication.builder().token(BOT_TOKEN).build()

    # Добавляем обработчики
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Устанавливаем вебхук
    print(f"✅ Устанавливаю webhook на URL: {WEBHOOK_URL}")
    await application.bot.set_webhook(url=WEBHOOK_URL)

    # Инициализируем приложение (создает внутренние ресурсы)
    await application.initialize()
    # Запускаем приложение (обычно для polling, но инициализация важна и для webhook)
    # await application.start() # Не обязательно для webhook, start/stop нужны для внутренних задач, если таковые есть

    print(f"✅ Telegram Application инициализировано и webhook установлен.")

    # Запуск Flask-сервера из асинхронной функции
    # Используем threading для запуска Flask в отдельном потоке, чтобы не блокировать asyncio
    import threading
    def run_flask():
        app.run(host="0.0.0.0", port=PORT, use_reloader=False, debug=False) # use_reloader=False важно при запуске из другого потока

    print(f"🚀 Запускаю Flask-сервер на порту {PORT}...")
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True # Поток завершится, когда основной поток завершится
    flask_thread.start()
    print(f"✅ Flask-сервер запущен в отдельном потоке.")

    # Основной цикл asyncio должен продолжаться
    # В простом случае можно просто ждать, чтобы скрипт не завершался
    try:
        while True:
            await asyncio.sleep(3600) # Спит 1 час, затем снова спит, чтобы цикл не завершался
    except KeyboardInterrupt:
        print("\n🛑 Останавливаюсь...")
    finally:
        print("🛑 Останавливаю Telegram Application...")
        # await application.stop() # Если были запущены внутренние задачи
        await application.shutdown()
        print("✅ Telegram Application остановлено.")


# === ЗАПУСК ===
if __name__ == "__main__":
    # Запускаем асинхронную функцию настройки и запуска
    asyncio.run(setup_and_run())
