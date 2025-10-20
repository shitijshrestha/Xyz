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
bot = telebot.TeleBot(BOT_TOKEN, num_threads=20)

ADMIN_IDS = [6403142441]  # Change to your Telegram ID
MAX_SIZE_MB = 50  # Telegram max per video upload limit
active_recordings = {}  # chat_id -> {msg_id: info}

# ---------------- HELPERS ----------------
def admin_only(func):
    @wraps(func)
    def wrapper(message, *args, **kwargs):
        if message.from_user.id in ADMIN_IDS:
            return func(message, *args, **kwargs)
        bot.reply_to(message, "⛔ केवल एडमिन इस्तेमाल कर सकता है!")
    return wrapper

def safe_edit(text, chat_id, msg_id):
    if len(text) > 4096:
        text = text[:4090] + "..."
    try:
        bot.edit_message_text(text, chat_id, msg_id)
    except ApiTelegramException:
        pass

# ---------------- BASIC COMMANDS ----------------
@bot.message_handler(commands=['start'])
@admin_only
def start(message):
    bot.reply_to(message, "👋 Bot चालू है!\n/use `/help` सभी commands देखने के लिए।", parse_mode="Markdown")

@bot.message_handler(commands=['help'])
@admin_only
def help_command(message):
    help_text = """
📌 **उपलब्ध Commands**

/start - बॉट चालू करें  
/help - मदद मेन्यू  
/status - चालू recordings  
/myrecordings - आपकी recordings  
/record <URL> <hh:mm:ss> <title> - Record स्ट्रीम  
/cancel - Record रोकें (reply करें recording msg पर)  
/screenshot <URL> - Screenshot लें  

**Admin Commands**  
/allrecordings - सब recordings देखें  
/broadcast <msg> - सब admins को msg भेजें  

**Example:**  
`/record https://url.m3u8 00:00:10 Testing`
"""
    bot.reply_to(message, help_text, parse_mode="Markdown")

@bot.message_handler(commands=['status'])
@admin_only
def status(message):
    total = sum(len(r) for r in active_recordings.values())
    bot.reply_to(message, f"✅ Bot चल रहा है!\n🎬 एक्टिव recordings: {total}")

@bot.message_handler(commands=['myrecordings'])
@admin_only
def myrecordings(message):
    chat_id = message.chat.id
    if chat_id not in active_recordings or not active_recordings[chat_id]:
        bot.reply_to(message, "कोई recording चालू नहीं है।")
        return
    text = "🎥 आपकी recordings:\n"
    for msg_id, info in active_recordings[chat_id].items():
        text += f"- {info['title']} (PID: {info['proc'].pid})\n"
    bot.reply_to(message, text)

@bot.message_handler(commands=['allrecordings'])
@admin_only
def allrecordings(message):
    total = sum(len(r) for r in active_recordings.values())
    if total == 0:
        bot.reply_to(message, "❌ कोई recording चालू नहीं है।")
        return
    text = f"🎬 सभी एक्टिव recordings ({total}):\n"
    for chat_id, recs in active_recordings.items():
        text += f"\nChat {chat_id}:\n"
        for msg_id, info in recs.items():
            text += f"- {info['title']} (PID: {info['proc'].pid})\n"
    bot.reply_to(message, text)

@bot.message_handler(commands=['broadcast'])
@admin_only
def broadcast(message):
    try:
        msg = message.text.split(None, 1)[1]
        for admin in ADMIN_IDS:
            bot.send_message(admin, f"📢 *Broadcast:*\n{msg}", parse_mode="Markdown")
        bot.reply_to(message, "✅ Broadcast भेज दिया गया।")
    except:
        bot.reply_to(message, "Usage: /broadcast <message>")

# ---------------- SCREENSHOT ----------------
@bot.message_handler(commands=['screenshot'])
@admin_only
def screenshot(message):
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /screenshot <URL>")
        return
    url = args[1]
    file = f"screenshot_{int(time.time())}.jpg"
    cmd = ["ffmpeg", "-y", "-i", url, "-vframes", "1", file]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.path.exists(file):
        with open(file, 'rb') as f:
            bot.send_photo(message.chat.id, f, caption=f"🖼 Screenshot\n🔗 {url}")
        os.remove(file)
    else:
        bot.reply_to(message, "❌ Screenshot असफल रहा।")

