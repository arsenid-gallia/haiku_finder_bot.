import os
import re
import random
import asyncio
import threading # Импортируем threading на уровне модуля
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

# Глобальная переменная для хранения приложения PTB и цикла событий
application = None
main_loop = None # Будет хранить цикл событий из основного потока

# === ОТВЕТЫ НА ХОККУ ===
HAiku_RESPONSES = [
    "нифига ты самурай",
    "вот это хокку!",
    "ты поэт, братишка",
    "сакура расцвела в твоих словах",
    "даже цикада замолчала",
    "с этим хокку на устах последний самурай сделал харакири",
    "У нас в Японии за такие слова и вакидзаси под ребро получить можно",
    "если бы я так умел, я бы сейчас был суперсегун",
    "От твоих слов у меня волосы в носу зашелестели как трава от осеннего ветра",
    "под сакэ сойдет",
    "твои хокку возбуждают меня больше, чем ношенные трусы старшеклассницы",
    "Банку EBOSHI этому ронину выдайте",
    "от твоего хокку у меня разрез глаз уже стал",
    "Кружка за кружкой я уже не самурай, я сакэзавр",
    "Самурай с котиком подобен самураю без котика, но счастливее",
    "Строг этикет самурая, но делать сеппуку поевши пельменей, обидно вдвойне",
    "Я этого самурая в Хоккайдо видал, деревянными катанами торгует!",
    "Видел падающую сакуру, это ты уронил?",
    "выдайте ему миска роллы и 2д жена",
    "У меня аж танто привстал",
    "Ты небось и бусидо наизусть знаешь",
    "в жопу раз или расенган в глаз?"
    
    
]

# === ПОДСЧЁТ СЛОГОВ (только русский) ===
def count_syllables(word):
    """Подсчёт слогов в слове, игнорируя не-буквенные символы."""
    # Оставляем только буквы
    word = ''.join(c.lower() for c in word if c.isalpha())
    vowels = "аеёиоуыэюя"
    count = 0
    prev_vowel = False
    for ch in word:
        is_vowel = ch in vowels
        if is_vowel and not prev_vowel:
            count += 1
        prev_vowel = is_vowel
    return max(1, count) # Минимум 1 слог

# === ПОИСК ХОККУ В ЛЮБОМ ФОРМАТЕ ===
def is_haiku(text):
    """
    Проверяет, является ли текст хокку (5-7-5 слогов) в любом формате.
    Учитывает переносы строк и пунктуацию.
    """
    # Разделяем текст на строки по символам новой строки
    lines = text.splitlines()
    # Убираем пустые строки и лишние пробелы
    lines = [line.strip() for line in lines if line.strip()]

    # Если строк меньше 3, попробуем найти 5-7-5 в одной строке (как было раньше)
    if len(lines) < 3:
        # Объединяем все строки в одну и используем старую логику
        combined_text = ' '.join(lines)
        words = re.findall(r'[а-яА-ЯёЁ]+', combined_text)
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

    # Если строк 3 или больше, проверяем первую, вторую и третью строки
    else:
        # Берем первые три строки
        first_line = lines[0]
        second_line = lines[1]
        third_line = lines[2]

        # Подсчитываем слоги в каждой строке
        first_syllables = sum(count_syllables(word) for word in re.findall(r'[а-яА-ЯёЁ]+', first_line))
        second_syllables = sum(count_syllables(word) for word in re.findall(r'[а-яА-ЯёЁ]+', second_line))
        third_syllables = sum(count_syllables(word) for word in re.findall(r'[а-яА-ЯёЁ]+', third_line))

        # Проверяем, равны ли они 5, 7, 5
        if first_syllables == 5 and second_syllables == 7 and third_syllables == 5:
            return True

        # Гибкая проверка: допускаем отклонение +/- 1 слог
        if (abs(first_syllables - 5) <= 1 and
            abs(second_syllables - 7) <= 1 and
            abs(third_syllables - 5) <= 1):
            return True

        # Дополнительно: если строк больше 3, можно проверить любые три подряд строки
        # Но для простоты оставим пока только первые три

        return False

# === ОБРАБОТЧИК СООБЩЕНИЙ ===
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if msg and msg.text and is_haiku(msg.text):
        print(f"✅ Найдено хокку от {msg.from_user.first_name if msg.from_user else 'Unknown'}: {msg.text[:50]}...")
        await msg.reply_text(random.choice(HAiku_RESPONSES))

# === Flask-приложение ===
app = Flask(__name__)

@app.route(WEBHOOK_PATH, methods=["POST"])
def telegram_webhook():
    if request.headers.get("content-type") == "application/json":
        json_data = request.get_json()
        update = Update.de_json(json_data, application.bot)

        # Создаём задачу для обработки обновления в основном цикле
        coro = application.process_update(update)

        # Запускаем корутину в основном цикле событий из другого потока
        future = asyncio.run_coroutine_threadsafe(coro, main_loop)
        try:
            # Ждем завершения задачи (опционально, можно и не ждать, но 200 быстрее вернется)
            future.result(timeout=10) # Таймаут 10 секунд
        except asyncio.TimeoutError:
            print("⚠️ Задача обработки обновления превысила таймаут.")
        except Exception as e:
            print(f"❌ Ошибка при обработке обновления в основном цикле: {e}")

        return "OK", 200
    else:
        return "Invalid content type", 400

@app.route("/", methods=["GET"])
def health_check():
    return "✅ Бот жив! Webhook активен.", 200

# === Асинхронная функция для инициализации и запуска ===
async def setup_and_run():
    global application, main_loop
    # Сохраняем текущий цикл событий (основной)
    main_loop = asyncio.get_running_loop()
    print(f"✅ Основной цикл событий получен в потоке {threading.current_thread().name}.") # Теперь threading доступен

    print(f"✅ Создаю и инициализирую Telegram Application...")
    application = PTBApplication.builder().token(BOT_TOKEN).build()

    # Добавляем обработчики
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Устанавливаем вебхук
    print(f"✅ Устанавливаю webhook на URL: {WEBHOOK_URL}")
    await application.bot.set_webhook(url=WEBHOOK_URL)

    # Инициализируем приложение (создает внутренние ресурсы, включая HTTP-клиент)
    await application.initialize()
    print(f"✅ Telegram Application инициализировано и webhook установлен.")

    # Запуск Flask-сервера из асинхронной функции
    # threading уже импортирован
    def run_flask():
        app.run(host="0.0.0.0", port=PORT, use_reloader=False, debug=False)

    print(f"🚀 Запускаю Flask-сервер на порту {PORT}...")
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    print(f"✅ Flask-сервер запущен в отдельном потоке {flask_thread.name}.")

    # Основной цикл asyncio должен продолжаться
    try:
        while True:
            await asyncio.sleep(3600) # Спит 1 час
    except KeyboardInterrupt:
        print("\n🛑 Останавливаюсь...")
    finally:
        print("🛑 Останавливаю Telegram Application...")
        await application.shutdown()
        print("✅ Telegram Application остановлено.")


# === ЗАПУСК ===
if __name__ == "__main__":
    asyncio.run(setup_and_run())
