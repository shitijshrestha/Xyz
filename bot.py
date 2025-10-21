import telebot
import subprocess
import threading
import os
import time
from datetime import datetime
from functools import wraps

# ---------------- CONFIG ----------------
BOT_TOKEN = "7994446557:AAEU2ZI52ZuSYKZ_dKrLPwarE7E_pvGLi3E"
bot = telebot.TeleBot(BOT_TOKEN, num_threads=10)

REAL_ADMIN_ID = 6403142441  # Real admin (aapka Telegram ID)
GROUP_CHAT_ID = -1002323987687  # Bot sirf is group mein chalega
APPROVED_USERS = set()  # Approved users ka record

# ---------------- HELPERS ----------------
def admin_only(func):
    @wraps(func)
    def wrapper(message):
        if message.from_user.id != REAL_ADMIN_ID:
            bot.reply_to(message, "❌ Ye command sirf admin ke liye hai.")
            return
        return func(message)
    return wrapper

def group_only(func):
    @wraps(func)
    def wrapper(message):
        if message.chat.id != GROUP_CHAT_ID:
            bot.reply_to(message, "❌ Ye bot sirf group mein use ho sakta hai.")
            return
        return func(message)
    return wrapper

def user_allowed(func):
    @wraps(func)
    def wrapper(message):
        user_id = message.from_user.id
        if user_id == REAL_ADMIN_ID or user_id in APPROVED_USERS:
            return func(message)
        else:
            bot.reply_to(message, "🕓 Aapka access pending hai. Admin approval ka intezaar karein.")
            bot.send_message(REAL_ADMIN_ID, f"📩 New user request:\n👤 {message.from_user.first_name} ({user_id})\n👉 Approve with /approve {user_id}")
    return wrapper

# ---------------- COMMANDS ----------------
@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "👋 Namaste! Ye IPTV Recorder Bot hai.\nAdmin approval ke baad hi aap commands use kar paayenge.")

@bot.message_handler(commands=['approve'])
@admin_only
def approve_user(message):
    try:
        user_id = int(message.text.split()[1])
        APPROVED_USERS.add(user_id)
        bot.reply_to(message, f"✅ User approved: {user_id}")
        bot.send_message(user_id, "✅ Aapko access mil gaya! Ab aap /record command use kar sakte hain.")
    except:
        bot.reply_to(message, "❌ Usage: /approve <user_id>")

# ---------------- RECORD FUNCTION ----------------
def record_stream(url, duration, title, chat_id):
    try:
        start_time = datetime.now()
        end_time = start_time + time.timedelta(seconds=duration)
        filename_time = start_time.strftime("%H-%M-%S") + "-" + (start_time + time.timedelta(seconds=duration)).strftime("%H-%M-%S")
        date_today = start_time.strftime("%d-%m-%Y")

        filename = f"Untitled.Direct Stream.{filename_time}.{date_today}.IPTV.WEB-DL.@Shitijbro.mkv"
        bot.send_message(chat_id, f"🎬 Recording Started!\n\n🎥 Title: {title}\n🔗 URL: {url}\n⏱ Duration: {duration}s")

        cmd = ["ffmpeg", "-y", "-i", url, "-t", str(duration), "-c", "copy", filename]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        if os.path.exists(filename):
            size_mb = os.path.getsize(filename) / (1024 * 1024)
            duration_str = time.strftime("%H:%M:%S", time.gmtime(duration))
            caption = f"📁 Filename: {filename}\n⏱ Duration: {duration_str} (Original: 0:{duration_str})\n💾 File-Size: {size_mb:.2f} MB\n☎️ @Shitijbro"

            with open(filename, "rb") as video:
                bot.send_video(chat_id, video, caption=caption)

            os.remove(filename)
        else:
            bot.send_message(chat_id, "❌ Recording failed.")
    except Exception as e:
        bot.send_message(chat_id, f"⚠️ Error: {e}")

@bot.message_handler(commands=['record'])
@group_only
@user_allowed
def handle_record(message):
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "❌ Usage:\n/record <url> [duration] [title]")
        return

    url = parts[1]
    duration = 10  # Default 10 sec
    title = "Untitled Stream"

    if len(parts) == 3:
        if ":" in parts[2]:
            try:
                h, m, s = map(int, parts[2].split(":"))
                duration = h * 3600 + m * 60 + s
            except:
                duration = 10
            title = " ".join(parts[3:]) if len(parts) > 3 else "Untitled Stream"
        else:
            try:
                duration = int(parts[2])
            except:
                duration = 10
            title = " ".join(parts[3:]) if len(parts) > 3 else "Untitled Stream"
    elif len(parts) > 3:
        try:
            duration = int(parts[2])
        except:
            duration = 10
        title = " ".join(parts[3:])

    threading.Thread(target=record_stream, args=(url, duration, title, message.chat.id)).start()

# ---------------- RUN BOT ----------------
print("🤖 Bot is running...")
bot.infinity_polling()
