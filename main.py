import os
import re
import random
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# === ОТВЕТЫ БОТА ===
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
        # Строка 1: 5 слогов
        s1, j = 0, i
        while j < n and s1 < 5:
            s1 += syllables[j]
            j += 1
        if s1 != 5:
            continue

        # Строка 2: 7 слогов
        s2, k = 0, j
        while k < n and s2 < 7:
            s2 += syllables[k]
            k += 1
        if s2 != 7:
            continue

        # Строка 3: 5 слогов
        s3, l = 0, k
        while l < n and s3 < 5:
            s3 += syllables[l]
            l += 1
        if s3 == 5:
            return True
    return False

# === ОБРАБОТКА СООБЩЕНИЙ ===
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not msg.text:
        return
    if is_haiku(msg.text):
        await msg.reply_text(random.choice(HAiku_RESPONSES))

# === ЗАПУСК ===
def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise ValueError("❌ BOT_TOKEN не задан! Добавьте его в Secrets на Render.")
    app = Application.builder().token(token).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("✅ Бот запущен и ищет хокку...")
    app.run_polling()

if __name__ == "__main__":
    main()
