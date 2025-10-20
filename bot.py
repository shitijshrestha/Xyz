import telebot
import subprocess
import threading
import os
import time
import math
import io
from functools import wraps
from telebot.apihelper import ApiTelegramException

# ---------------- CONFIG ----------------
BOT_TOKEN = "7994446557:AAHoC-lsN137MmZfVMHiTWHRXRBHCFlwCKA"
bot = telebot.TeleBot(BOT_TOKEN, num_threads=30)

ADMIN_IDS = [6403142441]  # Change to your Telegram ID
MAX_SIZE_MB = 50  # Telegram video part limit in MB

active_recordings = {}  # chat_id -> {msg_id: process_info}
lock = threading.Lock()  # for thread-safe updates

# ---------------- DECORATORS ----------------
def admin_only(func):
    @wraps(func)
    def wrapped(message, *args, **kwargs):
        if message.from_user.id in ADMIN_IDS:
            return func(message, *args, **kwargs)
        else:
            bot.reply_to(message, "⛔ केवल एडमिन ही इस कमांड का उपयोग कर सकते हैं!")
    return wrapped

def safe_edit_message(text, chat_id, message_id, **kwargs):
    if len(text) > 4096:
        text = text[:4090] + "..."
    try:
        bot.edit_message_text(text, chat_id, message_id, **kwargs)
    except ApiTelegramException:
        pass

# ---------------- COMMANDS ----------------
@bot.message_handler(commands=['start'])
@admin_only
def start(message):
    bot.reply_to(message, "👋 बॉट चालू है! उपयोग करें /help सभी कमांड देखने के लिए।")

@bot.message_handler(commands=['help'])
@admin_only
def help_command(message):
    text = """
📌 **उपलब्ध कमांड्स**

/start - बॉट शुरू करें  
/help - सभी कमांड दिखाएं  
/status - बॉट की स्थिति देखें  
/myrecordings - आपकी सक्रिय रिकॉर्डिंग्स  
/record <URL> <hh:mm:ss> <title> - स्ट्रीम रिकॉर्ड करें  
/cancel - किसी रिकॉर्डिंग को रद्द करें (रिकॉर्डिंग मेसेज को reply करें)  
/screenshot <URL> - एक स्क्रीनशॉट लें  

**Admin Commands**  
/allrecordings - सभी सक्रिय रिकॉर्डिंग्स देखें  
/broadcast <msg> - सभी एडमिन को मैसेज भेजें  

**उदाहरण:**  
/record https://url.m3u8 00:10:00 Testing
"""
    bot.reply_to(message, text)

@bot.message_handler(commands=['status'])
@admin_only
def status(message):
    total = sum(len(r) for r in active_recordings.values())
    bot.reply_to(message, f"✅ बॉट चालू है। सक्रिय रिकॉर्डिंग्स: {total}")

@bot.message_handler(commands=['myrecordings'])
@admin_only
def myrecordings(message):
    chat_id = message.chat.id
    if chat_id in active_recordings and active_recordings[chat_id]:
        text = "🎬 आपकी सक्रिय रिकॉर्डिंग्स:\n"
        for msg_id, info in active_recordings[chat_id].items():
            text += f"- {info['title']} (PID: {info['proc'].pid})\n"
    else:
        text = "कोई सक्रिय रिकॉर्डिंग नहीं मिली।"
    bot.reply_to(message, text)

@bot.message_handler(commands=['allrecordings'])
@admin_only
def allrecordings(message):
    total = sum(len(r) for r in active_recordings.values())
    if total == 0:
        bot.reply_to(message, "कोई सक्रिय रिकॉर्डिंग नहीं है।")
        return
    text = f"🎬 सभी सक्रिय रिकॉर्डिंग्स ({total}):\n"
    for chat_id, recs in active_recordings.items():
        text += f"\nChat {chat_id}:\n"
        for msg_id, info in recs.items():
            text += f"- {info['title']} (PID: {info['proc'].pid})\n"
    bot.reply_to(message, text)

@bot.message_handler(commands=['broadcast'])
@admin_only
def broadcast(message):
    try:
        text = message.text.split(None, 1)[1]
        for admin in ADMIN_IDS:
            bot.send_message(admin, f"📢 Broadcast:\n{text}")
        bot.reply_to(message, "✅ ब्रॉडकास्ट भेज दिया गया।")
    except:
        bot.reply_to(message, "Usage: /broadcast <message>")

