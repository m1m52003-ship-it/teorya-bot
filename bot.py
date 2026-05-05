import random
import re
import os
from tempfile import NamedTemporaryFile

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from rapidfuzz import process
from PIL import Image
import pytesseract

from data_loader import load_questions_database, group_questions_by_topic


# =========================
# ضع التوكن هنا
# =========================
import os
TOKEN = os.getenv("TOKEN")


# إذا كان Tesseract مثبتًا في هذا المسار
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


# =========================
# تحميل البيانات
# =========================
questions_db = load_questions_database()
topics_db = group_questions_by_topic(questions_db)


# =========================
# أسماء الفصول
# =========================
def load_topics_names(file_path="topics.txt"):
    topics = {}

    if not os.path.exists(file_path):
        return topics

    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            parts = line.split(" ", 1)
            if len(parts) == 2:
                topics[parts[0]] = parts[1]

    return topics


topics_names = load_topics_names()


# =========================
# أدوات مساعدة
# =========================
LETTERS = ["أ", "ب", "ج", "د"]


def sort_topics_key(topic):
    try:
        return int(topic)
    except ValueError:
        return topic


def format_question(q):
    text = f"❓ السؤال {q['id']}\n\n{q['question']}\n\n"

    for i, option in enumerate(q["options"]):
        letter = LETTERS[i] if i < len(LETTERS) else str(i + 1)
        text += f"{letter}) {option}\n\n"

    return text.strip()


def find_question_by_id(q_id):
    for q in questions_db:
        if q["id"] == q_id:
            return q
    return None


def find_question_by_text(text):
    choices = [q["question"] for q in questions_db]
    result = process.extractOne(text, choices)

    if result and result[1] >= 60:
        return questions_db[result[2]], result[1]

    return None, 0


def extract_text_from_image(image_path):
    img = Image.open(image_path)
    return pytesseract.image_to_string(img, lang="ara+eng")


async def clear_old_buttons(query):
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass


# =========================
# عرض القائمة الرئيسية
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    keyboard = []

    for topic in sorted(topics_db.keys(), key=sort_topics_key):
        name = topics_names.get(topic, f"الفصل {topic}")
        keyboard.append([
            InlineKeyboardButton(f"📘 {name}", callback_data=f"topic_{topic}")
        ])

    keyboard.append([InlineKeyboardButton("🎓 اختبار نهائي", callback_data="exam")])
    keyboard.append([InlineKeyboardButton("🔎 البحث عن سؤال", callback_data="search")])

    text = "🚗 بوت التربية المرورية\n\nاختر من القائمة:"

    if update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        query = update.callback_query
        await query.answer()
        await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


