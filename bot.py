#!/usr/bin/env python3
# ShitijBot — Full IPTV Recorder for VPS/Termux

import os
import time
import json
import threading
import subprocess
from datetime import datetime, timedelta
import telebot

# ---------------- CONFIG ----------------
BOT_TOKEN = "7994446557:AAHoC-lsN137MmZfVMHiTWHRXRBHCFlwCKA"  # Your bot token
ADMIN_ID = 6403142441  # Your Telegram ID
BOT_NAME = "Shitij𝔹ot"
WORKDIR = "/root/Shitijbot"
SPLIT_SECONDS = 5 * 60  # 5-minute split
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


def parse_time_pair(start, end):
    """Parses HH:MM into datetime objects."""
    now = datetime.now()
    st = datetime.strptime(start, "%H:%M")
    en = datetime.strptime(end, "%H:%M")
    start_dt = now.replace(hour=st.hour, minute=st.minute, second=0, microsecond=0)
    end_dt = now.replace(hour=en.hour, minute=en.minute, second=0, microsecond=0)
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)
    return start_dt, end_dt


# ---------------- COMMANDS ----------------
@bot.message_handler(commands=["start"])
def start_cmd(msg):
    bot.reply_to(
        msg,
        f"👋 Welcome to *{BOT_NAME}*\n\n"
        "📌 Usage:\n`/record <url> <start_HH:MM> <end_HH:MM> <title>`\n\n"
        "📝 Example:\n`/record https://example.com/live.m3u8 20:30 21:15 Ramayan_HD`\n\n"
        "⏰ Records from 8:30 PM to 9:15 PM and auto-splits 5-min chunks."
    )


@bot.message_handler(commands=["help"])
def help_cmd(msg):
    bot.reply_to(
        msg,
        "🆘 *Help Guide*\n\n"
        "Use:\n`/record <url> <start_HH:MM> <end_HH:MM> <title>`\n\n"
        "Admin only commands:\n`/addadmin <user_id>`",
    )


@bot.message_handler(commands=["addadmin"])
def addadmin_cmd(msg):
    if not is_admin(msg.from_user.id):
        bot.reply_to(msg, "❌ Only admins can add admins.")
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
        bot.reply_to(msg, "❌ Only admins can schedule recordings.")
        return
    parts = msg.text.strip().split(maxsplit=4)
    if len(parts) < 5:
        bot.reply_to(msg, "📌 Usage: /record <url> <start_HH:MM> <end_HH:MM> <title>")
        return

    _, url, st, en, title = parts
    try:
        start_dt, end_dt = parse_time_pair(st, en)
    except ValueError as e:
        bot.reply_to(msg, f"⚠️ Error: {e}")
        return

    duration = int((end_dt - start_dt).total_seconds())
    bot.reply_to(
        msg,
        f"🎬 *Recording Scheduled!*\n\n"
        f"🎥 *Title:* {title}\n"
        f"🔗 *URL:* {url}\n"
        f"🕒 *Start:* {start_dt.strftime('%d %b %Y • %I:%M %p')}\n"
        f"🕒 *End:* {end_dt.strftime('%d %b %Y • %I:%M %p')}\n"
        f"⏱ *Duration:* {duration//60} min {duration%60} sec\n"
        f"✂️ Auto-split every 5 min for safe upload.\n⚡ Live progress will be sent."
    )

    threading.Thread(
        target=schedule_recording,
        args=(url, start_dt, end_dt, title, msg.chat.id),
        daemon=True,
    ).start()


# ---------------- RECORDING ENGINE ----------------
def schedule_recording(url, start_dt, end_dt, title, chat_id):
    wait = (start_dt - datetime.now()).total_seconds()
    if wait > 0:
        bot.send_message(chat_id, f"⏳ Waiting {int(wait)}s until {start_dt.strftime('%I:%M %p')}")
        time.sleep(wait)
    try:
        recording_and_upload(url, start_dt, end_dt, title, chat_id)
    except Exception as e:
        bot.send_message(chat_id, f"❌ Recording failed: {e}")


def recording_and_upload(url, start_dt, end_dt, title, chat_id):
    safe_title = "".join(c if c.isalnum() or c in " _-." else "_" for c in title)[:70]
    out_base = os.path.join(WORKDIR, f"{safe_title}_{start_dt.strftime('%Y%m%d_%H%M%S')}")
    raw_file = f"{out_base}.mp4"
    duration = int((end_dt - start_dt).total_seconds())

    bot.send_message(chat_id, f"▶️ Started recording *{title}* for {duration//60} m {duration%60} s...")

    proc = subprocess.Popen(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                             "-i", url, "-t", str(duration), "-c", "copy", raw_file])

    start_time = time.time()
    last_msg_time = 0
    while proc.poll() is None:
        elapsed = int(time.time() - start_time)
        if elapsed - last_msg_time >= 15:
            bot.send_message(chat_id, f"📊 Recording… {elapsed}s elapsed")
            last_msg_time = elapsed
        time.sleep(1)

    if proc.returncode != 0:
        bot.send_message(chat_id, f"⚠️ ffmpeg exited with code {proc.returncode}")
        return

    bot.send_message(chat_id, f"✅ Recording completed: `{os.path.basename(raw_file)}`")

    # Split into chunks
    chunk_pattern = f"{out_base}_chunk_%03d.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", raw_file,
         "-c", "copy", "-f", "segment", "-segment_time", str(SPLIT_SECONDS),
         "-reset_timestamps", "1", chunk_pattern],
        check=True
    )

    chunks = sorted([os.path.join(WORKDIR, f) for f in os.listdir(WORKDIR)
                     if f.startswith(os.path.basename(out_base + "_chunk_")) and f.endswith(".mp4")])

    if not chunks:
        chunks = [raw_file]

    bot.send_message(chat_id, f"📦 Uploading {len(chunks)} part(s)...")

    for i, fpath in enumerate(chunks, 1):
        try:
            msg = bot.send_message(chat_id, f"⬆️ Uploading part {i}/{len(chunks)}...")
            with open(fpath, "rb") as vid:
                bot.send_video(chat_id, vid, caption=f"{title} — Part {i}/{len(chunks)}")
            bot.edit_message_text(f"✅ Uploaded part {i}/{len(chunks)}", chat_id, msg.message_id)
        except Exception as e:
            bot.send_message(chat_id, f"❌ Upload failed: {e}")

    for fpath in chunks + [raw_file]:
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
            except:
                pass

    bot.send_message(chat_id, "🗑️ Local files deleted after upload ✅")


# ---------------- RUN BOT ----------------
if __name__ == "__main__":
    print(f"🚀 {BOT_NAME} is running...")
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