@bot.message_handler(commands=['screenshot'])
@admin_only
def screenshot(message):
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /screenshot <URL>")
        return
    url = args[1]
    filename = f"screenshot_{int(time.time())}.jpg"
    cmd = ['ffmpeg', '-y', '-i', url, '-vframes', '1', filename]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if os.path.exists(filename):
        with open(filename, 'rb') as f:
            bot.send_photo(message.chat.id, f, caption=f"📸 Screenshot from {url}")
        os.remove(filename)
    else:
        bot.reply_to(message, "❌ Screenshot failed.")

# ---------------- RECORDING ----------------
@bot.message_handler(commands=['record'])
@admin_only
def record(message):
    args = message.text.split()
    if len(args) < 4:
        bot.reply_to(message, "Usage: /record <URL> <hh:mm:ss> <title>")
        return
    url = args[1]
    try:
        h, m, s = map(int, args[2].split(":"))
        duration_sec = h * 3600 + m * 60 + s
    except:
        bot.reply_to(message, "❌ Invalid duration format. Use hh:mm:ss")
        return
    title = " ".join(args[3:])
    output_file = f"rec_{message.chat.id}_{int(time.time())}.mp4"
    sent_msg = bot.reply_to(message, f"🎬 '{title}' की रिकॉर्डिंग शुरू हुई ({args[2]})")
    msg_id = sent_msg.message_id

    threading.Thread(
        target=record_stream,
        args=(message.chat.id, msg_id, url, duration_sec, title, output_file),
        daemon=True
    ).start()

@bot.message_handler(commands=['cancel'])
@admin_only
def cancel(message):
    if not message.reply_to_message:
        bot.reply_to(message, "⚠️ रिकॉर्डिंग को रद्द करने के लिए, रिकॉर्डिंग मेसेज पर reply करें।")
        return
    chat_id = message.chat.id
    msg_id = message.reply_to_message.message_id
    with lock:
        if chat_id in active_recordings and msg_id in active_recordings[chat_id]:
            proc = active_recordings[chat_id][msg_id]['proc']
            proc.terminate()
            del active_recordings[chat_id][msg_id]
            bot.reply_to(message, "❌ रिकॉर्डिंग रद्द कर दी गई।")
        else:
            bot.reply_to(message, "⚠️ कोई सक्रिय रिकॉर्डिंग नहीं मिली।")

def record_stream(chat_id, msg_id, url, duration_sec, title, output_file):
    with lock:
        if chat_id not in active_recordings:
            active_recordings[chat_id] = {}

    cmd = ['ffmpeg', '-y', '-i', url, '-t', str(duration_sec), '-c', 'copy', output_file]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    with lock:
        active_recordings[chat_id][msg_id] = {'proc': proc, 'title': title}

    proc.wait()

    if os.path.exists(output_file):
        safe_edit_message("✅ रिकॉर्डिंग पूरी हुई। अब अपलोड हो रही है...", chat_id, msg_id)
        split_and_send(chat_id, msg_id, output_file, title, duration_sec)
    else:
        safe_edit_message("❌ रिकॉर्डिंग विफल रही।", chat_id, msg_id)

    with lock:
        if chat_id in active_recordings and msg_id in active_recordings[chat_id]:
            del active_recordings[chat_id][msg_id]
        if chat_id in active_recordings and not active_recordings[chat_id]:
            del active_recordings[chat_id]

# ---------------- UPLOAD ----------------
def split_and_send(chat_id, msg_id, file_path, title, duration_sec):
    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    if file_size_mb <= MAX_SIZE_MB:
        send_file(chat_id, msg_id, file_path, title)
        os.remove(file_path)
        return
    num_parts = math.ceil(file_size_mb / MAX_SIZE_MB)
    base, ext = os.path.splitext(file_path)
    for i in range(num_parts):
        part_file = f"{base}_part{i+1}{ext}"
        cmd = ['ffmpeg', '-y', '-i', file_path, '-ss', str(i * duration_sec / num_parts),
               '-t', str(duration_sec / num_parts), '-c', 'copy', part_file]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        send_file(chat_id, msg_id, part_file, f"{title} Part {i+1}/{num_parts}")
        os.remove(part_file)

def send_file(chat_id, msg_id, file_path, caption):
    status_msg = bot.send_message(chat_id, f"⬆️ अपलोड हो रहा है '{caption}'...")

    with open(file_path, 'rb') as f:
        bot.send_video(chat_id, f, caption=f"🎥 {caption}")

    safe_edit_message("✅ अपलोड पूरा हुआ!", chat_id, status_msg.message_id)

# ---------------- START BOT ----------------
print("🤖 Bot Started! Unlimited recording enabled.")
bot.infinity_polling()
