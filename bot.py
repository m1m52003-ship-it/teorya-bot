import streamlit as st  # السطر الأهم لحل مشكلة NameError
import re
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from rapidfuzz import fuzz
from docx import Document

# ====== الإعدادات ======
TOKEN=st.secrets["TOKEN"]

def normalize_text(text):
    text = text.lower()
    text = re.sub(r'[^\w\s.]', '', text) # نحافظ على النقطة لأرقام الأسئلة
    return " ".join(text.split())

# ====== 1. قراءة مفتاح الإجابات من الملف الجديد ======
def load_answers():
    try:
        ans_doc = Document("answer.docx")
        ans_map = {}
        for table in ans_doc.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells]
                if len(cells) >= 2:
                    # تنظيف الأرقام (مثلاً تحويل 5.1 إلى 5.1)
                    q_num = cells[1] if re.match(r'^\d', cells[1]) else cells[0]
                    a_val = cells[0] if q_num == cells[1] else cells[1]
                    ans_map[q_num] = a_val
        return ans_map
    except:
        print("❌ خطأ: لم يتم العثور على ملف answer.docx")
        return {}

# ====== 2. قراءة الأسئلة من الملف الأصلي ======
def load_questions(ans_map):
    doc = Document("ttt.docx")
    final_data = []
    
    # استخراج النصوص من الفقرات والجداول
    full_content = []
    for p in doc.paragraphs: full_content.append(p.text)
    for table in doc.tables:
        for row in table.rows:
            full_content.append(" ".join([c.text for c in row.cells]))
    
    full_text = "\n".join(full_content)
    
    # البحث عن نمط الرقم (مثل 5.1 أو 15.1) يتبعه نص
    pattern = r'(\d+\.\d+)\s+(.*?)(?=\n\d+\.\d+|\Z)'
    matches = re.findall(pattern, full_text, re.DOTALL)
    
    for m in matches:
        q_id = m[0].strip()
        final_data.append({
            "id": q_id,
            "text": m[1].strip(),
            "norm": normalize_text(m[1]),
            "answer": ans_map.get(q_id, "❌ غير متوفرة")
        })
    return final_data

print("⏳ جاري ربط الملفين...")
answers = load_answers()
data_list = load_questions(answers)
print(f"✅ تم ربط {len(data_list)} سؤال بنجاح.")

# ====== 3. معالجة الرسائل ======
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    
    # البحث بالرقم
    for q in data_list:
        if query == q['id']:
            await update.message.reply_text(f"📌 **سؤال {q['id']}:**\n{q['text']}\n\n✅ **الإجابة:** {q['answer']}", parse_mode="Markdown")
            return

    # البحث بالنص
    best_q = None
    max_s = 0
    for q in data_list:
        s = fuzz.partial_ratio(normalize_text(query), q['norm'])
        if s > max_s:
            max_s = s
            best_q = q
    
    if best_q and max_s > 75:
        await update.message.reply_text(f"📌 **سؤال {best_q['id']}:**\n{best_q['text']}\n\n✅ **الإجابة:** {best_q['answer']}", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ لم أجد السؤال. تأكد من كتابة الرقم بشكل صحيح (مثل 5.1).")

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT, handle))
    app.run_polling()
