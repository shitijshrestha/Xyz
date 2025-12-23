import os
import telebot
import subprocess
import threading
import datetime
import shlex
import time
import requests
from flask import Flask, request

# ================= CONFIG =================
BOT_TOKEN = "8472411784:AAH--Dd1I45vwZcwLCi2iqav77vz8JfqpmI"
PERMANENT_ADMIN = 6403142441
DUMP_CHANNEL_ID = -1002627919828
PLAYLIST_URL = "https://21dec2027-rkdyiptv.pages.dev/global.html"
TEMP_DIR = "recordings"
RENDER_URL = "https://xyz-36.onrender.com"   # 🔴 CHANGE IF URL CHANGES
# =========================================

os.makedirs(TEMP_DIR, exist_ok=True)

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
app = Flask(__name__)

approved_users = [PERMANENT_ADMIN]
recording_processes = {}
playlist_dict = {}

# ================= WEB SERVER =================
@app.route("/", methods=["GET"])
def home():
    return "IPTV Recorder Bot Running", 200

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    update = telebot.types.Update.de_json(
        request.stream.read().decode("utf-8")
    )
    bot.process_new_updates([update])
    return "OK", 200

# ================= ADMIN CHECK =================
def admin_or_approved(func):
    def wrapper(message):
        uid = message.from_user.id
        if uid == PERMANENT_ADMIN or uid in approved_users:
            return func(message)
        bot.reply_to(message, "⛔ Access denied! Wait for admin approval.")
    return wrapper

# ================= PLAYLIST =================
def load_playlist():
    playlist_dict.clear()
    r = requests.get(PLAYLIST_URL, timeout=10)
    lines = r.text.splitlines()
    for i in range(len(lines)):
        if lines[i].startswith("#EXTINF"):
            name = lines[i].split(",", 1)[1]
            url = lines[i+1]
            cid = str(len(playlist_dict)+1)
            playlist_dict[cid] = {"name": name, "url": url}

# ================= PROGRESS =================
def send_progress(chat_id, text):
    try:
        bot.send_message(chat_id, text)
    except:
        pass

# ================= FFMPEG =================
def run_ffmpeg(url, duration, title, chat_id):
    ts = datetime.datetime.now().strftime("%d-%m-%Y_%H-%M-%S")
    path = f"{TEMP_DIR}/{title}_{ts}.mp4"

    cmd = ["ffmpeg", "-y", "-i", url, "-c", "copy"]
    if duration:
        cmd += ["-t", duration]
    cmd.append(path)

    bot.send_message(chat_id, f"🎬 Recording started: {title}")
    p = subprocess.Popen(cmd)
    recording_processes[chat_id] = p

    while p.poll() is None:
        send_progress(chat_id, "⏳ Recording...")
        time.sleep(30)

    try:
        with open(path, "rb") as v:
            bot.send_video(DUMP_CHANNEL_ID, v, caption=title)
        with open(path, "rb") as v:
            bot.send_video(chat_id, v, caption=title)
        os.remove(path)
        bot.send_message(chat_id, "✅ Upload completed")
    except Exception as e:
        bot.send_message(chat_id, f"❌ Upload failed: {e}")

# ================= COMMANDS =================
@bot.message_handler(commands=["start"])
def start(message):
    uid = message.from_user.id
    if uid == PERMANENT_ADMIN:
        bot.reply_to(message, "👑 Admin online")
    elif uid in approved_users:
        bot.reply_to(message, "✅ Welcome back")
    else:
        bot.send_message(PERMANENT_ADMIN, f"New user: {uid}\nApprove: /addadmins {uid}")
        bot.reply_to(message, "⏳ Approval sent")

@bot.message_handler(commands=["addadmins"])
def add_admins(message):
    if message.from_user.id != PERMANENT_ADMIN:
        return
    ids = message.text.split()[1:]
    for i in ids:
        i = int(i)
        if i not in approved_users:
            approved_users.append(i)
            bot.send_message(i, "✅ You are approved")
    bot.reply_to(message, "Done")

@bot.message_handler(commands=["helps"])
@admin_or_approved
def helps(message):
    bot.reply_to(message,
"""📘 Commands
/recorded <url> <duration> <title>
/prec <channel_id> <duration> <title>
/finds <name>
/files
/uploads <file>
/deleted <file>
/cancels
/statuss
""")

@bot.message_handler(commands=["recorded"])
@admin_or_approved
def recorded(message):
    args = shlex.split(message.text)
    url = args[1]
    duration = args[2]
    title = args[3]
    threading.Thread(target=run_ffmpeg, args=(url,duration,title,message.chat.id)).start()

@bot.message_handler(commands=["prec"])
@admin_or_approved
def prec(message):
    load_playlist()
    args = shlex.split(message.text)
    cid = args[1]
    duration = args[2]
    title = args[3]
    ch = playlist_dict.get(cid)
    if not ch:
        return bot.reply_to(message, "Invalid channel ID")
    threading.Thread(target=run_ffmpeg, args=(ch["url"],duration,title,message.chat.id)).start()

@bot.message_handler(commands=["finds"])
@admin_or_approved
def finds(message):
    load_playlist()
    q = message.text.split(maxsplit=1)[1].lower()
    res = []
    for k,v in playlist_dict.items():
        if q in v["name"].lower():
            res.append(f"{k} - {v['name']}")
    bot.reply_to(message, "\n".join(res) if res else "No result")

@bot.message_handler(commands=["files"])
@admin_or_approved
def files(message):
    bot.reply_to(message, "\n".join(os.listdir(TEMP_DIR)) or "Empty")

@bot.message_handler(commands=["deleted"])
@admin_or_approved
def deleted(message):
    f = message.text.split()[1]
    p = f"{TEMP_DIR}/{f}"
    if os.path.exists(p):
        os.remove(p)
        bot.reply_to(message, "Deleted")

@bot.message_handler(commands=["uploads"])
@admin_or_approved
def uploads(message):
    f = message.text.split()[1]
    p = f"{TEMP_DIR}/{f}"
    with open(p,"rb") as v:
        bot.send_video(message.chat.id, v)
    os.remove(p)

@bot.message_handler(commands=["cancels"])
@admin_or_approved
def cancels(message):
    p = recording_processes.get(message.chat.id)
    if p:
        p.terminate()
        bot.reply_to(message, "Canceled")

@bot.message_handler(commands=["statuss"])
@admin_or_approved
def statuss(message):
    p = recording_processes.get(message.chat.id)
    bot.reply_to(message, "Recording running" if p and p.poll() is None else "Idle")

# ================= WEBHOOK SET =================
bot.remove_webhook()
bot.set_webhook(url=f"{RENDER_URL}/{BOT_TOKEN}")

# ================= RUN =================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
