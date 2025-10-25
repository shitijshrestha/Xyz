import telebot
import subprocess
import threading
import os
import time
import datetime
from functools import wraps
from telebot.apihelper import ApiTelegramException

# ---------------- CONFIG ----------------
BOT_TOKEN = "7994446557:AAGVPy_UPpWKeJLEX1TNi6ZOC6OnKVe-4SA"
bot = telebot.TeleBot(BOT_TOKEN, num_threads=10)

PERMANENT_ADMIN = 6403142441
ADMIN_IDS = [6403142441, 7470440084]
approved_users = set(ADMIN_IDS)
pending_users = set()
DUMP_CHANNEL_ID = -1002627919828
SPLIT_SIZE_MB = 49
CHUNK_DURATION = 180  # 3 minutes = 180 seconds
active_recordings = {}

# ---------------- HELPERS ----------------
def admin_only(func):
    @wraps(func)
    def wrapped(message, *args, **kwargs):
        uid = message.from_user.id
        if uid in approved_users:
            return func(message, *args, **kwargs)
        else:
            if uid not in pending_users:
                pending_users.add(uid)
                for admin in ADMIN_IDS:
                    bot.send_message(admin, f"🛡 User @{message.from_user.username} ({uid}) requests access.")
                bot.reply_to(message, "⏳ Your request has been sent to admins for approval.")
            else:
                bot.reply_to(message, "⏳ Your request is pending admin approval.")
    return wrapped

def safe_edit(text, chat_id, msg_id):
    try:
        bot.edit_message_text(text, chat_id, msg_id)
    except ApiTelegramException:
        pass

def hms_format(seconds):
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{int(h)}hr, {int(m)}min, {int(s)}sec"

def generate_thumbnail(video_file):
    thumb_file = video_file.replace(".mkv", ".jpg")
    cmd = ["ffmpeg", "-y", "-i", video_file, "-ss", "00:00:05", "-vframes", "1", thumb_file]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return thumb_file if os.path.exists(thumb_file) else None

# ---------------- UPLOAD ----------------
def send_video(filepath, caption, chat_id, thumb=None):
    try:
        with open(filepath, "rb") as video_file:
            if thumb and os.path.exists(thumb):
                with open(thumb, "rb") as thumb_file:
                    bot.send_video(chat_id, video_file, caption=caption, thumb=thumb_file)
            else:
                bot.send_video(chat_id, video_file, caption=caption)
        print(f"[✅] Uploaded {filepath}")
    except Exception as e:
        bot.send_message(chat_id, f"❌ Upload failed: {e}")

def split_and_send(filepath, caption, chat_id, thumb=None):
    part_size = SPLIT_SIZE_MB * 1024 * 1024
    base, ext = os.path.splitext(filepath)
    part = 1
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(part_size)
            if not chunk:
                break
            part_file = f"{base}_part{part}{ext}"
            with open(part_file, "wb") as pf:
                pf.write(chunk)
            retry_upload(part_file, f"{caption}\n📄 Part {part}", chat_id, thumb)
            os.remove(part_file)
            part += 1

def retry_upload(file, caption, chat_id, thumb, retries=3):
    for attempt in range(retries):
        try:
            send_video(file, caption, chat_id, thumb)
            return
        except:
            time.sleep(5)

# ---------------- RECORDING ----------------
def record_stream(chat_id, msg_id, url, total_seconds, title):
    timestamp = datetime.datetime.now().strftime("%H-%M-%S.%d-%m-%Y")
    base_name = f"{title}.{timestamp}.IPTV.WEB-DL.@Shitijbro"
    output_file = f"{base_name}.mkv"

    active_recordings[chat_id] = {"title": title, "proc": None}
    cmd = ["ffmpeg", "-y", "-i", url, "-t", str(total_seconds), "-c", "copy", output_file]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    active_recordings[chat_id]["proc"] = proc

    start_time = time.time()
    while proc.poll() is None:
        elapsed = int(time.time() - start_time)
        percent = int((elapsed / total_seconds) * 100)
        if percent > 100: percent = 100
        bar = "█" * (percent // 5) + "░" * (20 - (percent // 5))
        safe_edit(f"🎬 Recording Progress\n📊 {percent}% [{bar}]\n⏱ {hms_format(elapsed)} / {hms_format(total_seconds)}\n🎯 {title}", chat_id, msg_id)
        time.sleep(2)

    proc.wait()
    safe_edit(f"✅ Recording Finished.\n📤 Uploading {title}...", chat_id, msg_id)

    # Split into 3-min chunks (180 sec each)
    chunk_cmd = [
        "ffmpeg", "-i", output_file, "-c", "copy", "-map", "0",
        "-f", "segment", "-segment_time", str(CHUNK_DURATION),
        "-reset_timestamps", "1", f"{base_name}_part%03d.mkv"
    ]
    subprocess.run(chunk_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # Upload all chunks
    for part_file in sorted([f for f in os.listdir(".") if f.startswith(base_name+"_part")]):
        thumb = generate_thumbnail(part_file)
        caption = f"🎬 {title}\n📦 {part_file}"
        split_and_send(part_file, caption, chat_id, thumb)
        split_and_send(part_file, caption, DUMP_CHANNEL_ID, thumb)
        if os.path.exists(part_file): os.remove(part_file)
        if thumb and os.path.exists(thumb): os.remove(thumb)

    if os.path.exists(output_file):
        os.remove(output_file)

    bot.send_message(chat_id, f"✅ Upload complete for {title}")

# ---------------- COMMANDS ----------------
@bot.message_handler(commands=['start'])
def start_cmd(message):
    bot.reply_to(message, "👋 Welcome! Use /help to see available commands.")

@bot.message_handler(commands=['help'])
def help_cmd(message):
    bot.reply_to(message, """📌 Usage: /record <url> <duration> [optional_title]

📝 Example:
/record https://example.com/stream.m3u8 00:00:10 Testing

✂️ Auto-splits into 3-min chunks and uploads each part.
""")

@bot.message_handler(commands=['record'])
@admin_only
def record_cmd(message):
    try:
        parts = message.text.split(" ", 3)
        if len(parts) < 3:
            return bot.reply_to(message, "Usage: /record <URL> <HH:MM:SS> <title>")
        url = parts[1]
        duration_str = parts[2]
        title = parts[3] if len(parts) >= 4 else "Recording"

        d = duration_str.split(":")
        if len(d) == 3:
            total_seconds = int(d[0]) * 3600 + int(d[1]) * 60 + int(d[2])
        elif len(d) == 2:
            total_seconds = int(d[0]) * 60 + int(d[1])
        else:
            total_seconds = int(d[0])

        msg = bot.reply_to(message, f"🎬 Recording started for {title}\nDuration: {hms_format(total_seconds)}")
        threading.Thread(target=record_stream, args=(message.chat.id, msg.message_id, url, total_seconds, title)).start()
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

@bot.message_handler(commands=['approve'])
@admin_only
def approve_user(message):
    try:
        uid = int(message.text.split()[1])
        approved_users.add(uid)
        bot.reply_to(message, f"✅ User {uid} approved.")
        bot.send_message(uid, "✅ You are approved to use the bot!")
    except:
        bot.reply_to(message, "⚠ Usage: /approve <user_id>")

print("🤖 Bot is running...")
bot.infinity_polling()
