import telebot
import subprocess
import threading
import os
import time
import math
import datetime
from telebot.apihelper import ApiTelegramException

# ---------------- CONFIG ----------------
BOT_TOKEN = "7994446557:AAHC5VT3ASLDPJATg2C17ejjhZtBySmsUAs"
PERMANENT_ADMIN = 6403142441
DUMP_CHANNEL_ID = -1002627919828
SPLIT_SIZE_MB = 50

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

approved_users = {PERMANENT_ADMIN}
active_processes = {}
recordings = {}

# ---------------- HELPERS ----------------
def time_to_seconds(t):
    if ":" in t:
        h, m, s = t.split(":")
        return int(h) * 3600 + int(m) * 60 + int(s)
    return int(t)

def readable_size(size_bytes):
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} TB"

def split_file_by_size(filepath, max_size_mb):
    """Split a file into parts ≤ max_size_mb"""
    max_bytes = max_size_mb * 1024 * 1024
    total_size = os.path.getsize(filepath)
    parts = []
    with open(filepath, "rb") as f:
        i = 1
        while True:
            chunk = f.read(max_bytes)
            if not chunk:
                break
            partname = f"{os.path.splitext(filepath)[0]}_part{i}.mkv"
            with open(partname, "wb") as p:
                p.write(chunk)
            parts.append(partname)
            i += 1
    return parts

def upload_video_parts(chat_id, filepath, title):
    """Upload video parts with captions"""
    try:
        duration_output = subprocess.check_output(
            ["./ffprobe", "-v", "error", "-show_entries",
             "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", filepath]
        ).decode().strip()
        duration_seconds = float(duration_output)
    except:
        duration_seconds = 0.0

    parts = split_file_by_size(filepath, SPLIT_SIZE_MB)
    for idx, part in enumerate(parts, start=1):
        size = os.path.getsize(part)
        caption = (
            f"📁 Filename: {os.path.basename(part)}\n"
            f"⏱ Duration: {str(datetime.timedelta(seconds=int(duration_seconds)))}\n"
            f"📦 File-Size: {readable_size(size)}\n"
            f"👨‍💻 Developer: @Shitijbro\n"
            f"🧩 Part {idx}/{len(parts)}"
        )
        with open(part, "rb") as video:
            try:
                bot.send_video(chat_id, video, caption=caption)
                bot.send_video(DUMP_CHANNEL_ID, video, caption=caption)
            except ApiTelegramException as e:
                bot.send_message(chat_id, f"⚠️ Upload failed: {e}")
        os.remove(part)
    os.remove(filepath)

# ---------------- RECORD FUNCTION ----------------
def record_stream(chat_id, url, duration_str, title):
    duration = time_to_seconds(duration_str)
    start = datetime.datetime.now()
    end = start + datetime.timedelta(seconds=duration)
    date_str = start.strftime("%d-%m-%Y")
    filename = f"{title}.{start.strftime('%H-%M-%S')}-{end.strftime('%H-%M-%S')}.{date_str}.IPTV.WEB-DL.@Shitijbro.mkv"

    msg = bot.send_message(chat_id, f"🎬 <b>Recording Started</b>\n🎥 {title}\n⏱ Duration: {duration_str}\n🔗 URL: {url}")
    cmd = ["./ffmpeg", "-y", "-i", url, "-t", str(duration), "-c", "copy", filename]

    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    active_processes[chat_id] = process
    start_time = time.time()

    while process.poll() is None:
        elapsed = int(time.time() - start_time)
        percent = min(100, (elapsed / duration) * 100)
        bar = "█" * int(percent // 10) + "░" * (10 - int(percent // 10))
        try:
            bot.edit_message_text(
                f"🎥 <b>{title}</b>\n📊 {percent:.1f}% [{bar}]\n⏱ {elapsed}s / {duration}s",
                chat_id, msg.message_id, parse_mode="HTML"
            )
        except:
            pass
        time.sleep(5)

    process.wait()
    del active_processes[chat_id]
    bot.send_message(chat_id, f"✅ Recording Finished.\n📤 Uploading <b>{title}</b>...")
    recordings[chat_id] = filename
    upload_video_parts(chat_id, filename, title)
    bot.send_message(chat_id, f"✅ All parts uploaded for <b>{title}</b>")

# ---------------- COMMAND HANDLERS ----------------
@bot.message_handler(commands=["start"])
def start_cmd(message):
    bot.reply_to(
        message,
        "🤖 <b>Welcome!</b>\n"
        "Use /record <url> <duration> <title> to record.\n"
        "Type /help for more commands.",
    )

@bot.message_handler(commands=["help"])
def help_cmd(message):
    bot.reply_to(
        message,
        "📘 <b>Available Commands</b>\n"
        "/start - Welcome\n"
        "/help - Show this message\n"
        "/record <url> <duration> <title> - Record a stream\n"
        "/cancel - Stop active recording\n"
        "/recordings - List last file\n"
        "/addadmin <user_id> - Approve new admin\n"
        "/users - Show approved users\n"
        "/status - Show running status"
    )

@bot.message_handler(commands=["record"])
def record_cmd(message):
    if message.from_user.id not in approved_users:
        return bot.reply_to(message, "🚫 Not authorized.")
    try:
        _, url, duration, title = message.text.split(" ", 3)
        threading.Thread(target=record_stream, args=(message.chat.id, url, duration, title)).start()
    except ValueError:
        bot.reply_to(message, "❌ Usage: /record <url> <duration> <title>")

@bot.message_handler(commands=["cancel"])
def cancel_cmd(message):
    proc = active_processes.get(message.chat.id)
    if proc:
        proc.terminate()
        bot.reply_to(message, "🛑 Recording cancelled.")
    else:
        bot.reply_to(message, "⚠️ No active recording.")

@bot.message_handler(commands=["recordings"])
def recordings_cmd(message):
    fname = recordings.get(message.chat.id)
    if fname:
        bot.reply_to(message, f"📁 Last file: <b>{fname}</b>")
    else:
        bot.reply_to(message, "No recordings found yet.")

@bot.message_handler(commands=["addadmin"])
def addadmin_cmd(message):
    if message.from_user.id != PERMANENT_ADMIN:
        return bot.reply_to(message, "🚫 Only permanent admin can add users.")
    try:
        uid = int(message.text.split(" ", 1)[1])
        approved_users.add(uid)
        bot.reply_to(message, f"✅ User {uid} added.")
    except:
        bot.reply_to(message, "❌ Usage: /addadmin <user_id>")

@bot.message_handler(commands=["users"])
def users_cmd(message):
    text = "\n".join(str(u) for u in approved_users)
    bot.reply_to(message, f"👥 Approved Users:\n{text}")

@bot.message_handler(commands=["status"])
def status_cmd(message):
    active = "Yes" if message.chat.id in active_processes else "No"
    bot.reply_to(message, f"⚙️ Bot Status\nActive Recording: {active}")

# ---------------- START BOT ----------------
print("🤖 Bot started and ready.")
bot.infinity_polling()
