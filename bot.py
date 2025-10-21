import telebot
import subprocess
import threading
import os
import time
import datetime
from telebot.apihelper import ApiTelegramException
import math

# ---------------- CONFIG ----------------
BOT_TOKEN = "7994446557:AAEB_sV9KQmSjlbFHrZ4y0hpd3Ldgi7bCI0"
DUMP_CHANNEL_ID = -1002627919828  # Dump channel
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
MAX_SIZE_BYTES = 2 * 1024 * 1024 * 1024  # 2GB limit

# ---------------- HELPERS ----------------
def time_to_seconds(t):
    """Convert 00:10:00 or 600 -> seconds"""
    try:
        if ":" in t:
            h, m, s = t.split(":")
            return int(h) * 3600 + int(m) * 60 + int(s)
        return int(t)
    except:
        return 10  # fallback

def split_and_upload(filename, title):
    """Split recorded video into 2GB chunks and upload each"""
    if not os.path.exists(filename):
        return

    # Check total file size
    total_size = os.path.getsize(filename)
    if total_size <= MAX_SIZE_BYTES:
        # Single upload
        size_mb = total_size / (1024 * 1024)
        caption = f"📁 Filename: {filename}\n💾 File-Size: {size_mb:.2f} MB\n☎️ @Shitijbro"
        with open(filename, "rb") as video:
            bot.send_video(DUMP_CHANNEL_ID, video, caption=caption)
        os.remove(filename)
        return

    # Split using ffmpeg into chunks <2GB
    # Estimate chunk duration proportionally
    total_duration = float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", filename]
    ).decode().strip())
    num_chunks = math.ceil(total_size / MAX_SIZE_BYTES)
    chunk_duration = total_duration / num_chunks

    for i in range(num_chunks):
        start_time = i * chunk_duration
        chunk_file = f"{filename}_part{i+1}.mkv"
        cmd = [
            "./ffmpeg", "-y", "-i", filename,
            "-ss", str(start_time), "-t", str(chunk_duration),
            "-c", "copy", chunk_file
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        size_mb = os.path.getsize(chunk_file) / (1024 * 1024)
        duration_str = str(datetime.timedelta(seconds=int(min(chunk_duration, total_duration - start_time))))
        caption = f"📁 Filename: {chunk_file}\n⏱ Duration: {duration_str}\n💾 File-Size: {size_mb:.2f} MB\n☎️ @Shitijbro"
        with open(chunk_file, "rb") as video:
            bot.send_video(DUMP_CHANNEL_ID, video, caption=caption)
        os.remove(chunk_file)

# ---------------- RECORD FUNCTION ----------------
def record_stream(chat_id, url, duration_str, title):
    duration = time_to_seconds(duration_str)
    start_time = datetime.datetime.now().strftime("%H-%M-%S")
    end_time = (datetime.datetime.now() + datetime.timedelta(seconds=duration)).strftime("%H-%M-%S")
    date_now = datetime.datetime.now().strftime("%d-%m-%Y")

    filename = f"Untitled.Direct Stream.{start_time}-{end_time}.{date_now}.IPTV.WEB-DL.@Shitijbro.mkv"

    # Send start message
    msg = bot.send_message(chat_id, f"🎬 Recording Started!\n🎥 <b>{title}</b>\n⏱ Duration: {duration_str}\n🔗 URL: {url}")

    # Start ffmpeg process
    cmd = ["./ffmpeg", "-y", "-i", url, "-t", str(duration), "-c", "copy", filename]
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    start = time.time()

    # Live progress update
    while process.poll() is None:
        elapsed = int(time.time() - start)
        percent = min(100, (elapsed / duration) * 100)
        filled = int(percent // 10)
        bar = "█" * filled + "░" * (10 - filled)
        try:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg.message_id,
                text=f"🎥 Recording <b>{title}</b>\n📊 {percent:.1f}% [{bar}]\n⏱ {elapsed}s/{duration}s",
                parse_mode="HTML"
            )
        except ApiTelegramException:
            pass
        time.sleep(5)

    process.wait()
    bot.send_message(chat_id, f"✅ Recording Finished. Uploading <b>{title}</b>...", parse_mode="HTML")

    # Split into 2GB chunks if needed and upload
    split_and_upload(filename, title)

    # Delete original file
    if os.path.exists(filename):
        os.remove(filename)
    bot.send_message(chat_id, f"✅ Upload Complete for <b>{title}</b>", parse_mode="HTML")

# ---------------- COMMAND HANDLER ----------------
@bot.message_handler(commands=['record'])
def record_handler(message):
    try:
        args = message.text.split(" ", 3)
        if len(args) < 3:
            bot.reply_to(message, "❌ Usage:\n/record <url> <duration> <title>")
            return
        url = args[1]
        duration_str = args[2]
        title = args[3] if len(args) > 3 else "Untitled"

        threading.Thread(target=record_stream, args=(message.chat.id, url, duration_str, title)).start()
    except Exception as e:
        bot.reply_to(message, f"⚠️ Error: {e}")

# ---------------- START BOT ----------------
print("🤖 Bot Started. Listening for /record ...")
bot.infinity_polling()
