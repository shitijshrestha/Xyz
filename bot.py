import telebot
import subprocess
import threading
import os
import time
import datetime
from telebot.apihelper import ApiTelegramException
import glob

# ===================== CONFIG =====================
BOT_TOKEN = "7994446557:AAEOInnu7ccKhfw1lXDGoAceHw-VqP2kbw4"  # Bot Token
PERMANENT_ADMIN = 6403142441       # Admin Telegram ID
UPLOAD_SIZE_LIMIT = 50 * 1024 * 1024  # 50 MB per part
PART_DURATION = 300  # 5 मिनट per part (seconds)

bot = telebot.TeleBot(BOT_TOKEN, num_threads=5)

# ===================== GLOBAL VARIABLES =====================
approved_users = set()
recording_processes = {}  # chat_id : subprocess.Popen

# ===================== FUNCTIONS =====================

def is_admin(user_id):
    return user_id == PERMANENT_ADMIN

def send_msg_safe(chat_id, text):
    try:
        bot.send_message(chat_id, text)
    except Exception as e:
        print(f"Send message error: {e}")

def safe_upload(chat_id, file_path, caption):
    """Upload with retry until success"""
    while True:
        try:
            with open(file_path, 'rb') as f:
                bot.send_document(chat_id, f, caption=caption, timeout=600)
            print(f"✅ Uploaded: {file_path}")
            break
        except ApiTelegramException as e:
            print(f"⚠️ Upload error: {e}. Retrying in 30s...")
            time.sleep(30)
        except Exception as e:
            print(f"⚠️ Upload failed: {e}, retrying...")
            time.sleep(30)

def record_and_upload(chat_id, url, start_time, end_time, title, stop_event):
    send_msg_safe(chat_id, f"🎬 रिकॉर्डिंग सेट की गई है:\n🕒 {start_time} ➜ {end_time}\n🎥 {title}")
    
    now = datetime.datetime.now()
    today = now.date()
    start_dt = datetime.datetime.strptime(f"{today} {start_time}", "%Y-%m-%d %H:%M")
    end_dt = datetime.datetime.strptime(f"{today} {end_time}", "%Y-%m-%d %H:%M")
    if end_dt < start_dt:
        end_dt += datetime.timedelta(days=1)

    wait = (start_dt - now).total_seconds()
    if wait > 0:
        send_msg_safe(chat_id, f"⏳ {int(wait/60)} मिनट बाद रिकॉर्डिंग शुरू होगी...")
        time.sleep(wait)

    duration = int((end_dt - start_dt).total_seconds())
    send_msg_safe(chat_id, f"▶️ रिकॉर्डिंग शुरू... कुल {duration//60} मिनट")

    output_pattern = f"{title}_part_%03d.mp4"

    # FFmpeg Command with max 50 MB per part
    cmd = [
        "ffmpeg", "-y", "-i", url, "-c", "copy",
        "-fs", str(UPLOAD_SIZE_LIMIT),
        "-f", "segment", "-segment_time", str(PART_DURATION),
        "-reset_timestamps", "1", output_pattern
    ]
    process = subprocess.Popen(cmd)
    recording_processes[chat_id] = process

    start_time_recording = time.time()
    part_count = 0
    uploaded_parts = set()

    while True:
        elapsed = time.time() - start_time_recording
        if elapsed >= duration or stop_event.is_set():
            process.terminate()
            send_msg_safe(chat_id, "⏹ रिकॉर्डिंग manually stop कर दी गई।")
            break

        # Check for new parts ready for upload
        parts = sorted(glob.glob(f"{title}_part_*.mp4"))
        for p in parts:
            if p not in uploaded_parts:
                part_count += 1
                caption = f"🎬 {title}\n📦 Part {part_count}"
                send_msg_safe(chat_id, f"⏳ Uploading Part {part_count}...")
                safe_upload(chat_id, p, caption)
                os.remove(p)
                uploaded_parts.add(p)
                send_msg_safe(chat_id, f"✅ Part {part_count} uploaded successfully!")

        time.sleep(5)  # check every 5 seconds

    # Upload remaining parts
    parts = sorted(glob.glob(f"{title}_part_*.mp4"))
    for p in parts:
        if p not in uploaded_parts:
            part_count += 1
            caption = f"🎬 {title}\n📦 Part {part_count}"
            send_msg_safe(chat_id, f"⏳ Uploading Part {part_count}...")
            safe_upload(chat_id, p, caption)
            os.remove(p)
            send_msg_safe(chat_id, f"✅ Part {part_count} uploaded successfully!")

    send_msg_safe(chat_id, f"🎉 रिकॉर्डिंग पूरी हो गई!\n📤 कुल {part_count} पार्ट upload किए गए ✅")
    recording_processes.pop(chat_id, None)

