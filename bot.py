import telebot
import subprocess
import threading
import os
import time
import re
import json
from math import ceil

# ---------------- CONFIG ----------------
BOT_TOKEN = "7994446557:AAHoC-lsN137MmZfVMHiTWHRXRBHCFlwCKA"
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="Markdown")

MAX_TELEGRAM_SIZE = 50 * 1024 * 1024  # 50MB per part
DATA_FILE = "access_control.json"
UPLOAD_FOLDER = "downloads"
RCLONE_REMOTE = "gdrive"  # change if your remote name is different

# ---------------- ACCESS CONTROL ----------------
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r") as f:
        access_data = json.load(f)
else:
    access_data = {"admin_id": None, "approved_users": [], "pending_requests": []}

def save_access_data():
    with open(DATA_FILE, "w") as f:
        json.dump(access_data, f)

def is_admin(user_id):
    return access_data["admin_id"] == user_id

def is_approved(user_id):
    return user_id in access_data["approved_users"]

# ---------------- RECORDING TRACKER ----------------
running_recordings = {}  # user_id: subprocess.Popen object

# ---------------- COMMANDS ----------------
@bot.message_handler(commands=["start"])
def start(message):
    bot.reply_to(message, (
        "👋 *Welcome to the M3U8 Recorder Bot!*\n\n"
        "🎥 `/record <channel_name> <url> <HH:MM:SS>` - Start recording\n"
        "🛑 `/stop` - Stop your recording\n"
        "☁️ Auto upload to Google Drive + public link\n"
        "📤 Uploads to Telegram split in 50MB chunks\n"
        "👮 Admin Commands:\n"
        "`/addadmin`, `/approve <user_id>`, `/reject <user_id>`\n"
        "📩 Normal users use `/requestaccess` to get approval"
    ))

@bot.message_handler(commands=["addadmin"])
def add_admin(message):
    user_id = message.from_user.id
    if access_data["admin_id"] is None:
        access_data["admin_id"] = user_id
        save_access_data()
        bot.reply_to(message, f"✅ You are now the permanent admin (User ID: `{user_id}`)")
    else:
        bot.reply_to(message, "❌ Admin already set.")

@bot.message_handler(commands=["requestaccess"])
def request_access(message):
    user_id = message.from_user.id
    if user_id == access_data["admin_id"]:
        bot.reply_to(message, "👑 You are already the admin.")
        return
    if user_id in access_data["approved_users"]:
        bot.reply_to(message, "✅ You already have access.")
        return
    if user_id in access_data["pending_requests"]:
        bot.reply_to(message, "⏳ Your request is already pending.")
        return

    access_data["pending_requests"].append(user_id)
    save_access_data()
    bot.reply_to(message, "📝 Access request sent to admin for approval.")
    if access_data["admin_id"]:
        bot.send_message(
            access_data["admin_id"],
            f"📥 *New access request*\nUser: `{message.from_user.first_name}`\nID: `{user_id}`\n\nApprove using `/approve {user_id}` or reject using `/reject {user_id}`."
        )

