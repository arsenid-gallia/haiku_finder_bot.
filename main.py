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
main_loop = None # Будет хранить цикл событий из основного потока

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
    2. В виде подпоследовательности слов в одном тексте, проверяя гибкое 5-7-5.
    """
    print(f"🔍 Проверка текста на хокку: '{text[:30]}...'") # Добавить
    # === ОГРАНИЧЕНИЕ 1: Длина текста ===
    if len(text) > 200:
        print("📏 Текст слишком длинный, пропускаем") # Добавить
        return False

    # Разделяем текст на строки по символам новой строки
    lines = text.splitlines()
    # Убираем пустые строки и лишние пробелы
    lines = [line.strip() for line in lines if line.strip()]
    print(f"📝 Найдено строк: {len(lines)}") # Добавить

    # === Проверка: Если строк 3, проверяем как 3 строки ===
    if len(lines) == 3:
        print("🔍 Проверка по схеме 3 строки") # Добавить
        try: # Добавить try-except
            first_line_syllables = sum(count_syllables(word) for word in re.findall(r'[а-яА-ЯёЁ]+', lines[0]))
            second_line_syllables = sum(count_syllables(word) for word in re.findall(r'[а-яА-ЯёЁ]+', lines[1]))
            third_line_syllables = sum(count_syllables(word) for word in re.findall(r'[а-яА-ЯёЁ]+', lines[2]))
        except Exception as e:
            print(f"❌ Ошибка при подсчёте слогов в строках: {e}") # Добавить
            import traceback
            traceback.print_exc() # Печатаем стек вызова ошибки
            return False

        # Проверяем строгое соответствие 5-7-5
        if first_line_syllables == 5 and second_line_syllables == 7 and third_line_syllables == 5:
            print(f"✅ Найдено чёткое хокку из 3 строк: {first_line_syllables}-{second_line_syllables}-{third_line_syllables}")
            return True

        # Проверяем гибкое соответствие +/- 1 слог
        if (abs(first_line_syllables - 5) <= 1 and
            abs(second_line_syllables - 7) <= 1 and
            abs(third_line_syllables - 5) <= 1):
            print(f"✅ Найдено гибкое хокку из 3 строк: {first_line_syllables}-{second_line_syllables}-{third_line_syllables}")
            return True

    # === Проверка: Ищем подпоследовательность слов (старый алгоритм) ===
    # Очищаем текст от лишних символов и разбиваем на слова (используем исходный текст, а не lines)
    words = re.findall(r'[а-яА-ЯёЁ]+', text)
    print(f"🔍 Найдено слов для проверки подпоследовательности: {len(words)}") # Добавить
    if len(words) < 3: # Нужно хотя бы 3 слова
        print("📏 Недостаточно слов для хокку") # Добавить
        return False

    # Подсчитываем слоги для каждого слова
    syllables = [count_syllables(w) for w in words]
    n = len(syllables)
    print(f"🔍 Подсчитаны слоги, длина: {n}") # Добавить

    # Перебираем все возможные начальные позиции для поиска хокку
    for start in range(n):
        total_syllables = 0
        # Ищем первую часть (примерно 5 слогов)
        i = start
        while i < n and total_syllables < 6:
            total_syllables += syllables[i]
            i += 1
        # Если первая часть слишком короткая или длинная, пропускаем
        if total_syllables < 4 or total_syllables > 6:
            continue

        first_part_end = i - 1
        first_part_syllables = total_syllables

        # Ищем вторую часть (примерно 7 слогов)
        total_syllables = 0
        j = i
        while j < n and total_syllables < 8:
            total_syllables += syllables[j]
            j += 1
        # Если вторая часть слишком короткая или длинная, пропускаем
        if total_syllables < 6 or total_syllables > 8:
            continue

        second_part_end = j - 1
        second_part_syllables = total_syllables

        # Ищем третью часть (примерно 5 слогов)
        total_syllables = 0
        k = j
        while k < n and total_syllables < 6:
            total_syllables += syllables[k]
            k += 1
        # Если третья часть слишком короткая или длинная, пропускаем
        if total_syllables < 4 or total_syllables > 6:
            continue

        third_part_syllables = total_syllables

        # === ОГРАНИЧЕНИЕ 2: Количество слов в найденном хокку ===
        total_words_in_haiku = (first_part_end - start + 1) + (second_part_end - i + 1) + (k - j)
        if total_words_in_haiku > 15:
            continue

        # Если нашли подходящую комбинацию, возвращаем True
        print(f"✅ Найдено хокку в подпоследовательности: {first_part_syllables}-{second_part_syllables}-{third_part_syllables} слогов, {total_words_in_haiku} слов")
        return True

    print("❌ Хокку не найдено") # Добавить
    # Если ничего не нашли ни в одном из форматов
    return False

# === ОБРАБОТЧИК СООБЩЕНИЙ ===
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"🔄 handle_message вызван для сообщения от {update.effective_message.from_user.first_name if update.effective_message.from_user else 'Unknown'}") # Добавить
    msg = update.effective_message
    if msg and msg.text:
        print(f"📄 Текст сообщения: {msg.text}") # Добавить
        if is_haiku(msg.text):
            print(f"✅ Найдено хокку от {msg.from_user.first_name if msg.from_user else 'Unknown'}: {msg.text[:50]}...") # Убрать дублирование
            await msg.reply_text(random.choice(HAiku_RESPONSES))
            print("📤 Отправлен ответ") # Добавить
        else:
            print("❌ Хокку не найдено") # Добавить
    else:
        print("⚠️ Обновление не содержит текстового сообщения") # Добавить

# === Flask-приложение ===
app = Flask(__name__)

@app.route(WEBHOOK_PATH, methods=["POST"])
def telegram_webhook():
    print("🔄 [DEBUG] НАЧАЛО telegram_webhook") # Новый отладочный принт в самом начале
    try: # Обернём весь роут в try-except
        print("🔄 Получен запрос на /webhook")
        if request.headers.get("content-type") == "application/json":
            json_data = request.get_json()
            print(f"📥 Получены данные: {json_data}")
            # Используем application.bot, которое теперь гарантированно инициализировано
            # Проверим, не стало ли оно None вдруг
            if application is None or application.bot is None:
                 print("❌ [CRITICAL] application или application.bot is None!")
                 return "Internal Server Error", 500
            update = Update.de_json(json_data, application.bot)
            print(f"📋 Создан объект Update: {update.effective_message.text if update.effective_message else 'No text'}")

            # Создаём задачу для обработки обновления в основном цикле
            coro = application.process_update(update)
            print("📋 Создана корутина для обработки")

            # Запускаем корутину в основном цикле событий из другого потока
            future = asyncio.run_coroutine_threadsafe(coro, main_loop)
            print("📋 Корутина отправлена в цикл событий")
            try:
                # Ждем завершения задачи (опционально, можно и не ждать, но 200 быстрее вернется)
                result = future.result(timeout=10) # Таймаут 10 секунд
                print(f"✅ Обработка завершена, результат: {result}")
            except asyncio.TimeoutError:
                print("⚠️ Задача обработки обновления превысила таймаут.")
            except Exception as e:
                print(f"❌ Ошибка при обработке обновления в основном цикле: {e}")
                import traceback
                traceback.print_exc() # Печатаем стек вызова ошибки

            return "OK", 200
        else:
            print("❌ Неверный тип контента")
            return "Invalid content type", 400
    except Exception as e:
        print(f"❌ [CRITICAL] Необработанная ошибка в telegram_webhook: {e}")
        import traceback
        traceback.print_exc()
        return "Internal Server Error", 500

@app.route("/", methods=["GET"])
def health_check():
    return "✅ Бот жив! Webhook активен.", 200

# === Асинхронная функция для инициализации ===
async def initialize_application():
    global application, main_loop
    # Сохраняем текущий цикл событий (основной)
    main_loop = asyncio.get_running_loop()
    print(f"✅ Основной цикл событий получен в потоке {threading.current_thread().name}.")

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

# === ЗАПУСК ===
if __name__ == "__main__":
    # Создаём новый цикл событий
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Инициализируем приложение синхронно (ждём завершения)
    print("🚀 Инициализирую Telegram Application...")
    loop.run_until_complete(initialize_application())
    print("✅ Telegram Application инициализировано.")

    # Запускаем Flask-сервер в основном потоке (с тем же циклом)
    print(f"🚀 Запускаю Flask-сервер на порту {PORT}...")
    app.run(host="0.0.0.0", port=PORT, use_reloader=False, debug=False)
