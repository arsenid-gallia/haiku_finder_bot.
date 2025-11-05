import os
import re
import random
import asyncio
import threading
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
ptb_loop = None # Цикл событий для PTB (в отдельном потоке)

# === Временная метка запуска бота ===
BOT_START_TIME = None # Будет установлено при запуске

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

# === ПОИСК ХОККУ В ЛЮБОМ ФОРМАТЕ (ГИБКАЯ ВЕРСИЯ С ОГРАНИЧЕНИЯМИ И ПРОВЕРКОЙ СТРОК) ===
def is_haiku(text):
    """
    Проверяет, является ли текст "хокку" (имеет 17 слогов, которые можно разделить на 5-7-5).
    Игнорирует пунктуацию, пробелы, регистр.
    Ищет хокку в следующих форматах:
    1. В виде 3 строк (разделённых \n), проверяя строгое и гибкое 5-7-5.
    2. В виде полного текста сообщения, разбитого на 3 части по словам (без пропусков слов).
    """

    print(f"🔍 Проверка текста на хокку: '{text[:30]}...'", flush=True) # flush=True
    # === ОГРАНИЧЕНИЕ 1: Длина текста ===
    if len(text) > 200:
        print("📏 Текст слишком длинный, пропускаем", flush=True) # flush=True
        return False

    # Разделяем текст на строки по символам новой строки
    lines = text.splitlines()
    # Убираем пустые строки и лишние пробелы
    lines = [line.strip() for line in lines if line.strip()]
    print(f"📝 Найдено строк: {len(lines)}", flush=True) # flush=True

    # === Проверка: Если строк 3, проверяем как 3 строки ===
    if len(lines) == 3:
        print("🔍 Проверка по схеме 3 строки", flush=True) # flush=True
        try: # flush=True
            first_line_syllables = sum(count_syllables(word) for word in re.findall(r'[а-яА-ЯёЁ]+', lines[0]))
            second_line_syllables = sum(count_syllables(word) for word in re.findall(r'[а-яА-ЯёЁ]+', lines[1]))
            third_line_syllables = sum(count_syllables(word) for word in re.findall(r'[а-яА-ЯёЁ]+', lines[2]))
        except Exception as e:
            print(f"❌ Ошибка при подсчёте слогов в строках: {e}", flush=True) # flush=True
            import traceback
            traceback.print_exc() # flush=True
            return False

        # Проверяем строгое соответствие 5-7-5
        if first_line_syllables == 5 and second_line_syllables == 7 and third_line_syllables == 5:
            print(f"✅ Найдено чёткое хокку из 3 строк: {first_line_syllables}-{second_line_syllables}-{third_line_syllables}", flush=True) # flush=True
            return True

        # Проверяем гибкое соответствие +/- 1 слог
        if (abs(first_line_syllables - 5) <= 1 and
            abs(second_line_syllables - 7) <= 1 and
            abs(third_line_syllables - 5) <= 1):
            print(f"✅ Найдено гибкое хокку из 3 строк: {first_line_syllables}-{second_line_syllables}-{third_line_syllables}", flush=True) # flush=True
            return True

    # === Проверка: Ищем хокку в полном тексте сообщения (без пропусков слов) ===
    # Очищаем текст от лишних символов и разбиваем на слова
    words = re.findall(r'[а-яА-ЯёЁ]+', text)
    print(f"🔍 Найдено слов для проверки: {len(words)}", flush=True) # flush=True
    if len(words) < 3: # Нужно хотя бы 3 слова
        print("📏 Недостаточно слов для хокку", flush=True) # flush=True
        return False

    # Подсчитываем слоги для каждого слова
    syllables = [count_syllables(w) for w in words]
    n = len(syllables)
    print(f"🔍 Подсчитаны слоги, длина: {n}", flush=True) # flush=True

    # Перебираем все возможные точки разбиения на 3 части
    # i - индекс конца первой части (включительно)
    # j - индекс конца второй части (включительно)
    for i in range(n-2): # Первая часть должна содержать хотя бы одно слово, оставить место для двух других
        total_syllables_first = sum(syllables[:i+1]) # Сумма слогов в словах от 0 до i
        if total_syllables_first != 5: # Строго 5
            continue

        for j in range(i+1, n-1): # Вторая часть начинается с i+1, должна содержать хотя бы одно слово, оставить место для третьей
            total_syllables_second = sum(syllables[i+1:j+1]) # Сумма слогов в словах от i+1 до j
            if total_syllables_second != 7: # Строго 7
                continue

            total_syllables_third = sum(syllables[j+1:]) # Сумма слогов в словах от j+1 до конца
            if total_syllables_third != 5: # Строго 5
                continue

            # Если нашли подходящее разбиение, возвращаем True
            print(f"✅ Найдено хокку в полном тексте: {total_syllables_first}-{total_syllables_second}-{total_syllables_third} слогов, {len(words)} слов", flush=True) # flush=True
            return True

    print("❌ Хокку не найдено", flush=True) # flush=True
    # Если ничего не нашли ни в одном из форматов
    return False

