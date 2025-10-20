#!/usr/bin/env python3
# ShitijBot — Fully Working IPTV Recorder with Safe Upload

import os
import time
import json
import threading
import subprocess
from datetime import datetime
import telebot

# ---------------- CONFIG ----------------
BOT_TOKEN = "7994446557:AAHoC-lsN137MmZfVMHiTWHRXRBHCFlwCKA"
ADMIN_ID = 6403142441
BOT_NAME = "Shitij𝔹ot"
WORKDIR = "/root/Shitijbot"
SPLIT_SECONDS = 60  # 1-minute chunks for Telegram
MAX_CHUNK_SIZE = 50 * 1024 * 1024  # 50 MB approx for Telegram
# -----------------------------------------

os.makedirs(WORKDIR, exist_ok=True)
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="Markdown")

ADMINS_FILE = os.path.join(WORKDIR, "admins.json")
if os.path.exists(ADMINS_FILE):
    with open(ADMINS_FILE, "r") as f:
        try:
            ADMINS = set(json.load(f))
        except:
            ADMINS = {ADMIN_ID}
else:
    ADMINS = {ADMIN_ID}


def save_admins():
    with open(ADMINS_FILE, "w") as f:
        json.dump(list(ADMINS), f)


def is_admin(uid):
    return uid in ADMINS


# ---------------- COMMANDS ----------------
@bot.message_handler(commands=["start"])
def start_cmd(msg):
    bot.reply_to(
        msg,
        f"👋 Welcome to *{BOT_NAME}*\n\n"
        "📌 Usage:\n`/record <url> <duration_HH:MM:SS> <title>`\n\n"
        "📝 Example:\n`/record https://example.com/live.m3u8 00:00:10 Testing`\n\n"
        "⏰ Records immediately and auto-splits chunks for safe Telegram upload."
    )


@bot.message_handler(commands=["help"])
def help_cmd(msg):
    bot.reply_to(
        msg,
        "🆘 *Help Guide*\n\n"
        "Use:\n`/record <url> <duration_HH:MM:SS> <title>`\n\n"
        "Admin only commands:\n`/addadmin <user_id>`",
    )


@bot.message_handler(commands=["addadmin"])
def addadmin_cmd(msg):
    if not is_admin(msg.from_user.id):
        bot.reply_to(msg, "❌ केवल admin ही admin जोड़ सकते हैं।")
        return
    parts = msg.text.strip().split()
    if len(parts) != 2:
        bot.reply_to(msg, "📌 Usage: /addadmin <user_id>")
        return
    try:
        new_id = int(parts[1])
    except:
        bot.reply_to(msg, "⚠️ Invalid user ID.")
        return
    ADMINS.add(new_id)
    save_admins()
    bot.reply_to(msg, f"✅ Added admin `{new_id}` successfully.")


@bot.message_handler(commands=["record"])
def record_cmd(msg):
    if not is_admin(msg.from_user.id):
        bot.reply_to(msg, "❌ केवल admin ही recording शुरू कर सकते हैं।")
        return
    parts = msg.text.strip().split(maxsplit=3)
    if len(parts) < 4:
        bot.reply_to(msg, "📌 Usage: /record <url> <duration_HH:MM:SS> <title>")
        return

    _, url, dur_str, title = parts

    # Parse duration HH:MM:SS
    try:
        h, m, s = map(int, dur_str.strip().split(":"))
        duration = h * 3600 + m * 60 + s
        if duration <= 0:
            raise ValueError
    except Exception:
        bot.reply_to(msg, "⚠️ Duration must be in HH:MM:SS format and > 0")
        return

    bot.reply_to(
        msg,
        f"🎬 *Recording Started!*\n\n"
        f"🎥 *Title:* {title}\n"
        f"🔗 *URL:* {url}\n"
        f"⏱ Duration: {duration//60} min {duration%60} sec\n"
        f"✂️ Auto-split into safe chunks for Telegram."
    )

    threading.Thread(
        target=recording_and_upload,
        args=(url, duration, title, msg.chat.id),
        daemon=True
    ).start()


# ---------------- RECORDING ENGINE ----------------
def recording_and_upload(url, duration, title, chat_id):
    safe_title = "".join(c if c.isalnum() or c in " _-." else "_" for c in title)[:70]
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    raw_file = os.path.join(WORKDIR, f"{safe_title}_{timestamp}.mp4")

    # Record
    bot.send_message(chat_id, f"▶️ Recording *{title}* for {duration} sec...")
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", url, "-t", str(duration), "-c", "copy", raw_file]
    )

    start_time = time.time()
    progress_msg = bot.send_message(chat_id, "📊 Recording… 0%")
    while proc.poll() is None:
        elapsed = int(time.time() - start_time)
        percent = min(100, int(elapsed * 100 / duration))
        bar = "█" * (percent // 5) + "░" * (20 - percent // 5)
        try:
            bot.edit_message_text(f"📊 Recording… {percent}% [{bar}] ({elapsed}s/{duration}s)", chat_id, progress_msg.message_id)
        except:
            pass
        time.sleep(2)

    if proc.returncode != 0:
        bot.send_message(chat_id, f"⚠️ ffmpeg exited with code {proc.returncode}")
        return

    bot.send_message(chat_id, f"✅ Recording completed: `{os.path.basename(raw_file)}`")

    # Split into small chunks for Telegram
    chunk_pattern = os.path.join(WORKDIR, f"{safe_title}_{timestamp}_chunk_%03d.mp4")
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", raw_file,
         "-c", "copy", "-f", "segment", "-segment_time", str(SPLIT_SECONDS),
         "-reset_timestamps", "1", chunk_pattern],
        check=True
    )

    chunks = sorted([os.path.join(WORKDIR, f) for f in os.listdir(WORKDIR)
                     if f.startswith(os.path.basename(f"{safe_title}_{timestamp}_chunk_")) and f.endswith(".mp4")])

    if not chunks:
        chunks = [raw_file]

    bot.send_message(chat_id, f"📦 Uploading {len(chunks)} part(s)...")

    # Upload each chunk safely
    for i, fpath in enumerate(chunks, 1):
        success = False
        for attempt in range(3):
            try:
                with open(fpath, "rb") as vid:
                    bot.send_video(chat_id, vid, caption=f"{title} — Part {i}/{len(chunks)}")
                success = True
                break
            except Exception as e:
                time.sleep(2)
        if not success:
            bot.send_message(chat_id, f"❌ Failed to upload part {i}")
        if os.path.exists(fpath):
            os.remove(fpath)

    # Remove raw file if exists
    if os.path.exists(raw_file):
        os.remove(raw_file)

    bot.send_message(chat_id, "🗑️ सभी files upload हो गए और local से delete कर दिए गए ✅")


# ---------------- RUN BOT ----------------
if __name__ == "__main__":
    print(f"🚀 {BOT_NAME} चल रहा है...")
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
