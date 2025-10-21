import telebot
import subprocess
import threading
import os
from functools import wraps
from telebot.apihelper import ApiTelegramException

# ---------------- CONFIG ----------------
BOT_TOKEN = "7994446557:AAHoC-lsN137MmZfVMHiTWHRXRBHCFlwCKA"
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="Markdown")

# Admins & Approved Users
PERMANENT_ADMIN = 6403142441  # Replace with your Telegram ID
ADMINS = {PERMANENT_ADMIN}
APPROVED_USERS = set()

# ---------------- DECORATORS ----------------
def admin_only(func):
    @wraps(func)
    def wrapper(message, *args, **kwargs):
        user_id = message.from_user.id
        if user_id not in ADMINS:
            bot.reply_to(message, "❌ You are not an admin.")
            return
        return func(message, *args, **kwargs)
    return wrapper

def approved_only(func):
    @wraps(func)
    def wrapper(message, *args, **kwargs):
        user_id = message.from_user.id
        if user_id not in APPROVED_USERS and user_id not in ADMINS:
            bot.reply_to(message, "⚠️ You are not approved. Use /request to ask for access.")
            return
        return func(message, *args, **kwargs)
    return wrapper

# ---------------- COMMANDS ----------------
@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "👋 Welcome! Use /help to see available commands.")

@bot.message_handler(commands=['help'])
def help_command(message):
    help_text = """
📌 Commands:

/record <url> <duration (hh:mm:ss)> <title> - Record a video and send directly to you
/request - Request access to use bot
/help - Show this message
"""
    bot.reply_to(message, help_text)

# ---------------- ACCESS REQUEST ----------------
@bot.message_handler(commands=['request'])
def request_access(message):
    user_id = message.from_user.id
    if user_id in APPROVED_USERS or user_id in ADMINS:
        bot.reply_to(message, "✅ You already have access.")
        return
    bot.reply_to(message, "✅ Your request has been sent to admins.")
    for admin_id in ADMINS:
        try:
            bot.send_message(admin_id, f"User {message.from_user.first_name} ({user_id}) requested access.\nUse /approve {user_id} to approve.")
        except:
            pass

@bot.message_handler(commands=['approve'])
@admin_only
def approve_user(message):
    args = message.text.split()
    if len(args) != 2:
        bot.reply_to(message, "Usage: /approve <user_id>")
        return
    try:
        user_id = int(args[1])
        APPROVED_USERS.add(user_id)
        bot.reply_to(message, f"✅ User {user_id} approved.")
        bot.send_message(user_id, "✅ You have been approved to use the bot.")
    except:
        bot.reply_to(message, "❌ Invalid user ID.")

@bot.message_handler(commands=['addadmin'])
@admin_only
def add_admin(message):
    args = message.text.split()
    if len(args) != 2:
        bot.reply_to(message, "Usage: /addadmin <user_id>")
        return
    try:
        user_id = int(args[1])
        ADMINS.add(user_id)
        bot.reply_to(message, f"✅ User {user_id} added as admin.")
        bot.send_message(user_id, "✅ You are now an admin.")
    except:
        bot.reply_to(message, "❌ Invalid user ID.")

# ---------------- RECORDING ----------------
@bot.message_handler(commands=['record'])
@approved_only
def record(message):
    args = message.text.split()
    if len(args) < 4:
        bot.reply_to(message, "Usage: /record <url> <duration (hh:mm:ss)> <title>")
        return

    url = args[1]
    duration = args[2]
    title = " ".join(args[3:])
    file_name = f"{title.replace(' ','_')}.mp4"

    bot.reply_to(message, f"🎬 Recording started!\n🎥 Title: {title}\n🔗 URL: {url}\n⏱ Duration: {duration}")

    def run_record():
        cmd = f"ffmpeg -y -i \"{url}\" -t {duration} -c copy \"{file_name}\""
        process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        process.communicate()

        if os.path.exists(file_name):
            # Upload directly to user
            try:
                with open(file_name, "rb") as video:
                    bot.send_video(message.chat.id, video, caption=f"🎬 {title}")
                bot.send_message(message.chat.id, "✅ Recording finished and sent to you.")
            except ApiTelegramException as e:
                bot.reply_to(message, f"❌ Upload failed: {e}")
            finally:
                os.remove(file_name)
        else:
            bot.reply_to(message, "❌ Recording failed.")

    threading.Thread(target=run_record).start()

# ---------------- RUN BOT ----------------
print("🤖 Bot is running...")
bot.infinity_polling()