# ===================== COMMANDS =====================

@bot.message_handler(commands=['start'])
def handle_start(message):
    bot.reply_to(message, "👋 Welcome! Send /help for commands.")

@bot.message_handler(commands=['help'])
def handle_help(message):
    if not is_admin(message.from_user.id) and message.from_user.id not in approved_users:
        bot.reply_to(message, "❌ केवल approved users और admin ही commands use कर सकते हैं।")
        return
    text = """
🎬 Commands:
/record <url> <start_time> <end_time> <title> - रिकॉर्डिंग शुरू करें
/stop - रिकॉर्डिंग रोकें
/help - ये message दिखाएँ
"""
    bot.reply_to(message, text)

# ===================== User Approval =====================

@bot.message_handler(commands=['request'])
def handle_request(message):
    user_id = message.from_user.id
    if user_id in approved_users:
        send_msg_safe(user_id, "✅ आप पहले से approved हैं।")
        return
    send_msg_safe(PERMANENT_ADMIN, f"👤 User {user_id} wants access. Use /approve {user_id}")
    send_msg_safe(user_id, "⏳ आपका request भेज दिया गया है। Admin approval pending...")

@bot.message_handler(commands=['approve'])
def handle_approve(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "❌ केवल admin कर सकता है।")
        return
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "📌 Usage: /approve <user_id>")
        return
    user_id = int(args[1])
    approved_users.add(user_id)
    send_msg_safe(user_id, "✅ आपका access approve हो गया है। अब आप commands use कर सकते हैं।")
    bot.reply_to(message, f"✅ User {user_id} approved successfully.")

# ===================== Record Command =====================

@bot.message_handler(commands=['record'])
def handle_record(message):
    user_id = message.from_user.id
    if not is_admin(user_id) and user_id not in approved_users:
        bot.reply_to(message, "❌ केवल approved users और admin ही रिकॉर्डिंग कर सकते हैं।")
        return
    try:
        args = message.text.split()
        if len(args) < 4:
            bot.reply_to(message, "📌 Usage:\n/record <m3u8_url> <start_time> <end_time> <title>")
            return
        url, start_time, end_time = args[1], args[2], args[3]
        title = args[4] if len(args) > 4 else "IPTV_Record"
        stop_event = threading.Event()
        threading.Thread(target=record_and_upload, args=(message.chat.id, url, start_time, end_time, title, stop_event)).start()
        send_msg_safe(message.chat.id, "▶️ रिकॉर्डिंग started...")
    except Exception as e:
        bot.reply_to(message, f"⚠️ Error: {e}")

# ===================== Stop Command =====================

@bot.message_handler(commands=['stop'])
def handle_stop(message):
    user_id = message.from_user.id
    if not is_admin(user_id) and user_id not in approved_users:
        bot.reply_to(message, "❌ केवल approved users और admin ही रिकॉर्डिंग रोक सकते हैं।")
        return
    process = recording_processes.get(message.chat.id)
    if process:
        process.terminate()
        send_msg_safe(message.chat.id, "⏹ रिकॉर्डिंग stop कर दी गई।")
    else:
        send_msg_safe(message.chat.id, "⚠️ कोई active recording नहीं है।")

# ===================== START BOT =====================
print("🤖 Bot Started...")
bot.infinity_polling()
