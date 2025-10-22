import telebot
import subprocess
import threading
import os
import time
import datetime
from functools import wraps
from telebot.apihelper import ApiTelegramException

# ---------------- CONFIG ----------------
BOT_TOKEN = "7994446557:AAFUdcVf18O0YkwOC0r9Rv4mvPGClCn6Z8s"
bot = telebot.TeleBot(BOT_TOKEN, num_threads=10)

PERMANENT_ADMIN = 6403142441
ADMIN_IDS = [6403142441, 7470440084]
approved_users = set(ADMIN_IDS)
pending_users = set()
DUMP_CHANNEL_ID = -1002627919828
SPLIT_SIZE_MB = 50
active_recordings = {}  # chat_id -> msg_id -> info

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
        if elapsed > total_seconds:
            elapsed = total_seconds
        percent = int((elapsed / total_seconds) * 100)
        bar = "█" * (percent // 5) + "░" * (20 - (percent // 5))
        safe_edit(f"🎬 Recording Progress\n📊 {percent}% [{bar}]\n⏱ {elapsed}s / {total_seconds}s\n🎯 {title}", chat_id, msg_id)
        time.sleep(2)

    proc.wait()

    if os.path.exists(output_file):
        filesize_mb = os.path.getsize(output_file)/(1024*1024)
        caption = (
            f"📁 Filename: {os.path.basename(output_file)}\n"
            f"⏱ Duration: {hms_format(total_seconds)}\n"
            f"📦 File-Size: {filesize_mb:.2f} MB"
        )
        thumb = generate_thumbnail(output_file)

        # Split if needed
        if filesize_mb > SPLIT_SIZE_MB:
            split_and_send(output_file, caption, chat_id, thumb)
        else:
            send_video(output_file, caption, chat_id, thumb)

        # Dump channel upload
        try:
            if filesize_mb > SPLIT_SIZE_MB:
                split_and_send(output_file, caption, DUMP_CHANNEL_ID, thumb)
            else:
                send_video(output_file, caption, DUMP_CHANNEL_ID, thumb)
        except: pass

        if os.path.exists(output_file):
            os.remove(output_file)
        if thumb and os.path.exists(thumb):
            os.remove(thumb)

    active_recordings[chat_id].pop(msg_id, None)
    if not active_recordings[chat_id]:
        active_recordings.pop(chat_id, None)

def send_video(filepath, caption, chat_id, thumb=None):
    with open(filepath, "rb") as f:
        bot.send_video(chat_id, f, caption=caption, thumb=open(thumb, "rb") if thumb else None)

def split_and_send(filepath, caption, chat_id, thumb=None):
    part_size = SPLIT_SIZE_MB*1024*1024
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
            part_caption = f"{caption}\n\n📄 Part {part}"
            send_video(part_file, part_caption, chat_id, thumb)
            if os.path.exists(part_file):
                os.remove(part_file)
            part +=1

# ---------------- COMMAND HANDLERS ----------------
@bot.message_handler(commands=['start'])
@admin_only
def start(message):
    bot.reply_to(message, "👋 Bot is online and running!\nUse /help to see available commands.")

@bot.message_handler(commands=['help'])
@admin_only
def help_cmd(message):
    text = """
Available Commands:
/record <URL> <HH:MM:SS> <title> - Record stream
/cancel - Cancel your recording (reply to your recording message)
/myrecordings - List your active recordings
/allrecordings - List all active recordings
/broadcast <msg> - Send message to approved users
/approve <user_id> - Approve user access
"""
    bot.reply_to(message, text)

@bot.message_handler(commands=['record'])
@admin_only
def record_cmd(message):
    try:
        parts = message.text.split(" ", 3)
        if len(parts)<4:
            return bot.reply_to(message, "Usage:\n/record <URL> <HH:MM:SS> <title>")
        url = parts[1]
        duration_str = parts[2]
        title = parts[3]

        # Parse duration
        dparts = duration_str.split(":")
        if len(dparts)==3:
            total_seconds = int(dparts[0])*3600 + int(dparts[1])*60 + int(dparts[2])
        elif len(dparts)==2:
            total_seconds = int(dparts[0])*60 + int(dparts[1])
        else:
            total_seconds = int(dparts[0])

        timestamp = datetime.datetime.now().strftime("%H-%M-%S.%d-%m-%Y")
        filename = f"{title}.{timestamp}.IPTV.WEB-DL.@Shitijbro.mkv"
        msg = bot.reply_to(message, f"🎬 Recording '{title}' for {hms_format(total_seconds)} started...")
        threading.Thread(target=record_stream, args=(message.chat.id, msg.message_id, url, total_seconds, title, filename)).start()
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

@bot.message_handler(commands=['cancel'])
@admin_only
def cancel(message):
    if not message.reply_to_message:
        return bot.reply_to(message, "Reply to your recording message to cancel.")
    chat_id = message.chat.id
    msg_id = message.reply_to_message.message_id
    if chat_id in active_recordings and msg_id in active_recordings[chat_id]:
        owner_id = active_recordings[chat_id][msg_id].get('user_id')
        if owner_id == message.from_user.id:
            proc = active_recordings[chat_id][msg_id]['proc']
            proc.terminate()
            bot.reply_to(message, "❌ Your recording canceled.")
        else:
            bot.reply_to(message, "⛔ You can only cancel your own recording.")
    else:
        bot.reply_to(message, "No active recording found.")

@bot.message_handler(commands=['myrecordings'])
@admin_only
def myrec(message):
    chat_id = message.chat.id
    if chat_id in active_recordings and active_recordings[chat_id]:
        text = "🎬 Your active recordings:\n"
        for msg_id, info in active_recordings[chat_id].items():
            if info.get('user_id') == message.from_user.id:
                text += f"- {info['title']} (PID: {info['proc'].pid})\n"
    else:
        text = "No active recordings."
    bot.reply_to(message, text)

@bot.message_handler(commands=['allrecordings'])
@admin_only
def allrec(message):
    total = sum(len(r) for r in active_recordings.values())
    if total==0:
        return bot.reply_to(message, "No active recordings.")
    text = f"🎬 All active recordings ({total}):\n"
    for chat_id, recs in active_recordings.items():
        text+=f"\nChat {chat_id}:\n"
        for msg_id, info in recs.items():
            text += f"- {info['title']} (PID: {info['proc'].pid})\n"
    bot.reply_to(message, text)

@bot.message_handler(commands=['approve'])
@admin_only
def approve(message):
    args = message.text.split()
    if len(args)<2:
        return bot.reply_to(message, "Usage: /approve <user_id>")
    try:
        uid = int(args[1])
        approved_users.add(uid)
        pending_users.discard(uid)
        bot.reply_to(message, f"✅ User {uid} approved!")
        bot.send_message(uid, "✅ You are approved to use the bot!")
    except:
        bot.reply_to(message, "Invalid user id.")

@bot.message_handler(commands=['broadcast'])
@admin_only
def broadcast(message):
    args = message.text.split(" ",1)
    if len(args)<2:
        return bot.reply_to(message, "Usage: /broadcast <message>")
    msg = args[1]
    for uid in approved_users:
        try:
            bot.send_message(uid, f"📢 Broadcast:\n\n{msg}")
        except: pass
    bot.reply_to(message, "✅ Broadcast sent to all approved users.")

# ---------------- RUN BOT ----------------
print("🤖 Bot is now running...")
bot.infinity_polling()
