import telebot
import subprocess
import threading
import os
import time
import math
import datetime
from telebot.apihelper import ApiTelegramException

# ---------------- CONFIG ----------------
BOT_TOKEN = "7994446557:AAE_lXneTqYEF5sEVdUxn38-RPBiK7rlJUM"
PERMANENT_ADMIN = 6403142441
DUMP_CHANNEL_ID = -1002627919828

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

active_records = {}
admins = {PERMANENT_ADMIN}
recordings = []
lock_file = "/tmp/iptvbot.lock"

# ---------------- SAFETY: SINGLE INSTANCE ----------------
if os.path.exists(lock_file):
    print("⚠️ Another instance detected. Exiting to prevent 409 conflict.")
    exit(0)
open(lock_file, "w").close()

def cleanup_lock():
    if os.path.exists(lock_file):
        os.remove(lock_file)

# ---------------- HELPERS ----------------
def time_to_seconds(t):
    try:
        if ":" in t:
            h, m, s = t.split(":")
            return int(h) * 3600 + int(m) * 60 + int(s)
        return int(t)
    except:
        return 10

def readable_size(path):
    return os.path.getsize(path) / (1024 * 1024)

def split_video(filename, target_mb=50):
    """Split video into ~target_mb size parts."""
    parts = []
    size = readable_size(filename)
    if size <= target_mb:
        return [filename]

    # get duration
    duration = float(subprocess.check_output([
        "ffprobe","-v","error","-show_entries",
        "format=duration","-of","default=noprint_wrappers=1:nokey=1",filename
    ]).decode().strip())

    chunks = math.ceil(size / target_mb)
    chunk_dur = duration / chunks

    for i in range(chunks):
        start = i * chunk_dur
        out = f"{filename}_part{i+1}.mkv"
        cmd = [
            "./ffmpeg","-y","-i",filename,"-ss",str(start),
            "-t",str(chunk_dur),"-c","copy",out
        ]
        subprocess.run(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        parts.append(out)
    return parts

def upload_video(chat_id, path, title):
    size = readable_size(path)
    dur = subprocess.check_output([
        "ffprobe","-v","error","-show_entries","format=duration",
        "-of","default=noprint_wrappers=1:nokey=1",path
    ]).decode().strip()
    duration_str = str(datetime.timedelta(seconds=int(float(dur))))
    caption = (
        f"📁 Filename: {os.path.basename(path)}\n"
        f"⏱ Duration: {duration_str}\n"
        f"📦 File-Size: {size:.2f} MB\n"
        f"Developer: @Shitijbro"
    )

    with open(path, "rb") as f:
        bot.send_video(chat_id, f, caption=caption)
        f.seek(0)
        bot.send_video(DUMP_CHANNEL_ID, f, caption=caption)
    os.remove(path)

# ---------------- RECORD FUNCTION ----------------
def record_stream(chat_id, url, dur_str, title):
    duration = time_to_seconds(dur_str)
    start_time = datetime.datetime.now().strftime("%H-%M-%S")
    end_time = (datetime.datetime.now() + datetime.timedelta(seconds=duration)).strftime("%H-%M-%S")
    date_now = datetime.datetime.now().strftime("%d-%m-%Y")
    filename = f"{title}.{start_time}-{end_time}.{date_now}.IPTV.WEB-DL.@Shitijbro.mkv"

    msg = bot.send_message(chat_id, f"🎬 Recording started\n🎥 <b>{title}</b>\n⏱ Duration: {dur_str}")
    cmd = ["./ffmpeg","-y","-i",url,"-t",str(duration),"-c","copy",filename]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    active_records[chat_id] = proc

    start = time.time()
    while proc.poll() is None:
        elapsed = int(time.time() - start)
        percent = min(100, (elapsed / duration) * 100)
        bar = "█" * int(percent/10) + "░" * (10 - int(percent/10))
        try:
            bot.edit_message_text(
                chat_id=chat_id, message_id=msg.message_id,
                text=f"🎥 <b>{title}</b>\n📊 {percent:.1f}% [{bar}]\n⏱ {elapsed}s/{duration}s",
                parse_mode="HTML"
            )
        except ApiTelegramException:
            pass
        time.sleep(5)

    proc.wait()
    del active_records[chat_id]
    bot.send_message(chat_id, f"✅ Recording finished. Splitting & uploading <b>{title}</b> ...")

    parts = split_video(filename, 50)
    for p in parts:
        upload_video(chat_id, p, title)
    if os.path.exists(filename):
        os.remove(filename)
    bot.send_message(chat_id, f"✅ All parts uploaded for <b>{title}</b>")

# ---------------- COMMANDS ----------------
@bot.message_handler(commands=['start'])
def start_cmd(m):
    bot.reply_to(m, "👋 Welcome! Use /record [url] [duration] [title]\nExample:\n/record https://example.m3u8 00:10:00 Test")

@bot.message_handler(commands=['help'])
def help_cmd(m):
    bot.reply_to(m, (
        "🧾 Commands:\n"
        "/record [url] [duration] [title] - Record stream\n"
        "/cancel - Cancel current recording\n"
        "/recordings - Show list\n"
        "/addadmin [user_id] - Add admin\n"
        "/users - List admins"
    ))

@bot.message_handler(commands=['record'])
def record_cmd(m):
    try:
        _, url, dur, title = m.text.split(" ", 3)
    except:
        bot.reply_to(m, "❌ Usage: /record [url] [duration] [title]")
        return
    threading.Thread(target=record_stream, args=(m.chat.id, url, dur, title)).start()

@bot.message_handler(commands=['cancel'])
def cancel_cmd(m):
    if m.chat.id in active_records:
        active_records[m.chat.id].terminate()
        bot.reply_to(m, "⛔ Recording cancelled.")
        del active_records[m.chat.id]
    else:
        bot.reply_to(m, "No active recording found.")

@bot.message_handler(commands=['recordings'])
def recs_cmd(m):
    if not recordings:
        bot.reply_to(m, "No recordings yet.")
    else:
        msg = "\n".join(recordings[-10:])
        bot.reply_to(m, f"📂 Recent Recordings:\n{msg}")

@bot.message_handler(commands=['addadmin'])
def add_admin(m):
    if m.from_user.id != PERMANENT_ADMIN:
        return
    try:
        uid = int(m.text.split(" ",1)[1])
        admins.add(uid)
        bot.reply_to(m, f"✅ Added admin: {uid}")
    except:
        bot.reply_to(m, "❌ Usage: /addadmin [user_id]")

@bot.message_handler(commands=['users'])
def users_cmd(m):
    if m.from_user.id not in admins:
        return
    msg = "\n".join([str(a) for a in admins])
    bot.reply_to(m, f"👮 Admins:\n{msg}")

# ---------------- START BOT ----------------
try:
    print("🤖 Bot started. Waiting for commands ...")
    bot.infinity_polling(timeout=30, long_polling_timeout=30)
finally:
    cleanup_lock()
