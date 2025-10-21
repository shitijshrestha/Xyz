import telebot
import subprocess
import threading
import os
import time
import math
import io
from functools import wraps
from telebot.apihelper import ApiTelegramException

# ---------------- CONFIG ----------------
BOT_TOKEN = "7994446557:AAHoC-lsN137MmZfVMHiTWHRXRBHCFlwCKA"
bot = telebot.TeleBot(BOT_TOKEN, num_threads=10)

PERMANENT_ADMINS = [6403142441]  # Your Telegram ID
admin_ids = set(PERMANENT_ADMINS)
pending_users = set()

MAX_SIZE_MB = 50  # Telegram video part limit in MB
active_recordings = {}  # chat_id -> {msg_id: process_info}

# ---------------- DECORATORS ----------------
def admin_only(func):
    @wraps(func)
    def wrapped(message, *args, **kwargs):
        if message.from_user.id in admin_ids:
            return func(message, *args, **kwargs)
        else:
            bot.reply_to(message, "⛔ Admin only command!")
    return wrapped

def approved_only(func):
    @wraps(func)
    def wrapped(message, *args, **kwargs):
        if message.from_user.id in admin_ids:
            return func(message, *args, **kwargs)
        elif message.from_user.id in pending_users:
            bot.reply_to(message, "⏳ Your request is pending admin approval.")
        else:
            pending_users.add(message.from_user.id)
            bot.reply_to(message, "✋ You are not approved. Admins will approve you soon.")
    return wrapped

def safe_edit_message(text, chat_id, message_id, **kwargs):
    if len(text) > 4096:
        text = text[:4090] + "..."
    try:
        bot.edit_message_text(text, chat_id, message_id, **kwargs)
    except ApiTelegramException:
        pass

# ---------------- COMMANDS ----------------
@bot.message_handler(commands=['start'])
@approved_only
def start(message):
    bot.reply_to(message, "👋 Bot is running! Use /help to see all commands.")

@bot.message_handler(commands=['help'])
@approved_only
def help_command(message):
    text = """
📌 **Available Commands**

/start - Start bot  
/help - Show this help  
/status - Bot status  
/myrecordings - Your active recordings  
/record <URL> <hh:mm:ss> <title> - Record stream  
/cancel - Cancel a recording (reply to recording msg)  
/screenshot <URL> - Take single screenshot  

**Admin Commands**  
/allrecordings - View all active recordings  
/broadcast <msg> - Send broadcast to all admins  
/approve <user_id> - Approve pending user
"""
    bot.reply_to(message, text)

@bot.message_handler(commands=['status'])
@approved_only
def status(message):
    total = sum(len(r) for r in active_recordings.values())
    bot.reply_to(message, f"✅ Bot running. Active recordings: {total}")

@bot.message_handler(commands=['myrecordings'])
@approved_only
def myrecordings(message):
    chat_id = message.chat.id
    if chat_id in active_recordings and active_recordings[chat_id]:
        text = "🎬 Your active recordings:\n"
        for msg_id, info in active_recordings[chat_id].items():
            text += f"- {info['title']} (PID: {info['proc'].pid})\n"
    else:
        text = "No active recordings."
    bot.reply_to(message, text)

# ---------------- ADMIN COMMANDS ----------------
@bot.message_handler(commands=['allrecordings'])
@admin_only
def allrecordings(message):
    total = sum(len(r) for r in active_recordings.values())
    if total == 0:
        bot.reply_to(message, "No active recordings.")
        return
    text = f"🎬 All active recordings ({total}):\n"
    for chat_id, recs in active_recordings.items():
        text += f"\nChat {chat_id}:\n"
        for msg_id, info in recs.items():
            text += f"- {info['title']} (PID: {info['proc'].pid})\n"
    bot.reply_to(message, text)

@bot.message_handler(commands=['broadcast'])
@admin_only
def broadcast(message):
    try:
        text = message.text.split(None, 1)[1]
        for admin in admin_ids:
            bot.send_message(admin, f"📢 Broadcast:\n{text}")
        bot.reply_to(message, "✅ Broadcast sent.")
    except:
        bot.reply_to(message, "Usage: /broadcast <message>")

@bot.message_handler(commands=['approve'])
@admin_only
def approve(message):
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /approve <user_id>")
        return
    try:
        user_id = int(args[1])
    except:
        bot.reply_to(message, "❌ Invalid user_id.")
        return
    if user_id in pending_users:
        admin_ids.add(user_id)
        pending_users.remove(user_id)
        bot.reply_to(message, f"✅ User {user_id} approved as admin.")
        bot.send_message(user_id, "✅ You have been approved! You can now use the bot.")
    else:
        bot.reply_to(message, "User is not in pending list.")

