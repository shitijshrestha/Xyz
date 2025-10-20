import telebot
from telebot.apihelper import ApiTelegramException
import subprocess
import threading
import os
import io
import time
import psutil
import math
import json
from functools import wraps

# ---------------- CONFIG ----------------
BOT_TOKEN = "7994446557:AAHoC-lsN137MmZfVMHiTWHRXRBHCFlwCKA"
bot = telebot.TeleBot(BOT_TOKEN, num_threads=15)

PERMANENT_ADMINS = [6403142441]  # Permanent admin(s)
approved_users_file = "approved_users.json"
active_recordings = {}
MAX_RECORDINGS_PER_USER = 3
SPLIT_SIZE_MB = 40  # Split video if >40MB

# ---------------- USER APPROVAL ----------------
if not os.path.exists(approved_users_file):
    with open(approved_users_file, "w") as f:
        json.dump(PERMANENT_ADMINS, f)

def load_approved_users():
    with open(approved_users_file, "r") as f:
        return json.load(f)

def save_approved_users(users):
    with open(approved_users_file, "w") as f:
        json.dump(users, f)

def user_approved(user_id):
    return user_id in load_approved_users()

def requires_approval(func):
    @wraps(func)
    def wrapped(message, *args, **kwargs):
        if message.from_user.id in PERMANENT_ADMINS or user_approved(message.from_user.id):
            return func(message, *args, **kwargs)
        else:
            bot.reply_to(message, "⛔️ You are not approved to use this bot. Ask admin for access.")
            return
    return wrapped

def admin_only(func):
    @wraps(func)
    def wrapped(message, *args, **kwargs):
        if message.from_user.id in load_approved_users():
            return func(message, *args, **kwargs)
        else:
            bot.reply_to(message, "⛔️ Admin only command.")
            return
    return wrapped

# ---------------- PUBLIC COMMANDS ----------------
@bot.message_handler(commands=['start'])
@requires_approval
def start(message):
    bot.reply_to(message, "👋 Hello! I'm your recording bot.\nUse /help to see commands.")

@bot.message_handler(commands=['help'])
@requires_approval
def help_command(message):
    help_text = f"""
/start - Welcome message
/help - Show this help
/getid - Show your user ID

*Recording Commands:*
/record <url> [duration_sec] [title] - Start recording
/cancel - Cancel a recording (reply to recording message)
/myrecordings - List your active recordings
/screenshot <url> - Take screenshot
/status - Bot status
"""
    if message.from_user.id in PERMANENT_ADMINS:
        help_text += """
*Admin Commands:*
/allrecordings - Show all active recordings
/broadcast <message> - Send message to all approved users
/addadmin <user_id> - Approve user to use bot
/reboot - Restart bot
"""
    bot.reply_to(message, help_text)

@bot.message_handler(commands=['getid'])
@requires_approval
def get_id(message):
    bot.reply_to(message, f"Your User ID: `{message.from_user.id}`", parse_mode='Markdown')

# ---------------- ADMIN COMMANDS ----------------
@bot.message_handler(commands=['addadmin'])
@admin_only
def add_admin(message):
    try:
        user_id = int(message.text.split()[1])
        users = load_approved_users()
        if user_id not in users:
            users.append(user_id)
            save_approved_users(users)
            bot.reply_to(message, f"✅ User {user_id} approved successfully.")
        else:
            bot.reply_to(message, f"User {user_id} is already approved.")
    except:
        bot.reply_to(message, "Usage: /addadmin <user_id>")

@bot.message_handler(commands=['allrecordings'])
@admin_only
def all_recordings(message):
    total = sum(len(r) for r in active_recordings.values())
    if total == 0:
        bot.reply_to(message, "No active recordings.")
        return
    response = f"All active recordings ({total}):\n"
    for chat, recs in active_recordings.items():
        response += f"\nChat ID {chat}:\n"
        for msg_id, info in recs.items():
            response += f"- {info['title']}: {info['progress']}\n"
    bot.reply_to(message, response)

@bot.message_handler(commands=['broadcast'])
@admin_only
def broadcast(message):
    try:
        text = message.text.split(None,1)[1]
        users = load_approved_users()
        for u in users:
            try:
                bot.send_message(u, f"📢 Broadcast:\n{text}")
            except:
                continue
        bot.reply_to(message, "✅ Broadcast sent.")
    except:
        bot.reply_to(message, "Usage: /broadcast <message>")

