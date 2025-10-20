import telebot
import subprocess
import threading
import os
import io
import time
import math
import json
from functools import wraps

# ---------------- CONFIG ----------------
BOT_TOKEN = "7994446557:AAHoC-lsN137MmZfVMHiTWHRXRBHCFlwCKA"
bot = telebot.TeleBot(BOT_TOKEN, num_threads=15)

PERMANENT_ADMINS = [6403142441]
approved_users_file = "approved_users.json"
active_recordings = {}
SPLIT_SIZE_MB = 40  # Split if video > 40MB

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
            bot.reply_to(message, "⛔️ You are not approved. Ask admin for access.")
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

# ---------------- HELP & INFO ----------------
@bot.message_handler(commands=['start'])
@requires_approval
def start(message):
    bot.reply_to(message, "👋 Welcome! Use /help to see commands.")

@bot.message_handler(commands=['help'])
@requires_approval
def help_command(message):
    help_text = """
/start - Welcome
/help - This help
/getid - Your user ID
/record <url> [duration_sec] [title] - Start recording
/myrecordings - List active recordings
/status - Bot status
/cancel - Cancel recording (reply)
/screenshot <url> - Take screenshot
"""
    if message.from_user.id in PERMANENT_ADMINS:
        help_text += """
*Admin Commands*
/addadmin <user_id> - Approve user
/allrecordings - Show all recordings
/broadcast <msg> - Send to all
/reboot - Restart bot
"""
    bot.reply_to(message, help_text)

@bot.message_handler(commands=['getid'])
@requires_approval
def get_id(message):
    bot.reply_to(message, f"Your ID: `{message.from_user.id}`", parse_mode="Markdown")

# ---------------- ADMIN ----------------
@bot.message_handler(commands=['addadmin'])
@admin_only
def add_admin(message):
    try:
        user_id = int(message.text.split()[1])
        users = load_approved_users()
        if user_id not in users:
            users.append(user_id)
            save_approved_users(users)
            bot.reply_to(message, f"✅ User {user_id} approved.")
        else:
            bot.reply_to(message, "User already approved.")
    except:
        bot.reply_to(message, "Usage: /addadmin <user_id>")

@bot.message_handler(commands=['allrecordings'])
@admin_only
def all_recordings(message):
    if not active_recordings:
        bot.reply_to(message, "No active recordings.")
        return
    text = "Active recordings:\n"
    for chat, recs in active_recordings.items():
        for mid, info in recs.items():
            text += f"- {info['title']}\n"
    bot.reply_to(message, text)

@bot.message_handler(commands=['broadcast'])
@admin_only
def broadcast(message):
    try:
        text = message.text.split(None,1)[1]
        for uid in load_approved_users():
            try: bot.send_message(uid, f"📢 {text}")
            except: continue
        bot.reply_to(message, "✅ Broadcast sent.")
    except:
        bot.reply_to(message, "Usage: /broadcast <msg>")

@bot.message_handler(commands=['reboot'])
@admin_only
def reboot_bot(message):
    bot.reply_to(message, "♻️ Rebooting...")
    import sys
    import subprocess
    subprocess.Popen([sys.executable]+sys.argv)
    os._exit(0)

# ---------------- RECORDING ----------------
@bot.message_handler(commands=['status'])
@requires_approval
def status(message):
    total = sum(len(v) for v in active_recordings.values())
    bot.reply_to(message, f"✅ Bot running\nActive recordings: {total}")

@bot.message_handler(commands=['myrecordings'])
@requires_approval
def my_recordings(message):
    recs = active_recordings.get(message.chat.id, {})
    if not recs:
        bot.reply_to(message, "No active recordings.")
        return
    text = "Your recordings:\n"
    for mid, info in recs.items():
        text += f"- {info['title']}\n"
    bot.reply_to(message, text)

@bot.message_handler(commands=['record'])
@requires_approval
def record(message):
    args = message.text.split()[1:]
    if not args:
        bot.reply_to(message,"Usage: /record <url> [duration_sec] [title]")
        return
    url = args[0]
    duration = int(args[1]) if len(args)>1 else 60
    title = " ".join(args[2:]) if len(args)>2 else "Recording"
    ts = int(time.time())
    file_out = f"rec_{message.chat.id}_{ts}.mp4"
    sent_msg = bot.reply_to(message, f"🎬 Recording '{title}' started ({duration}s).")
    threading.Thread(target=record_stream,args=(message,sent_msg.message_id,url,duration,title,file_out)).start()

def record_stream(message,msg_id,url,duration,title,outfile):
    chat_id = message.chat.id
    cmd = ["ffmpeg","-y","-i",url,"-t",str(duration),"-c","copy",outfile]
    proc = subprocess.Popen(cmd)
    if chat_id not in active_recordings: active_recordings[chat_id]={}
    active_recordings[chat_id][msg_id]={"title":title,"pid":proc.pid,"canceled":False}
    proc.wait()
    if active_recordings[chat_id][msg_id]["canceled"]:
        bot.edit_message_text(f"❌ Recording '{title}' canceled.",chat_id,msg_id)
        if os.path.exists(outfile): os.remove(outfile)
    elif os.path.exists(outfile):
        bot.edit_message_text(f"✅ Recording finished. Sending...",chat_id,msg_id)
        send_split_video(message,msg_id,outfile,title)
    del active_recordings[chat_id][msg_id]

@bot.message_handler(commands=['cancel'])
@requires_approval
def cancel_recording(message):
    if not message.reply_to_message: 
        bot.reply_to(message,"Reply to recording to cancel")
        return
    chat_id = message.chat.id
    msg_id = message.reply_to_message.message_id
    if chat_id in active_recordings and msg_id in active_recordings[chat_id]:
        pid = active_recordings[chat_id][msg_id]["pid"]
        try:
            os.system(f"kill -9 {pid}")
            active_recordings[chat_id][msg_id]["canceled"]=True
            bot.reply_to(message,"✅ Recording canceled.")
        except:
            bot.reply_to(message,"Error canceling recording")
    else:
        bot.reply_to(message,"No recording found.")

def send_split_video(message,msg_id,file_path,title):
    size_mb = os.path.getsize(file_path)/(1024*1024)
    base,ext=os.path.splitext(file_path)
    if size_mb <= SPLIT_SIZE_MB:
        bot.send_document(message.chat.id, open(file_path,"rb"),caption=title,reply_to_message_id=msg_id)
        os.remove(file_path)
        return
    parts = math.ceil(size_mb/SPLIT_SIZE_MB)
    for i in range(parts):
        part_file = f"{base}_part{i+1}{ext}"
        start = (i*size_mb)/parts
        cmd = ["ffmpeg","-y","-i",file_path,"-ss",str(i*(duration/parts)),"-t",str(duration/parts),"-c","copy",part_file]
        subprocess.run(cmd)
        bot.send_document(message.chat.id, open(part_file,"rb"),caption=f"{title} Part {i+1}/{parts}",reply_to_message_id=msg_id)
        os.remove(part_file)
    os.remove(file_path)

# ---------------- RUN BOT ----------------
while True:
    try:
        bot.polling(none_stop=True)
    except:
        time.sleep(5)