# =========================
# إرسال سؤال
# =========================
async def send_question(chat_id, q, context):
    question_text = format_question(q)

    keyboard = [
        [
            InlineKeyboardButton("أ", callback_data="ans_0"),
            InlineKeyboardButton("ب", callback_data="ans_1"),
            InlineKeyboardButton("ج", callback_data="ans_2"),
            InlineKeyboardButton("د", callback_data="ans_3"),
        ],
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="home")]
    ]

    if q.get("image"):
        try:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=open(q["image"], "rb"),
                caption=f"صورة السؤال {q['id']}"
            )
        except Exception:
            pass

    await context.bot.send_message(
        chat_id=chat_id,
        text=question_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================
# اختيار من القائمة
# =========================
async def handle_menu_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data.startswith("topic_"):
        topic = data.replace("topic_", "")
        qs = topics_db.get(topic, []).copy()
        random.shuffle(qs)

        context.user_data["mode"] = "topic"
        context.user_data["qs"] = qs
        context.user_data["i"] = 0
        context.user_data["score"] = 0

        await clear_old_buttons(query)
        await send_current_question(update, context)

    elif data == "exam":
        qs = random.sample(questions_db, min(30, len(questions_db)))

        context.user_data["mode"] = "exam"
        context.user_data["qs"] = qs
        context.user_data["i"] = 0
        context.user_data["score"] = 0

        await clear_old_buttons(query)
        await query.message.reply_text("🎓 بدأ الاختبار النهائي: 30 سؤالًا")
        await send_current_question(update, context)

    elif data == "search":
        context.user_data["mode"] = "search"

        await clear_old_buttons(query)
        await query.message.reply_text(
            "🔎 أرسل رقم السؤال مثل:\n"
            "5.12\n\n"
            "أو أرسل نصًا من السؤال.\n"
            "أو أرسل صورة تحتوي على السؤال."
        )


# =========================
# إرسال السؤال الحالي
# =========================
async def send_current_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    qs = context.user_data.get("qs", [])
    i = context.user_data.get("i", 0)

    if i >= len(qs):
        await finish_quiz(update, context)
        return

    q = qs[i]
    await send_question(update.effective_chat.id, q, context)


# =========================
# معالجة الإجابة
# =========================
async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if "qs" not in context.user_data:
        await query.message.reply_text("اضغط /start للبدء من جديد.")
        return

    qs = context.user_data["qs"]
    i = context.user_data["i"]

    if i >= len(qs):
        await finish_quiz(update, context)
        return

    q = qs[i]
    user_index = int(query.data.replace("ans_", ""))
    correct_index = q["answer_index"]

    await clear_old_buttons(query)

    if user_index == correct_index:
        context.user_data["score"] += 1
        result_text = "✅ إجابة صحيحة!"
    else:
        correct_letter = q["answer_letter"]
        correct_option = q["options"][correct_index]
        result_text = (
            "❌ إجابة غير صحيحة\n\n"
            f"✅ الإجابة الصحيحة: {correct_letter}\n"
            f"{correct_option}"
        )

    context.user_data["i"] += 1

    answered = context.user_data["i"]
    score = context.user_data["score"]

    result_text += f"\n\n📊 نتيجتك الحالية: {score} من {answered}"

    keyboard = [
        [InlineKeyboardButton("➡️ سؤال آخر", callback_data="next")],
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="home")]
    ]

    await query.message.reply_text(
        result_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================
# السؤال التالي
# =========================
async def handle_next(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await clear_old_buttons(query)
    await send_current_question(update, context)


# =========================
# إنهاء الاختبار
# =========================
async def finish_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    score = context.user_data.get("score", 0)
    total = len(context.user_data.get("qs", []))
    mode = context.user_data.get("mode")

    if mode == "exam":
        if score > 24:
            text = f"🎉 مبروك! لقد تجاوزت الاختبار.\n\nالنتيجة: {score} من {total}"
        else:
            text = f"😔 للأسف، لست مستعدًا بعد. حاول مرة أخرى.\n\nالنتيجة: {score} من {total}"
    else:
        text = f"📊 انتهى التدريب.\n\nنتيجتك: {score} من {total}"

    keyboard = [[InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="home")]]

    await update.effective_chat.send_message(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================
# الرجوع للقائمة الرئيسية
# =========================
async def handle_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await clear_old_buttons(query)
    await start(update, context)


# =========================
# البحث بنص أو رقم
# =========================
async def handle_text_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("mode") != "search":
        return

    text = update.message.text.strip()

    if re.fullmatch(r"\d+\.\d+", text):
        q = find_question_by_id(text)

        if not q:
            await update.message.reply_text("❌ لم أجد سؤالًا بهذا الرقم.")
            return
    else:
        q, score = find_question_by_text(text)

        if not q:
            await update.message.reply_text("❌ لم أجد سؤالًا مطابقًا للنص.")
            return

        await update.message.reply_text(f"🔎 أقرب سؤال مطابق: {q['id']}")

    context.user_data["mode"] = "search_result"
    context.user_data["qs"] = [q]
    context.user_data["i"] = 0
    context.user_data["score"] = 0

    await send_current_question(update, context)


# =========================
# البحث بالصورة
# =========================
async def handle_photo_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("mode") != "search":
        return

    photo = update.message.photo[-1]
    file = await photo.get_file()

    with NamedTemporaryFile(delete=False, suffix=".jpg") as temp:
        temp_path = temp.name

    await file.download_to_drive(temp_path)

    try:
        extracted_text = extract_text_from_image(temp_path)
    except Exception:
        await update.message.reply_text(
            "❌ لم أتمكن من قراءة النص من الصورة.\n"
            "تأكد أن Tesseract مثبت وأن الصورة واضحة."
        )
        return
    finally:
        try:
            os.remove(temp_path)
        except Exception:
            pass

    q, score = find_question_by_text(extracted_text)

    if not q:
        await update.message.reply_text("❌ لم أجد سؤالًا مطابقًا للصورة.")
        return

    await update.message.reply_text(f"🔎 وجدت أقرب سؤال مطابق: {q['id']}")

    context.user_data["mode"] = "search_result"
    context.user_data["qs"] = [q]
    context.user_data["i"] = 0
    context.user_data["score"] = 0

    await send_current_question(update, context)


# =========================
# تشغيل البوت
# =========================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    app.add_handler(CallbackQueryHandler(handle_menu_choice, pattern="^(topic_|exam|search)"))
    app.add_handler(CallbackQueryHandler(handle_answer, pattern="^ans_[0-3]$"))
    app.add_handler(CallbackQueryHandler(handle_next, pattern="^next$"))
    app.add_handler(CallbackQueryHandler(handle_home, pattern="^home$"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_search))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo_search))

    print("✅ البوت يعمل الآن...")
    app.run_polling()


if __name__ == "__main__":
    main()
