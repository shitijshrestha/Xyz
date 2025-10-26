import telebot
import subprocess
import threading
import os
import time
import datetime
import requests
from functools import wraps
from telebot.apihelper import ApiTelegramException

# ---------------- CONFIG ----------------
BOT_TOKEN = "7994446557:AAHtM5FerKiv46dL1AfwlOrhTc1Y8lVvNq8"  # Replace with your bot token
bot = telebot.TeleBot(BOT_TOKEN, num_threads=10)

PERMANENT_ADMIN = 6403142441
ADMIN_IDS = [PERMANENT_ADMIN]
approved_users = set(ADMIN_IDS)
pending_users = set()
DUMP_CHANNEL_ID = -1002627919828
SPLIT_SIZE_MB = 49.6  # Telegram bot upload part size in MB
active_recordings = {}  # chat_id -> msg_id -> info

# Playlist URL
PLAYLIST_URL = "https://maxtv4kkk-rkdyiptv.pages.dev/"

# ---------------- DECORATORS ----------------
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
    if len(text) > 4096:
        text = text[:4090] + "..."
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

# ---------------- PLAYLIST ----------------
def fetch_playlist():
    try:
        r = requests.get(PLAYLIST_URL)
        r.raise_for_status()
        lines = r.text.splitlines()
        playlist = {}
        for i in range(len(lines)):
            if lines[i].startswith("#EXTINF:"):
                name = lines[i].split(",",1)[1].strip()
                url = lines[i+1].strip()
                playlist[str(i+1)] = {"name": name, "url": url}
        return playlist
    except:
        return {}

# ---------------- RECORDING ----------------
def record_stream(chat_id, msg_id, url, total_seconds, title, output_file):
    if chat_id not in active_recordings:
        active_recordings[chat_id] = {}
    cmd = ["ffmpeg", "-y", "-i", url, "-t", str(total_seconds), "-c", "copy", output_file]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    active_recordings[chat_id][msg_id] = {'proc': proc, 'title': title, 'user_id': chat_id}

    start_time = time.time()
    while proc.poll() is None:
        elapsed = int(time.time() - start_time)
        percent = int((elapsed / total_seconds) * 100) if total_seconds>0 else 0
        bar = "█" * (percent // 5) + "░" * (20 - (percent // 5))
        safe_edit(f"🎬 Recording Progress\n📊 {percent}% [{bar}]\n⏱ {hms_format(elapsed)} / {hms_format(total_seconds)}\n🎯 {title}", chat_id, msg_id)
        time.sleep(2)

    proc.wait()

    if os.path.exists(output_file):
        filesize_mb = os.path.getsize(output_file)/(1024*1024)
        caption = (
            f"━━━━━━━━━━━━━━\n"
            f"📁 Filename: {os.path.basename(output_file)}\n"
            f"⏱ Duration: {hms_format(total_seconds)}\n"
            f"📦 File Size: {filesize_mb:.2f} MB\n"
            f"🖥 Resolution: 1280x720\n"
            f"Part\n👨‍💻 Bot developer: @Shitijbro\n"
            f"━━━━━━━━━━━━━━"
        )
        thumb = generate_thumbnail(output_file)

        # Split & upload
        split_and_send(output_file, caption, chat_id, thumb)
        split_and_send(output_file, caption, DUMP_CHANNEL_ID, thumb)

        # Cleanup
        if os.path.exists(output_file):
            os.remove(output_file)
        if thumb and os.path.exists(thumb):
            os.remove(thumb)

    active_recordings[chat_id].pop(msg_id, None)
    if not active_recordings[chat_id]:
        active_recordings.pop(chat_id, None)

# ---------------- UPLOAD FUNCTIONS ----------------
def send_video(filepath, caption, chat_id, thumb=None):
    try:
        with open(filepath, "rb") as video_file:
            if thumb and os.path.exists(thumb):
                with open(thumb, "rb") as thumb_file:
                    bot.send_video(chat_id, video_file, caption=caption, thumb=thumb_file)
            else:
                bot.send_video(chat_id, video_file, caption=caption)
    except Exception as e:
        bot.send_message(chat_id, f"❌ Upload failed: {e}")

def split_and_send(filepath, caption, chat_id, thumb=None):
    part_size = int(SPLIT_SIZE_MB * 1024 * 1024)
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
            part_caption = f"{caption}\n📄 Part {part}"
            bot.send_message(chat_id, f"📤 Uploading Part {part}...")
            retry_upload(part_file, part_caption, chat_id, thumb)
            if os.path.exists(part_file):
                os.remove(part_file)
            part += 1

def retry_upload(file, caption, chat_id, thumb, retries=3):
    for attempt in range(retries):
        try:
            send_video(file, caption, chat_id, thumb)
            break
        except:
            time.sleep(5)

# ---------------- COMMAND HANDLERS ----------------
@bot.message_handler(commands=['start'])
@admin_only
def start(message):
    bot.reply_to(message, "👋 Bot is online!\nUse /help to see commands.")

@bot.message_handler(commands=['help'])
@admin_only
def help_cmd(message):
    text = """
/find <name> - Search channel from playlist
/rec <id> <HH:MM:SS> <title> - Record selected channel by ID
/cancel - Cancel your recording
/myrecordings - List your active recordings
/allrecordings - List all active recordings
/broadcast <msg> - Send message to approved users
/approve <user_id> - Approve user
"""
    bot.reply_to(message, text)

@bot.message_handler(commands=['find'])
@admin_only
def find_cmd(message):
    args = message.text.split(" ",1)
    if len(args)<2:
        return bot.reply_to(message, "Usage: /find <name>")
    name = args[1].lower()
    playlist = fetch_playlist()
    results = []
    for id, info in playlist.items():
        if name in info['name'].lower():
            results.append(f"{id} - {info['name']}")
    if results:
        bot.reply_to(message, "🔎 Found:\n" + "\n".join(results))
    else:
        bot.reply_to(message, "No results found.")

@bot.message_handler(commands=['rec'])
@admin_only
def rec_cmd(message):
    parts = message.text.split(" ",3)
    if len(parts)<3:
        return bot.reply_to(message, "Usage: /rec <id> <HH:MM:SS> <title>")
    stream_id = parts[1]
    duration_str = parts[2]
    title = parts[3] if len(parts)>=4 else "Recording"

    playlist = fetch_playlist()
    if stream_id not in playlist:
        return bot.reply_to(message, "Invalid ID.")

    url = playlist[stream_id]['url']

    # Parse duration
    dparts = duration_str.split(":")
    if len(dparts)==3:
        total_seconds = int(dparts[0])*3600 + int(dparts[1])*60 + int(dparts[2])
    elif len(dparts)==2:
        total_seconds = int(dparts[0])*60 + int(dparts[1])
    else:
        total_seconds = int(dparts[0])

    timestamp = datetime.datetime.now().strftime("%H-%M-%S.%d-%m-%Y")
    filename = f"{title}.{timestamp}.IPTV.WEB-DL.Shitij.mp4"
    msg = bot.reply_to(message, f"🎬 Recording **'{title}'** started ({total_seconds}s).")
    threading.Thread(target=record_stream, args=(message.chat.id, msg.message_id, url, total_seconds, title, filename)).start()

# ---------------- RUN BOT ----------------
print("🤖 Bot is running...")
bot.infinity_polling()