# ---------------- RECORD & UPLOAD ----------------
@bot.message_handler(commands=['screenshot'])
@approved_only
def screenshot(message):
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /screenshot <URL>")
        return
    url = args[1]
    filename = f"screenshot_{int(time.time())}.jpg"
    cmd = ['ffmpeg', '-y', '-i', url, '-vframes', '1', filename]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if os.path.exists(filename):
        with open(filename, 'rb') as f:
            bot.send_photo(message.chat.id, f, caption=f"Screenshot from {url}")
        os.remove(filename)
    else:
        bot.reply_to(message, "❌ Screenshot failed.")

@bot.message_handler(commands=['record'])
@approved_only
def record(message):
    args = message.text.split()
    if len(args) < 4:
        bot.reply_to(message, "Usage: /record <URL> <hh:mm:ss> <title>")
        return
    url = args[1]
    try:
        h, m, s = map(int, args[2].split(":"))
        duration_sec = h * 3600 + m * 60 + s
    except:
        bot.reply_to(message, "Invalid duration format. Use hh:mm:ss")
        return
    title = " ".join(args[3:])
    timestamp = int(time.time())
    output_file = f"rec_{message.chat.id}_{timestamp}.mp4"
    sent_msg = bot.reply_to(message, f"🎬 Recording '{title}' for {args[2]} started...")
    msg_id = sent_msg.message_id
    threading.Thread(target=record_stream, args=(message.chat.id, msg_id, url, duration_sec, title, output_file)).start()

@bot.message_handler(commands=['cancel'])
@approved_only
def cancel(message):
    if not message.reply_to_message:
        bot.reply_to(message, "Reply to recording message to cancel.")
        return
    chat_id = message.chat.id
    msg_id = message.reply_to_message.message_id
    if chat_id in active_recordings and msg_id in active_recordings[chat_id]:
        proc = active_recordings[chat_id][msg_id]['proc']
        proc.terminate()
        bot.reply_to(message, "❌ Recording canceled.")
    else:
        bot.reply_to(message, "No active recording found.")

# ---------------- RECORDING FUNCTIONS ----------------
def record_stream(chat_id, msg_id, url, duration_sec, title, output_file):
    if chat_id not in active_recordings:
        active_recordings[chat_id] = {}
    cmd = ['ffmpeg', '-y', '-i', url, '-t', str(duration_sec), '-c', 'copy', output_file]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    active_recordings[chat_id][msg_id] = {'proc': proc, 'title': title}
    proc.wait()

    if os.path.exists(output_file):
        safe_edit_message(f"✅ Recording finished. Uploading...", chat_id, msg_id)
        split_and_send(chat_id, msg_id, output_file, title, duration_sec)
    else:
        safe_edit_message(f"❌ Recording failed.", chat_id, msg_id)

    active_recordings[chat_id].pop(msg_id, None)
    if not active_recordings[chat_id]:
        active_recordings.pop(chat_id, None)

def split_and_send(chat_id, msg_id, file_path, title, duration_sec):
    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    if file_size_mb <= MAX_SIZE_MB:
        send_file(chat_id, msg_id, file_path, title, duration_sec)
        os.remove(file_path)
        return
    num_parts = math.ceil(file_size_mb / MAX_SIZE_MB)
    base, ext = os.path.splitext(file_path)
    for i in range(num_parts):
        part_file = f"{base}_part{i+1}{ext}"
        cmd = ['ffmpeg', '-y', '-i', file_path, '-ss', str(i * duration_sec / num_parts),
               '-t', str(duration_sec / num_parts), '-c', 'copy', part_file]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        send_file(chat_id, msg_id, part_file, f"{title} Part {i+1}/{num_parts}", duration_sec / num_parts)
        os.remove(part_file)

def send_file(chat_id, msg_id, file_path, caption, duration_sec):
    status_msg = bot.send_message(chat_id, f"⬆️ Uploading '{caption}'...")

    with open(file_path, 'rb') as f:
        bot.send_video(chat_id, f, caption=f"🎥 {caption}")
    safe_edit_message("✅ Upload complete!", chat_id, status_msg.message_id)

# ---------------- START BOT ----------------
print("🤖 Bot started!")
bot.infinity_polling()
