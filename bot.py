# bot.py — IPTV Recorder Bot with playlist, /prec, /recorded, /finds, live progress, dump channel upload
import telebot, subprocess, threading, os, datetime, shlex, time, requests

# ---------------- CONFIG ----------------
BOT_TOKEN = "7994446557:AAFdPWh2xhi3TbPUQuRGi_Z_YhxEFy78A7g"  # Replace with your bot token
PERMANENT_ADMIN = 6403142441        # Replace with your admin ID
DUMP_CHANNEL_ID = -1002627919828    # Dump channel ID
TEMP_DIR = "recordings"
PLAYLIST_URL = "https://21dec2027-rkdyiptv.pages.dev/global.html"  # Replace with actual playlist URL
os.makedirs(TEMP_DIR, exist_ok=True)
bot = telebot.TeleBot(BOT_TOKEN, num_threads=10)

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

    # Emulated progress while ffmpeg runs
    while process.poll() is None:
        send_progress(chat_id, f"Recording: {title}", 50, 100, "Recording...")
        time.sleep(30)

    # Identify recorded files
    if split_time:
        files_to_upload = sorted([f for f in os.listdir(TEMP_DIR) if f.startswith(f"{title}_{timestamp}_part")])
    else:
        files_to_upload = [f"{title}_{timestamp}.mp4"]

    # Upload to both user and dump channel
    for f in files_to_upload:
        path = os.path.join(TEMP_DIR, f)
        try:
            bot.send_message(chat_id, f"📤 Uploading `{f}` ...")
            with open(path, "rb") as vid:
                # Upload to dump channel
                bot.send_video(DUMP_CHANNEL_ID, vid, caption=f"🎬 {f}")
            with open(path, "rb") as vid:
                # Upload to user
                bot.send_video(chat_id, vid, caption=f"🎬 {f}")
            os.remove(path)
            send_progress(chat_id, f"Upload: {f}", 100, 100, "Completed")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Upload failed: {e}")

    bot.send_message(chat_id, "✅ Recording & upload finished!")

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

@bot.message_handler(commands=['helps'])
@admin_or_approved
def helps(message):
    text = f"""📘 **Bot Commands Guide**

🎬 **Recording**
/recorded <url> [duration] <title> [--split <time>] — Direct URL recording
/prec <channel_id> [duration] <title> [--split <time>] — Playlist recording from URL
/finds <name_or_id> — Search channel in playlist

📁 **Files**
/files — List recordings
/uploads <filename> — Upload file
/deleted <filename> — Delete file

⚙️ **Other**
/cancels — Cancel recording
/statuss — Show status
/addadmins <user_id> ... — Approve multiple users
/started — Welcome message
/helps — This guide

💾 All recordings automatically uploaded to dump channel: {DUMP_CHANNEL_ID}
"""
    bot.reply_to(message, text, parse_mode="Markdown")

# ---------------- /recorded ----------------
@bot.message_handler(commands=['recorded'])
@admin_or_approved
def recorded(message):
    try:
        args = shlex.split(message.text)
        if len(args) < 4:
            return bot.reply_to(message, "❌ Usage: /recorded <url> [duration] <title> [--split <time>]")
        url = args[1]
        duration = args[2] if ":" in args[2] else None
        title = args[3] if duration else args[2]
        split_time = None
        if "--split" in message.text:
            split_time = message.text.split("--split")[1].strip()
        threading.Thread(target=run_ffmpeg, args=(url, duration, title, message.chat.id, split_time)).start()
    except Exception as e:
        bot.reply_to(message, f"⚠️ Error: {e}")

# ---------------- /prec ----------------
@bot.message_handler(commands=['prec'])
@admin_or_approved
def prec(message):
    load_playlist()
    try:
        args = shlex.split(message.text)
        if len(args) < 3:
            return bot.reply_to(message, "❌ Usage: /prec <channel_id> [duration] <title> [--split <time>]")
        channel_id = args[1]
        channel = playlist_dict.get(channel_id)
        if not channel:
            return bot.reply_to(message, "⚠️ Invalid channel ID.")
        url = channel["url"]
        duration = args[2] if ":" in args[2] else None
        title = args[3] if duration else args[2]
        split_time = None
        if "--split" in message.text:
            split_time = message.text.split("--split")[1].strip()
        threading.Thread(target=run_ffmpeg, args=(url, duration, title, message.chat.id, split_time)).start()
    except Exception as e:
        bot.reply_to(message, f"⚠️ Error: {e}")

# ---------------- /finds ----------------
@bot.message_handler(commands=['finds'])
@admin_or_approved
def finds(message):
    load_playlist()
    try:
        query = message.text.split(maxsplit=1)[1].lower()
        result = []
        for cid, ch in playlist_dict.items():
            if query in ch["name"].lower() or query == cid:
                result.append(f"{cid} — {ch['name']}")
        if result:
            bot.reply_to(message, "\n".join(result))
        else:
            bot.reply_to(message, "⚠️ No matching channels found.")
    except:
        bot.reply_to(message, "❌ Usage: /finds <channel_name_or_id>")

# ---------------- /cancels /statuss ----------------
@bot.message_handler(commands=['cancels'])
@admin_or_approved
def cancels(message):
    chat_id = message.chat.id
    process = recording_processes.get(chat_id)
    if process and process.poll() is None:
        process.terminate()
        bot.reply_to(message, "⏹ Recording canceled.")
    else:
        bot.reply_to(message, "⚠️ No active recording found.")

@bot.message_handler(commands=['statuss'])
@admin_or_approved
def statuss(message):
    chat_id = message.chat.id
    process = recording_processes.get(chat_id)
    if process and process.poll() is None:
        bot.reply_to(message, "🎥 Recording is active.")
    else:
        bot.reply_to(message, "⏹ No active recording.")

# ---------------- /files /deleted /uploads ----------------
@bot.message_handler(commands=['files'])
@admin_or_approved
def list_files(message):
    files = os.listdir(TEMP_DIR)
    if not files:
        bot.reply_to(message, "📂 No recordings found.")
    else:
        bot.reply_to(message, "\n".join(files))

@bot.message_handler(commands=['deleted'])
@admin_or_approved
def delete_file(message):
    try:
        filename = message.text.split()[1]
        path = os.path.join(TEMP_DIR, filename)
        if os.path.exists(path):
            os.remove(path)
            bot.reply_to(message, f"🗑 Deleted `{filename}`")
        else:
            bot.reply_to(message, "⚠️ File not found.")
    except:
        bot.reply_to(message, "❌ Usage: /deleted <filename>")

@bot.message_handler(commands=['uploads'])
@admin_or_approved
def uploads(message):
    try:
        filename = message.text.split()[1]
        path = os.path.join(TEMP_DIR, filename)
        if os.path.exists(path):
            bot.send_message(message.chat.id, f"📤 Uploading `{filename}` ...")
            with open(path, "rb") as vid:
                # Upload to dump channel
                bot.send_video(DUMP_CHANNEL_ID, vid, caption=f"🎬 {filename}")
            with open(path, "rb") as vid:
                # Upload to user
                bot.send_video(message.chat.id, vid, caption=f"🎬 {filename}")
            os.remove(path)
        else:
            bot.reply_to(message, "⚠️ File not found.")
    except:
        bot.reply_to(message, "❌ Usage: /uploads <filename>")

# ---------------- RUN BOT ----------------
print(f"🤖 IPTV Recorder Bot running with dump channel ID {DUMP_CHANNEL_ID} ...")
bot.infinity_polling()
