import telebot, subprocess, threading, os, datetime, shlex, time, requests
from flask import Flask, request

# ---------------- CONFIG ----------------
BOT_TOKEN = "8472411784:AAH_Zdt_zjMsFQ4zYj6-s5R6_kzi3OeaUw4"  # Your Telegram bot token
PERMANENT_ADMIN = 6403142441
DUMP_CHANNEL_ID = -1002627919828
TEMP_DIR = "recordings"
PLAYLIST_URL = "https://21dec2027-rkdyiptv.pages.dev/global.html"

os.makedirs(TEMP_DIR, exist_ok=True)
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

approved_users = [PERMANENT_ADMIN]
recording_processes = {}
playlist_dict = {}

# ---------------- ADMIN CHECK ----------------
def admin_or_approved(func):
    def wrapper(message):
        user_id = message.from_user.id
        if user_id == PERMANENT_ADMIN or user_id in approved_users:
            return func(message)
        else:
            bot.reply_to(message, "⛔ Access denied! Wait for admin approval.")
    return wrapper

# ---------------- UTILITIES ----------------
def load_playlist():
    global playlist_dict
    try:
        r = requests.get(PLAYLIST_URL, timeout=10)
        r.raise_for_status()
        playlist_dict.clear()
        lines = r.text.splitlines()
        for i in range(len(lines)):
            if lines[i].startswith("#EXTINF:"):
                name = lines[i].split(",", 1)[1].strip()
                url = lines[i+1].strip()
                cid = str(len(playlist_dict)+1)
                playlist_dict[cid] = {"name": name, "url": url}
    except Exception as e:
        print(f"⚠️ Failed to load playlist: {e}")

def send_progress(chat_id, prefix, current, total, status):
    percent = int((current/total)*100) if total else 0
    bar_len = 20
    filled_len = int(bar_len*percent/100)
    bar = "█"*filled_len + "░"*(bar_len-filled_len)
    text = f"{prefix}\n📊 {percent}% [{bar}]\n🎯 Status: {status}"
    try:
        bot.send_message(chat_id, text)
    except:
        pass

def run_ffmpeg(url, duration, title, chat_id, split_time=None):
    timestamp = datetime.datetime.now().strftime("%H-%M-%S_%d-%m-%Y")
    files_to_upload = []

    if split_time:
        parts_pattern = os.path.join(TEMP_DIR, f"{title}_{timestamp}_part%03d.mp4")
        cmd = ["ffmpeg", "-y", "-i", url, "-c", "copy", "-f", "segment",
               "-segment_time", split_time, "-reset_timestamps", "1", parts_pattern]
    else:
        filepath = os.path.join(TEMP_DIR, f"{title}_{timestamp}.mp4")
        cmd = ["ffmpeg", "-y", "-i", url, "-c", "copy"]
        if duration:
            cmd += ["-t", duration]
        cmd.append(filepath)

    bot.send_message(chat_id, f"🎬 Recording started: `{title}`", parse_mode="Markdown")
    process = subprocess.Popen(cmd)
    recording_processes[chat_id] = process

    while process.poll() is None:
        send_progress(chat_id, f"Recording: {title}", 50, 100, "Recording...")
        time.sleep(30)

    if split_time:
        files_to_upload = sorted([f for f in os.listdir(TEMP_DIR) if f.startswith(f"{title}_{timestamp}_part")])
    else:
        files_to_upload = [f"{title}_{timestamp}.mp4"]

    for f in files_to_upload:
        path = os.path.join(TEMP_DIR, f)
        try:
            bot.send_message(chat_id, f"📤 Uploading `{f}` ...")
            with open(path, "rb") as vid:
                bot.send_video(DUMP_CHANNEL_ID, vid, caption=f"🎬 {f}")
            with open(path, "rb") as vid:
                bot.send_video(chat_id, vid, caption=f"🎬 {f}")
            os.remove(path)
            send_progress(chat_id, f"Upload: {f}", 100, 100, "Completed")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Upload failed: {e}")

    bot.send_message(chat_id, "✅ Recording & upload finished!")

# ---------------- WEBHOOK ROUTE ----------------
@app.route('/' + BOT_TOKEN, methods=['POST'])
def webhook():
    json_str = request.get_data().decode('UTF-8')
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "!", 200

# ---------------- COMMANDS ----------------
@bot.message_handler(commands=['started'])
def started(message):
    user_id = message.from_user.id
    if user_id == PERMANENT_ADMIN:
        bot.reply_to(message, "👑 Welcome Admin!\nUse /helps to see commands.")
    elif user_id in approved_users:
        bot.reply_to(message, "✅ Welcome back! Use /helps to see commands.")
    else:
        bot.send_message(PERMANENT_ADMIN, f"📩 New user request: {user_id}\nApprove with /addadmins {user_id}")
        bot.reply_to(message, "⏳ Your request has been sent to admin.")

@bot.message_handler(commands=['addadmins'])
def add_admins(message):
    user_id = message.from_user.id
    if user_id != PERMANENT_ADMIN:
        return bot.reply_to(message, "⛔ Only the permanent admin can approve users.")
    try:
        new_ids = list(map(int, message.text.split()[1:]))
        approved_list = []
        for uid in new_ids:
            if uid not in approved_users:
                approved_users.append(uid)
                approved_list.append(uid)
                bot.send_message(uid, "🎉 You are now approved to use the bot!")
        bot.reply_to(message, f"✅ Users approved: {approved_list}")
    except:
        bot.reply_to(message, "❌ Usage: /addadmins <user_id1> <user_id2> ...")

# ---------------- START BOT ----------------
print(f"🤖 IPTV Recorder Bot running with dump channel ID {DUMP_CHANNEL_ID} ...")
bot.remove_webhook()
bot.set_webhook(url=f"https://xyz-32.onrender.com/{BOT_TOKEN}")  # Replace with your Render URL

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
