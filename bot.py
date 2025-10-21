import telebot
import subprocess
import threading
import os
import time
from datetime import datetime, timedelta
from telebot.apihelper import ApiTelegramException
from functools import wraps

# ---------------- CONFIG ----------------
BOT_TOKEN = "7994446557:AAEZZ4ffk2-a2hLBi-rJDJywUD1HVCVm1zU"
bot = telebot.TeleBot(BOT_TOKEN, num_threads=10)

PERMANENT_ADMIN = 6403142441
approved_users = set()
pending_users = set()
DUMP_CHANNEL_ID = -1002627919828

# ---------------- DECORATORS ----------------
def admin_only(func):
    @wraps(func)
    def wrapper(message, *args, **kwargs):
        if message.from_user.id == PERMANENT_ADMIN:
            return func(message, *args, **kwargs)
        else:
            bot.reply_to(message, "⛔ Only the main admin can use this command.")
    return wrapper


def approved_only(func):
    @wraps(func)
    def wrapper(message, *args, **kwargs):
        uid = message.from_user.id
        if uid == PERMANENT_ADMIN or uid in approved_users:
            return func(message, *args, **kwargs)
        elif uid in pending_users:
            bot.reply_to(message, "⏳ Your access request is pending admin approval.")
        else:
            pending_users.add(uid)
            bot.reply_to(message, "✋ You are not approved yet. Admin has been notified.")
            bot.send_message(
                PERMANENT_ADMIN,
                f"🆕 New user request:\n👤 {message.from_user.first_name}\n🆔 ID: {uid}\nUse /approve {uid} to approve."
            )
    return wrapper


def safe_edit(chat_id, msg_id, text):
    try:
        if len(text) > 4000:
            text = text[:3990] + "..."
        bot.edit_message_text(text, chat_id, msg_id)
    except ApiTelegramException:
        pass


# ---------------- COMMANDS ----------------
@bot.message_handler(commands=['start'])
def start(message):
    uid = message.from_user.id
    if uid == PERMANENT_ADMIN or uid in approved_users:
        bot.reply_to(message, "👋 Welcome! Use /help to see available commands.")
    elif uid in pending_users:
        bot.reply_to(message, "⏳ Your access request is pending admin approval.")
    else:
        pending_users.add(uid)
        bot.reply_to(message, "✋ You are not approved yet. Admin has been notified.")
        bot.send_message(
            PERMANENT_ADMIN,
            f"🆕 New user request:\n👤 {message.from_user.first_name}\n🆔 ID: {uid}\nUse /approve {uid} to approve."
        )


@bot.message_handler(commands=['help'])
@approved_only
def help_command(message):
    text = """
📘 **Available Commands:**
/record <url> <duration> <title> — Record stream
/status — Show bot status
/cancel — Cancel a recording

🛠 **Admin Only:**
/approve <user_id> — Approve user
"""
    bot.reply_to(message, text)


@bot.message_handler(commands=['approve'])
@admin_only
def approve_user(message):
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /approve <user_id>")
        return
    try:
        user_id = int(args[1])
    except:
        bot.reply_to(message, "Invalid user ID format.")
        return

    if user_id in pending_users:
        pending_users.remove(user_id)
        approved_users.add(user_id)
        bot.reply_to(message, f"✅ Approved user: {user_id}")
        bot.send_message(user_id, "✅ You’ve been approved! Use /record to start recording.")
    else:
        bot.reply_to(message, "⚠️ This user is not pending approval.")


# ---------------- RECORDING SYSTEM ----------------
active_rec = {}

@bot.message_handler(commands=['record'])
@approved_only
def record(message):
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /record <url> <duration> <title>")
        return

    url = args[1]
    duration = 10
    title = "Untitled"

    if len(args) >= 3:
        try:
            if ":" in args[2]:
                h, m, s = map(int, args[2].split(":"))
                duration = h * 3600 + m * 60 + s
            else:
                duration = int(args[2])
        except:
            bot.reply_to(message, "Invalid duration format.")
            return

    if len(args) >= 4:
        title = " ".join(args[3:])

    msg = bot.reply_to(message, f"🎬 Recording started: {title}\n⏱ Duration: {duration}s")
    chat_id = message.chat.id
    msg_id = msg.message_id
    threading.Thread(target=record_process, args=(chat_id, msg_id, url, duration, title)).start()


def record_process(chat_id, msg_id, url, duration, title):
    timestamp = int(time.time())
    filename = f"record_{chat_id}_{timestamp}.mkv"
    cmd = ["ffmpeg", "-y", "-i", url, "-t", str(duration), "-c", "copy", filename]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    start = time.time()
    active_rec[(chat_id, msg_id)] = proc
    while proc.poll() is None:
        elapsed = time.time() - start
        percent = min((elapsed / duration) * 100, 100)
        bar = "█" * int(percent / 10) + "░" * (10 - int(percent / 10))
        safe_edit(chat_id, msg_id, f"🎥 Recording {title}\n📊 {percent:.1f}% [{bar}]\n⏱ {int(elapsed)}s/{duration}s")
        time.sleep(2)

    proc.wait()
    if os.path.exists(filename):
        safe_edit(chat_id, msg_id, "✅ Recording complete. Uploading...")
        upload_video(chat_id, filename, title, duration)
    else:
        safe_edit(chat_id, msg_id, "❌ Recording failed.")

    del active_rec[(chat_id, msg_id)]


def upload_video(chat_id, path, title, duration):
    size_mb = os.path.getsize(path) / (1024 * 1024)
    now = datetime.now()
    end_time = now + timedelta(seconds=duration)
    caption = (
        f"📁 Filename: {title}.{now.strftime('%H-%M-%S')}-{end_time.strftime('%H-%M-%S')}.{now.strftime('%d-%m-%Y')}.IPTV.WEB-DL.@Shitijbro.mkv\n"
        f"⏱ Duration: {duration//60}min {duration%60}sec\n"
        f"💾 File Size: {size_mb:.2f} MB\n"
        f"☎️ @Shitijbro"
    )

    try:
        with open(path, "rb") as video:
            # Upload to user/chat
            bot.send_video(chat_id, video, caption=caption)
        with open(path, "rb") as video_dump:
            # Upload to dump channel
            bot.send_video(DUMP_CHANNEL_ID, video_dump, caption=caption)
        bot.send_message(chat_id, "✅ Uploaded to you and dump channel successfully!")
    except Exception as e:
        bot.send_message(chat_id, f"❌ Upload failed: {e}")
    finally:
        if os.path.exists(path):
            os.remove(path)


@bot.message_handler(commands=['cancel'])
@approved_only
def cancel_record(message):
    if not message.reply_to_message:
        bot.reply_to(message, "Reply to the recording message to cancel it.")
        return

    chat_id = message.chat.id
    msg_id = message.reply_to_message.message_id
    key = (chat_id, msg_id)

    if key in active_rec:
        proc = active_rec[key]
        proc.terminate()
        del active_rec[key]
        bot.reply_to(message, "🛑 Recording cancelled.")
    else:
        bot.reply_to(message, "❌ No active recording found.")


# ---------------- START BOT ----------------
print("🤖 IPTV Upload Bot started with Dump Channel upload enabled!")
bot.infinity_polling()