# === ОБРАБОТЧИК СООБЩЕНИЙ ===
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Получаем время отправки сообщения
    msg_time = update.effective_message.date.timestamp()
    # Проверяем, было ли сообщение отправлено до запуска бота
    if BOT_START_TIME and msg_time < BOT_START_TIME:
        print(f"🕒 Сообщение отправлено до запуска бота, игнорируем. Время сообщения: {msg_time}, Время запуска: {BOT_START_TIME}", flush=True)
        return

    print(f"🔄 handle_message вызван для сообщения от {update.effective_message.from_user.first_name if update.effective_message.from_user else 'Unknown'}", flush=True) # flush=True
    msg = update.effective_message
    if msg and msg.text:
        print(f"📄 Текст сообщения: {msg.text}", flush=True) # flush=True
        if is_haiku(msg.text):
            print(f"✅ Найдено хокку от {msg.from_user.first_name if msg.from_user else 'Unknown'}: {msg.text[:50]}...", flush=True) # flush=True
            await msg.reply_text(random.choice(HAiku_RESPONSES))
            print("📤 Отправлен ответ", flush=True) # flush=True
        else:
            print("❌ Хокку не найдено", flush=True) # flush=True
    else:
        print("⚠️ Обновление не содержит текстового сообщения", flush=True) # flush=True

# === Flask-приложение ===
app = Flask(__name__)

@app.route(WEBHOOK_PATH, methods=["POST"])
def telegram_webhook():
    print("🔄 [DEBUG] НАЧАЛО telegram_webhook (в потоке Flask)", flush=True) # flush=True
    try:
        if request.headers.get("content-type") == "application/json":
            json_data = request.get_json()
            print(f"📥 Получены данные: {json_data}", flush=True) # flush=True
            # Используем application.bot, которое инициализировано в другом потоке
            # Проверим, не стало ли оно None вдруг
            if application is None or application.bot is None:
                 print("❌ [CRITICAL] application или application.bot is None!", flush=True) # flush=True
                 return "Internal Server Error", 500
            update = Update.de_json(json_data, application.bot)
            print(f"📋 Создан объект Update: {update.effective_message.text if update.effective_message else 'No text'}", flush=True) # flush=True

            # Создаём задачу для обработки обновления в основном цикле PTB
            coro = application.process_update(update)
            print("📋 Создана корутина для обработки", flush=True) # flush=True

            # Запускаем корутину в асинхронном цикле событий из *другого* потока (ptb_loop)
            future = asyncio.run_coroutine_threadsafe(coro, ptb_loop)
            print("📋 Корутина отправлена в цикл событий PTB", flush=True) # flush=True
            try:
                # Ждем завершения задачи (опционально, можно и не ждать, но 200 быстрее вернется)
                result = future.result(timeout=10) # Таймаут 10 секунд
                print(f"✅ Обработка завершена, результат: {result}", flush=True) # flush=True
            except asyncio.TimeoutError:
                print("⚠️ Задача обработки обновления превысила таймаут.", flush=True) # flush=True
            except Exception as e:
                print(f"❌ Ошибка при обработке обновления в основном цикле: {e}", flush=True) # flush=True
                import traceback
                traceback.print_exc() # flush=True

            return "OK", 200
        else:
            print("❌ Неверный тип контента", flush=True) # flush=True
            return "Invalid content type", 400
    except Exception as e:
        print(f"❌ [CRITICAL] Необработанная ошибка в telegram_webhook: {e}", flush=True) # flush=True
        import traceback
        traceback.print_exc() # flush=True
        return "Internal Server Error", 500