@bot.message_handler(commands=["approve"])
def approve_user(message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        bot.reply_to(message, "🚫 Only admin can approve users.")
        return
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /approve <user_id>")
        return
    target_id = int(args[1])
    if target_id in access_data["approved_users"]:
        bot.reply_to(message, "✅ User already approved.")
        return
    access_data["approved_users"].append(target_id)
    if target_id in access_data["pending_requests"]:
        access_data["pending_requests"].remove(target_id)
    save_access_data()
    bot.reply_to(message, f"✅ Approved user `{target_id}`.")
    bot.send_message(target_id, "🎉 Your access has been approved! Use `/record` to start recording.")

@bot.message_handler(commands=["reject"])
def reject_user(message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        bot.reply_to(message, "🚫 Only admin can reject users.")
        return
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /reject <user_id>")
        return
    target_id = int(args[1])
    if target_id in access_data["pending_requests"]:
        access_data["pending_requests"].remove(target_id)
        save_access_data()
        bot.reply_to(message, f"❌ Rejected user `{target_id}`.")
        bot.send_message(target_id, "🚫 Your access request has been rejected.")
    else:
        bot.reply_to(message, "⚠️ No pending request for that user.")

# ---------------- RECORDING FUNCTION ----------------
def parse_duration(time_str):
    if not re.match(r"^\d{2}:\d{2}:\d{2}$", time_str):
        return None
    h, m, s = map(int, time_str.split(":"))
    return h * 3600 + m * 60 + s

def split_file(filepath):
    """Split file into 50MB chunks for Telegram."""
    file_size = os.path.getsize(filepath)
    if file_size <= MAX_TELEGRAM_SIZE:
        return [filepath]

    parts = []
    total_parts = ceil(file_size / MAX_TELEGRAM_SIZE)
    with open(filepath, "rb") as f:
        for i in range(total_parts):
            part_filename = f"{filepath}.part{i+1}"
            with open(part_filename, "wb") as pf:
                pf.write(f.read(MAX_TELEGRAM_SIZE))
            parts.append(part_filename)
    return parts

def upload_to_telegram(filepath, chat_id):
    try:
        parts = split_file(filepath)
        for i, part in enumerate(parts, 1):
            bot.send_message(chat_id, f"📤 Uploading part {i}/{len(parts)}...")
            with open(part, "rb") as f:
                bot.send_document(chat_id, f)
            os.remove(part)
        bot.send_message(chat_id, "✅ Upload completed successfully!")
    except Exception as e:
        bot.send_message(chat_id, f"❌ Telegram upload failed: {e}")

@bot.message_handler(commands=["record"])
def record(message):
    user_id = message.from_user.id
    if not (is_admin(user_id) or is_approved(user_id)):
        bot.reply_to(message, "🚫 Access denied. Please request access using `/requestaccess`.")
        return
    args = message.text.split(maxsplit=3)
    if len(args) < 4:
        bot.reply_to(message, "Usage: /record [channel_name] [url] [HH:MM:SS]", parse_mode=None)
        return

    channel_name, url, duration_str = args[1], args[2], args[3]
    duration_sec = parse_duration(duration_str)
    if duration_sec is None:
        bot.reply_to(message, "⏱ Invalid duration format. Use HH:MM:SS.")
        return

    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)

    filename = f"{channel_name}_{int(time.time())}.mp4"
    filepath = os.path.join(UPLOAD_FOLDER, filename)

    bot.reply_to(message, f"🎬 Recording *{channel_name}* for `{duration_str}`...", parse_mode="Markdown")

    def record_task():
        try:
            cmd = [
                "ffmpeg", "-y", "-i", url, "-t", str(duration_sec),
                "-c", "copy", "-bsf:a", "aac_adtstoasc", filepath
            ]
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            running_recordings[user_id] = process
            process.wait()
            running_recordings.pop(user_id, None)

            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                bot.send_message(message.chat.id, "📦 Recording completed. Uploading to Telegram...")
                upload_to_telegram(filepath, message.chat.id)
                bot.send_message(message.chat.id, "☁️ Uploading to Google Drive...")
                upload_to_gdrive(filepath, message)
            else:
                bot.send_message(message.chat.id, "❌ Recording failed (empty file).")
        except Exception as e:
            bot.send_message(message.chat.id, f"⚠️ Error: {e}")
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)

    threading.Thread(target=record_task).start()

# ---------------- STOP RECORDING ----------------
@bot.message_handler(commands=["stop"])
def stop_recording(message):
    user_id = message.from_user.id
    process = running_recordings.get(user_id)
    if process:
        process.terminate()
        running_recordings.pop(user_id, None)
        bot.reply_to(message, "🛑 Recording stopped.")
    else:
        bot.reply_to(message, "⚠️ No active recording found.")

# ---------------- UPLOAD TO GDRIVE ----------------
def upload_to_gdrive(filepath, message):
    try:
        filename = os.path.basename(filepath)
        cmd = ["rclone", "copy", filepath, f"{RCLONE_REMOTE}:/M3U8_Record"]
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        process.wait()
        if process.returncode == 0:
            cmd_link = ["rclone", "link", f"{RCLONE_REMOTE}:/M3U8_Record/{filename}"]
            link = subprocess.check_output(cmd_link).decode().strip()
            bot.send_message(message.chat.id, f"✅ Google Drive Upload Successful!\n🔗 *Public Link:* {link}")
            # Auto-delete from GDrive after 6 hours
            threading.Timer(21600, lambda: subprocess.run(["rclone", "deletefile", f"{RCLONE_REMOTE}:/M3U8_Record/{filename}"])).start()
        else:
            bot.send_message(message.chat.id, "❌ Google Drive upload failed (rclone error).")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Google Drive upload failed: {e}")

# ---------------- RUN BOT ----------------
def run_forever():
    while True:
        try:
            bot.polling(none_stop=True, interval=1, timeout=20)
        except Exception as e:
            print(f"Bot polling crashed: {e}")
            time.sleep(5)

if __name__ == "__main__":
    print("🤖 M3U8 Recorder Bot running with Telegram split upload + Google Drive + /stop + auto-delete after 6 hours...")
    run_forever()
