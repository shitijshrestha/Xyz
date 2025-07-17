import telebot
import subprocess
import threading
import os
import time
import re
import json

BOT_TOKEN = "7994446557:AAFA2u-ZGQ32lEAES6eRrhconrFOLo_nE18"
bot = telebot.TeleBot(BOT_TOKEN)

MAX_SIZE = 2 * 1024 * 1024 * 1024  # 2GB
DATA_FILE = "access_control.json"

# Load or initialize access data
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, 'r') as f:
        access_data = json.load(f)
else:
    access_data = {"admin_id": None, "approved_users": [], "pending_requests": []}

def save_access_data():
    with open(DATA_FILE, 'w') as f:
        json.dump(access_data, f)

def is_admin(user_id):
    return access_data["admin_id"] == user_id

def is_approved(user_id):
    return user_id in access_data["approved_users"]

# ------------------- Commands -------------------

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, (
        "Welcome to the Recording Bot!\n"
        "Use /record <channel_name> <url> <HH:MM:SS> to start recording (if approved).\n"
        "Use /requestaccess to ask admin for access.\n"
        "Admin can use /approve and /reject.\n"
        "Use /help for commands."
    ))

@bot.message_handler(commands=['help'])
def help_command(message):
    bot.reply_to(message, (
        "*Commands:*\n\n"
        "/record <channel_name> <url> <HH:MM:SS> - Start recording (if approved)\n"
        "/requestaccess - Request admin to approve you\n"
        "/approve <user_id> - Admin approves a user\n"
        "/reject <user_id> - Admin rejects a user\n"
        "/addadmin - Set yourself as permanent admin (only once)"
    ), parse_mode="Markdown")

@bot.message_handler(commands=['addadmin'])
def add_admin(message):
    user_id = message.from_user.id
    if access_data["admin_id"] is None:
        access_data["admin_id"] = user_id
        save_access_data()
        bot.reply_to(message, f"You are now the permanent admin (User ID: {user_id}).")
    else:
        bot.reply_to(message, "Admin already set. Only one permanent admin allowed.")

@bot.message_handler(commands=['requestaccess'])
def request_access(message):
    user_id = message.from_user.id
    if is_admin(user_id) or is_approved(user_id):
        bot.reply_to(message, "You already have access.")
        return

    if user_id not in access_data["pending_requests"]:
        access_data["pending_requests"].append(user_id)
        save_access_data()
        bot.reply_to(message, "Your request has been sent to the admin.")

        admin_id = access_data["admin_id"]
        if admin_id:
            bot.send_message(admin_id, f"User {user_id} has requested access. Use /approve {user_id} to approve.")
    else:
        bot.reply_to(message, "Your request is already pending.")

@bot.message_handler(commands=['approve'])
def approve_user(message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        bot.reply_to(message, "Only the admin can approve users.")
        return

    args = message.text.split()
    if len(args) != 2 or not args[1].isdigit():
        bot.reply_to(message, "Usage: /approve <user_id>")
        return

    uid = int(args[1])
    if uid not in access_data["approved_users"]:
        access_data["approved_users"].append(uid)
        if uid in access_data["pending_requests"]:
            access_data["pending_requests"].remove(uid)
        save_access_data()
        bot.reply_to(message, f"User {uid} has been approved.")
        bot.send_message(uid, "You have been approved to use the bot!")
    else:
        bot.reply_to(message, "User is already approved.")

@bot.message_handler(commands=['reject'])
def reject_user(message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        bot.reply_to(message, "Only the admin can reject users.")
        return

    args = message.text.split()
    if len(args) != 2 or not args[1].isdigit():
        bot.reply_to(message, "Usage: /reject <user_id>")
        return

    uid = int(args[1])
    if uid in access_data["approved_users"]:
        access_data["approved_users"].remove(uid)
    if uid in access_data["pending_requests"]:
        access_data["pending_requests"].remove(uid)

    save_access_data()
    bot.reply_to(message, f"User {uid} has been rejected.")
    bot.send_message(uid, "Your access to the bot has been rejected.")

# ------------------- RECORD -------------------

def parse_duration(time_str):
    if not re.match(r"^\d{2}:\d{2}:\d{2}$", time_str):
        return None
    h, m, s = map(int, time_str.split(":"))
    return h * 3600 + m * 60 + s

@bot.message_handler(commands=['record'])
def record(message):
    user_id = message.from_user.id
    if not (is_admin(user_id) or is_approved(user_id)):
        bot.reply_to(message, "You do not have access to use this command.")
        return

    args = message.text.split()[1:]
    if len(args) < 3:
        bot.reply_to(message, "Usage: /record <channel_name> <url> <HH:MM:SS>\nExample: /record Channel1 http://stream 00:10:00")
        return

    channel_name = args[0]
    url = args[1]
    duration_str = args[2]
    duration_sec = parse_duration(duration_str)

    if duration_sec is None:
        bot.reply_to(message, "Duration should be in HH:MM:SS format (e.g., 00:05:00)")
        return

    filename = f"recording_{int(time.time())}.mp4"
    recording_msg = bot.reply_to(message, f"Recording started for {duration_str} on {channel_name}...")

    def record_stream():
        try:
            cmd = ['ffmpeg', '-y', '-i', url, '-t', str(duration_sec), '-c', 'copy', filename]
            subprocess.run(cmd, check=True)

            if os.path.exists(filename):
                size = os.path.getsize(filename)
                if size > 0:
                    if size <= MAX_SIZE:
                        bot.delete_message(message.chat.id, recording_msg.message_id)
                        uploading_msg = bot.send_message(message.chat.id, "Uploading...")

                        size_mb = round(size / (1024 * 1024), 2)
                        caption = f"🎬 *Recording Completed!*\n📺 Channel: *{channel_name}*\n⏱ Duration: *{duration_str}*\n💾 Size: *{size_mb} MB*"
                        send_video_with_retry(message.chat.id, filename, caption)
                        bot.delete_message(message.chat.id, uploading_msg.message_id)
                    else:
                        bot.delete_message(message.chat.id, recording_msg.message_id)
                        bot.send_message(message.chat.id, "File is larger than 2GB, cannot send on Telegram.")
                else:
                    bot.delete_message(message.chat.id, recording_msg.message_id)
                    bot.send_message(message.chat.id, "Recording failed, file is empty.")
            else:
                bot.delete_message(message.chat.id, recording_msg.message_id)
                bot.send_message(message.chat.id, "Recording failed, file not created.")
        except Exception as e:
            bot.delete_message(message.chat.id, recording_msg.message_id)
            bot.send_message(message.chat.id, f"Recording error: {str(e)}")
        finally:
            if os.path.exists(filename):
                os.remove(filename)

    threading.Thread(target=record_stream).start()

def send_video_with_retry(chat_id, filepath, caption, retries=3, delay=5):
    for attempt in range(retries):
        try:
            with open(filepath, 'rb') as file:
                bot.send_document(chat_id=chat_id, document=file, timeout=300, caption=caption, parse_mode="Markdown")
            return True
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                bot.send_message(chat_id, f"Error sending video: {str(e)}")
                return False

# ------------------- Run Bot -------------------
bot.polling()
