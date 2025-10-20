import telebot
import subprocess
import threading
import os
import time
from datetime import datetime

# ---------------- CONFIG ----------------
BOT_TOKEN = "7994446557:AAHoC-lsN137MmZfVMHiTWHRXRBHCFlwCKA"
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="Markdown")

# ---------------- GLOBAL ----------------
MAX_SIZE = 2 * 1024 * 1024 * 1024  # 2GB
RECORDINGS = {}

# ---------------- FUNCTION: Time Conversion ----------------
def parse_duration(time_str):
    """HH:MM:SS को सेकंड में बदलो"""
    parts = time_str.split(":")
    if len(parts) == 3:
        h, m, s = map(int, parts)
        return h * 3600 + m * 60 + s
    elif len(parts) == 2:
        m, s = map(int, parts)
        return m * 60 + s
    elif len(parts) == 1:
        return int(parts[0])
    else:
        return 0

# ---------------- FUNCTION: रिकॉर्डिंग ----------------
def record_stream(url, duration, title, chat_id, task_id):
    try:
        start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        filename = f"{title}_{int(time.time())}.mp4"

        cmd = [
            "ffmpeg",
            "-y",
            "-i", url,
            "-t", str(duration),
            "-c", "copy",
            filename
        ]

        bot.send_message(chat_id, f"""
🎬 *रिकॉर्डिंग शुरू!*

🎥 *टाइटल:* `{title}`
⏱ *Duration:* {duration} सेकंड
🕒 *शुरुआत:* {start_time}
🔗 *URL:* `{url}`
🆔 *Task ID:* `{task_id}`
        """)

        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        RECORDINGS[task_id] = process

        process.wait()

        if os.path.exists(filename):
            size = os.path.getsize(filename)
            if size > MAX_SIZE:
                bot.send_message(chat_id, "⚠️ वीडियो 2GB से बड़ा है — अपलोड नहीं किया जा सकता।")
            else:
                bot.send_message(chat_id, "📤 *अपलोड शुरू हो रहा है...*")
                with open(filename, "rb") as video:
                    bot.send_video(chat_id, video, caption=f"✅ *रिकॉर्डिंग पूरी!* \n📝 *टाइटल:* `{title}` \n🕒 *Duration:* {duration} सेकंड")
                bot.send_message(chat_id, "✅ *Upload Complete!*")
            os.remove(filename)
        else:
            bot.send_message(chat_id, "❌ *रिकॉर्डिंग फाइल नहीं मिली!*")

    except Exception as e:
        bot.send_message(chat_id, f"⚠️ Error: `{str(e)}`")

    finally:
        if task_id in RECORDINGS:
            del RECORDINGS[task_id]

# ---------------- COMMAND: /record ----------------
@bot.message_handler(commands=['record'])
def handle_record(message):
    try:
        parts = message.text.split(" ")
        if len(parts) < 4:
            bot.reply_to(message, "❌ उपयोग:\n`/record <url> <duration> <title>`\n\nउदाहरण:\n`/record https://abc/playlist.m3u8 00:00:10 TestVideo`")
            return

        url = parts[1]
        duration_str = parts[2]
        title = " ".join(parts[3:])
        duration = parse_duration(duration_str)
        chat_id = message.chat.id
        task_id = str(int(time.time()))

        thread = threading.Thread(target=record_stream, args=(url, duration, title, chat_id, task_id))
        thread.start()

        bot.send_message(chat_id, f"🎥 *रिकॉर्डिंग शुरू हुई है!* Task ID: `{task_id}`")

    except Exception as e:
        bot.reply_to(message, f"⚠️ Error: `{str(e)}`")

# ---------------- COMMAND: /stop ----------------
@bot.message_handler(commands=['stop'])
def stop_record(message):
    try:
        parts = message.text.split(" ")
        if len(parts) < 2:
            bot.reply_to(message, "❌ उपयोग: `/stop <task_id>`")
            return

        task_id = parts[1]
        if task_id in RECORDINGS:
            process = RECORDINGS[task_id]
            process.terminate()
            del RECORDINGS[task_id]
            bot.reply_to(message, f"🛑 रिकॉर्डिंग बंद कर दी गई! Task ID: `{task_id}`")
        else:
            bot.reply_to(message, f"⚠️ कोई रिकॉर्डिंग नहीं मिली ID `{task_id}`")

    except Exception as e:
        bot.reply_to(message, f"⚠️ Error: `{str(e)}`")

# ---------------- COMMAND: /list ----------------
@bot.message_handler(commands=['list'])
def list_records(message):
    if not RECORDINGS:
        bot.reply_to(message, "📭 कोई रिकॉर्डिंग नहीं चल रही।")
    else:
        msg = "🎬 *चल रही रिकॉर्डिंग्स:*\n\n"
        for tid in RECORDINGS:
            msg += f"🆔 `{tid}` - चल रही है...\n"
        bot.reply_to(message, msg)

# ---------------- COMMAND: /help ----------------
@bot.message_handler(commands=['help', 'start'])
def help_command(message):
    bot.reply_to(message, """
👋 *रिकॉर्डिंग बॉट में आपका स्वागत है!*

🎬 **कमांड सूची:**
- `/record <url> <duration> <title>` — M3U8 लिंक रिकॉर्ड करें  
  ➤ उदाहरण: `/record https://abc/playlist.m3u8 00:00:10 TestVideo`
- `/list` — चल रही रिकॉर्डिंग्स देखें  
- `/stop <task_id>` — किसी रिकॉर्डिंग को बंद करें  

💾 *सीमा:* 2GB तक की फाइलें अपलोड होंगी।
    """)

# ---------------- BOT RUN ----------------
bot.infinity_polling()