@bot.message_handler(commands=['reboot'])
@admin_only
def reboot_bot(message):
    bot.reply_to(message, "♻️ Rebooting...")
    import sys
    import subprocess
    subprocess.Popen([sys.executable]+sys.argv)
    os._exit(0)

# ---------------- CORE FUNCTIONALITY ----------------
@bot.message_handler(commands=['status'])
@requires_approval
def status(message):
    total = sum(len(r) for r in active_recordings.values())
    bot.reply_to(message, f"✅ Bot is running\nActive recordings: {total}")

@bot.message_handler(commands=['myrecordings'])
@requires_approval
def my_recordings(message):
    chat_id = message.chat.id
    if chat_id in active_recordings and active_recordings[chat_id]:
        response = "Your active recordings:\n"
        for msg_id, rec in active_recordings[chat_id].items():
            response += f"- {rec['title']}: {rec['progress']}\n"
        bot.reply_to(message, response)
    else:
        bot.reply_to(message, "You have no active recordings.")

@bot.message_handler(commands=['cancel'])
@requires_approval
def cancel_recording(message):
    if not message.reply_to_message:
        bot.reply_to(message, "Reply to recording message to cancel.")
        return
    chat_id = message.chat.id
    msg_id = message.reply_to_message.message_id
    if chat_id in active_recordings and msg_id in active_recordings[chat_id]:
        pid = active_recordings[chat_id][msg_id]['pid']
        try:
            p = psutil.Process(pid)
            for c in p.children(recursive=True): c.kill()
            p.kill()
            active_recordings[chat_id][msg_id]['canceled'] = True
            bot.reply_to(message, f"✅ Recording '{active_recordings[chat_id][msg_id]['title']}' canceled.")
        except:
            bot.reply_to(message, "Process not found or already finished.")
    else:
        bot.reply_to(message, "No active recording found for this message.")

# ---------------- RECORDING ----------------
@bot.message_handler(commands=['record'])
@requires_approval
def record(message):
    chat_id = message.chat.id
    if chat_id in active_recordings and len(active_recordings[chat_id]) >= MAX_RECORDINGS_PER_USER:
        bot.reply_to(message, f"Maximum {MAX_RECORDINGS_PER_USER} recordings reached.")
        return
    try:
        args = message.text.split()[1:]
        if not args:
            bot.reply_to(message, "Usage: /record <url> [duration_sec] [title]")
            return
        url = args[0]
        duration = int(args[1]) if len(args) > 1 else 300
        title = " ".join(args[2:]) if len(args) > 2 else "Untitled"
        timestamp = int(time.time())
        output_file = f"recording_{chat_id}_{timestamp}.mp4"
        sent_msg = bot.reply_to(message, f"🎬 Recording '{title}' started for {duration}s.")
        thread = threading.Thread(target=record_stream, args=(message, sent_msg.message_id, url, duration, title, output_file))
        thread.start()
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

def record_stream(message, msg_id, url, duration, title, output_file):
    chat_id = message.chat.id
    cmd = ['ffmpeg','-y','-i',url,'-t',str(duration),'-c','copy','-progress','pipe:1',output_file]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, encoding='utf-8', errors='ignore')
    if chat_id not in active_recordings: active_recordings[chat_id]={}
    active_recordings[chat_id][msg_id]={'pid':proc.pid,'title':title,'canceled':False,'progress':'Initializing...'}
    last_update = 0
    for line in proc.stdout:
        if 'canceled' in active_recordings[chat_id][msg_id] and active_recordings[chat_id][msg_id]['canceled']:
            break
        if 'out_time_ms' in line:
            t_ms = int(line.strip().split('=')[1])
            progress = (t_ms/(duration*1000000))*100
            now = time.time()
            if now-last_update>5:
                bar = '█'*int(progress/10)+'░'*(10-int(progress/10))
                elapsed = time.strftime('%H:%M:%S',time.gmtime(t_ms/1000000))
                dur_str = time.strftime('%H:%M:%S',time.gmtime(duration))
                text = f"🔴 Recording '{title}'\n`{bar}` {progress:.1f}%\n`{elapsed} / {dur_str}`"
                safe_edit_message(text, chat_id, msg_id, parse_mode='Markdown')
                last_update=now
    proc.wait()
    if active_recordings[chat_id][msg_id]['canceled']:
        safe_edit_message(f"❌ Recording '{title}' canceled.", chat_id, msg_id)
        if os.path.exists(output_file): os