# ---------------- RECORDING ----------------
@bot.message_handler(commands=['record'])
@admin_only
def record(message):
    args = message.text.split()
    if len(args) < 4:
        bot.reply_to(message, "Usage: /record <URL> <hh:mm:ss> <Title>")
        return

    url = args[1]
    try:
        h, m, s = map(int, args[2].split(":"))
        duration = h * 3600 + m * 60 + s
    except:
        bot.reply_to(message, "❌ Invalid time format! (Use hh:mm:ss)")
        return

    title = " ".join(args[3:])
    output = f"rec_{message.chat.id}_{int(time.time())}.mp4"
    msg = bot.reply_to(message, f"🎬 Recording *{title}* शुरू हो गई!\n⏱ समय: {args[2]}", parse_mode="Markdown")
    msg_id = msg.message_id

    threading.Thread(target=start_recording, args=(message.chat.id, msg_id, url, duration, title, output)).start()

def start_recording(chat_id, msg_id, url, duration, title, output):
    if chat_id not in active_recordings:
        active_recordings[chat_id] = {}
    cmd = ["ffmpeg", "-y", "-i", url, "-t", str(duration), "-c", "copy", output]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    active_recordings[chat_id][msg_id] = {"proc": proc, "title": title}

    start_time = time.time()
    while proc.poll() is None:
        elapsed = time.time() - start_time
        percent = min(100, (elapsed / duration) * 100)
        bar = "█" * int(percent / 10) + "░" * (10 - int(percent / 10))
        safe_edit(f"🎬 Recording: {title}\n📊 {percent:.1f}% [{bar}]\n⏱ बीता: {int(elapsed)}s / {duration}s", chat_id, msg_id)
        time.sleep(5)

    proc.wait()
    if os.path.exists(output):
        safe_edit(f"✅ Recording पूरी हुई!\n📦 Uploading...", chat_id, msg_id)
        upload_split(chat_id, output, title, msg_id)
    else:
        safe_edit("❌ Recording असफल रही।", chat_id, msg_id)

    active_recordings[chat_id].pop(msg_id, None)
    if not active_recordings[chat_id]:
        active_recordings.pop(chat_id, None)

# ---------------- CANCEL ----------------
@bot.message_handler(commands=['cancel'])
@admin_only
def cancel(message):
    if not message.reply_to_message:
        bot.reply_to(message, "Reply करें उस recording message पर जिसे रोकना है।")
        return
    chat_id = message.chat.id
    msg_id = message.reply_to_message.message_id
    if chat_id in active_recordings and msg_id in active_recordings[chat_id]:
        proc = active_recordings[chat_id][msg_id]["proc"]
        proc.terminate()
        bot.reply_to(message, "🛑 Recording बंद कर दी गई।")
    else:
        bot.reply_to(message, "❌ कोई active recording नहीं मिली।")

# ---------------- UPLOAD ----------------
def upload_split(chat_id, file_path, title, msg_id):
    file_size = os.path.getsize(file_path) / (1024 * 1024)
    if file_size <= MAX_SIZE_MB:
        send_part(chat_id, file_path, title, msg_id)
        os.remove(file_path)
        return

    num_parts = math.ceil(file_size / MAX_SIZE_MB)
    base, ext = os.path.splitext(file_path)
    duration = get_video_duration(file_path)
    part_dur = duration / num_parts

    for i in range(num_parts):
        part = f"{base}_part{i+1}{ext}"
        cmd = ["ffmpeg", "-y", "-i", file_path, "-ss", str(i * part_dur),
               "-t", str(part_dur), "-c", "copy", part]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        send_part(chat_id, part, f"{title} (Part {i+1}/{num_parts})", msg_id)
        os.remove(part)

    os.remove(file_path)

def get_video_duration(file_path):
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", file_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        return float(result.stdout.strip())
    except:
        return 0

def send_part(chat_id, file_path, caption, msg_id):
    status = bot.send_message(chat_id, f"⬆️ Uploading `{caption}`...", parse_mode="Markdown")

    total_size = os.path.getsize(file_path)
    sent = 0
    last_update = 0
    chunk_size = 1024 * 512  # 512KB

    class ProgressFile(io.BufferedReader):
        def read(self, size=-1):
            nonlocal sent, last_update
            chunk = super().read(size)
            if chunk:
                sent += len(chunk)
                now = time.time()
                if now - last_update > 2:
                    percent = (sent / total_size) * 100
                    bar = "█" * int(percent / 10) + "░" * (10 - int(percent / 10))
                    safe_edit(f"⬆️ Uploading: {caption}\n📊 {percent:.1f}% [{bar}]", chat_id, status.message_id)
                    last_update = now
            return chunk

    with open(file_path, 'rb') as f:
        progress = ProgressFile(f)
        bot.send_video(chat_id, progress, caption=f"🎥 {caption}")
    safe_edit("✅ Upload Complete!", chat_id, status.message_id)

# ---------------- START BOT ----------------
print("🤖 Bot Started & Ready for Unlimited Recording!")
bot.infinity_polling()