@app.route("/", methods=["GET"])
def health_check():
    return "✅ Бот жив! Webhook активен.", 200

# === Асинхронная функция для инициализации в отдельном потоке ===
async def setup_and_run_ptb():
    global application, ptb_loop
    # Сохраняем текущий цикл событий (из потока PTB)
    ptb_loop = asyncio.get_running_loop()
    print(f"✅ Цикл событий PTB получен в потоке {threading.current_thread().name}.", flush=True) # flush=True

    print(f"✅ Создаю и инициализирую Telegram Application...", flush=True) # flush=True
    application = PTBApplication.builder().token(BOT_TOKEN).build()

    # Добавляем обработчики
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Устанавливаем вебхук
    print(f"✅ Устанавливаю webhook на URL: {WEBHOOK_URL}", flush=True) # flush=True
    await application.bot.set_webhook(url=WEBHOOK_URL)

    # Инициализируем приложение (создает внутренние ресурсы, включая HTTP-клиент)
    await application.initialize()
    print(f"✅ Telegram Application инициализировано и webhook установлен.", flush=True) # flush=True

    # Устанавливаем временную метку запуска бота
    global BOT_START_TIME
    BOT_START_TIME = asyncio.get_event_loop().time()
    print(f"⏱️ Временная метка запуска бота установлена: {BOT_START_TIME}", flush=True) # flush=True

    # Ждём бесконечно в этом цикле (в потоке PTB)
    # Это позволяет циклу оставаться активным для обработки через run_coroutine_threadsafe
    try:
        while True:
            await asyncio.sleep(3600) # Спит 1 час, затем снова спит
    except KeyboardInterrupt:
        print("\n🛑 Останавливаюсь из потока PTB...", flush=True) # flush=True
    finally:
        print("🛑 Останавливаю Telegram Application из потока PTB...", flush=True) # flush=True
        await application.shutdown()
        print("✅ Telegram Application остановлено из потока PTB.", flush=True) # flush=True


# === ЗАПУСК ===
if __name__ == "__main__":
    # Запускаем асинхронную настройку PTB в ОТДЕЛЬНОМ потоке
    import threading
    def run_ptb():
        # Создаём новый цикл asyncio для потока PTB
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(setup_and_run_ptb())
        finally:
            loop.close()

    print(f"🚀 Запускаю поток с Telegram Application...", flush=True) # flush=True
    ptb_thread = threading.Thread(target=run_ptb, name="PTB_Thread")
    ptb_thread.daemon = True # Важно: поток завершится, когда основной скрипт завершится
    ptb_thread.start()

    # Ждём короткое время, чтобы PTB инициализировалась
    import time
    time.sleep(2)

    # Проверяем, инициализирована ли application
    if application is None:
        print("❌ [CRITICAL] Telegram Application не была инициализирована вовремя!", flush=True) # flush=True
        exit(1)

    # Запускаем Flask-сервер в основном потоке (после запуска потока PTB)
    print(f"🚀 Запускаю Flask-сервер на порту {PORT} в основном потоке...", flush=True) # flush=True
    app.run(host="0.0.0.0", port=PORT, use_reloader=False, debug=False)
