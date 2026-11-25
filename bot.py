import telebot
import subprocess
import threading
import os
import time
import re
import json
import imageio_ffmpeg

# BOT TOKEN
BOT_TOKEN = "9231852175:AAEmC4uuHjhxiSts_gyBUgsSoQWBHEr4e4c"
bot = telebot.TeleBot(BOT_TOKEN)

# FFmpeg bundled executable
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

MAX_SIZE = 2 * 1024 * 1024 * 1024
DATA_FILE = "access_control.json"

# ------------------- ACCESS DATA -------------------

if os.path.exists(DATA_FILE):
    with open(DATA_FILE, 'r') as f:
        access_data = json.load(f)
else:
    access_data = {
        "admin_id": None,
        "approved_users": [],
        "pending_requests": []
    }


def save_access_data():
    with open(DATA_FILE, 'w') as f:
        json.dump(access_data, f)


def is_admin(user_id):
    return access_data["admin_id"] == user_id


def is_approved(user_id):
    return user_id in access_data["approved_users"]


# ------------------- COMMANDS -------------------

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
        bot.reply_to(
            message,
            f"You are now the permanent admin (User ID: {user_id})."
        )
    else:
        bot.reply_to(
            message,
            "Admin already set. Only one permanent admin allowed."
        )


@bot.message_handler(commands=['requestaccess'])
def request_access(message):
    user_id = message.from_user.id

    if is_admin(user_id) or is_approved(user_id):
        bot.reply_to(message, "You already have access.")
        return

    if user_id not in access_data["pending_requests"]:
        access_data["pending_requests"].append(user_id)
        save_access_data()

        bot.reply_to(
            message,
            "Your request has been sent to the admin."
        )

        admin_id = access_data["admin_id"]

        if admin_id:
            bot.send_message(
                admin_id,
                f"User {user_id} has requested access. "
                f"Use /approve {user_id} to approve."
            )
    else:
        bot.reply_to(
            message,
            "Your request is already pending."
        )


@bot.message_handler(commands=['approve'])
def approve_user(message):
    user_id = message.from_user.id

    if not is_admin(user_id):
        bot.reply_to(
            message,
            "Only the admin can approve users."
        )
        return

    args = message.text.split()

    if len(args) != 2 or not args[1].isdigit():
        bot.reply_to(
            message,
            "Usage: /approve <user_id>"
        )
        return

    uid = int(args[1])

    if uid not in access_data["approved_users"]:
        access_data["approved_users"].append(uid)

        if uid in access_data["pending_requests"]:
            access_data["pending_requests"].remove(uid)

        save_access_data()

        bot.reply_to(
            message,
            f"User {uid} has been approved."
        )

        try:
            bot.send_message(
                uid,
                "You have been approved to use the bot!"
            )
        except Exception:
            pass
    else:
        bot.reply_to(
            message,
            "User is already approved."
        )


@bot.message_handler(commands=['reject'])
def reject_user(message):
    user_id = message.from_user.id

    if not is_admin(user_id):
        bot.reply_to(
            message,
            "Only the admin can reject users."
        )
        return

    args = message.text.split()

    if len(args) != 2 or not args[1].isdigit():
        bot.reply_to(
            message,
            "Usage: /reject <user_id>"
        )
        return

    uid = int(args[1])

    if uid in access_data["approved_users"]:
        access_data["approved_users"].remove(uid)

    if uid in access_data["pending_requests"]:
        access_data["pending_requests"].remove(uid)

    save_access_data()

    bot.reply_to(
        message,
        f"User {uid} has been rejected."
    )

    try:
        bot.send_message(
            uid,
            "Your access to the bot has been rejected."
        )
    except Exception:
        pass


# ------------------- DURATION -------------------

def parse_duration(time_str):
    if not re.match(r"^\d{2}:\d{2}:\d{2}$", time_str):
        return None

    h, m, s = map(int, time_str.split(":"))

    if m >= 60 or s >= 60:
        return None

    return h * 3600 + m * 60 + s


# ------------------- RECORDING -------------------

@bot.message_handler(commands=['record'])
def record(message):
    user_id = message.from_user.id

    if not (is_admin(user_id) or is_approved(user_id)):
        bot.reply_to(
            message,
            "You do not have access to use this command."
        )
        return

    args = message.text.split()[1:]

    if len(args) < 3:
        bot.reply_to(
            message,
            "Usage: /record <channel_name> <url> <HH:MM:SS>\n"
            "Example: /record Channel1 http://stream 00:10:00"
        )
        return

    channel_name = args[0]
    url = args[1]
    duration_str = args[2]

    duration_sec = parse_duration(duration_str)

    if duration_sec is None or duration_sec <= 0:
        bot.reply_to(
            message,
            "Duration should be in HH:MM:SS format "
            "(e.g. 00:05:00)"
        )
        return

    filename = (
        f"recording_{int(time.time())}_"
        f"{message.message_id}.mp4"
    )

    recording_msg = bot.reply_to(
        message,
        f"Recording started for {duration_str} on {channel_name}..."
    )

    def record_stream():
        try:
            cmd = [
                FFMPEG,
                '-y',
                '-hide_banner',
                '-loglevel', 'error',

                # HLS/network reconnect options
                '-reconnect', '1',
                '-reconnect_streamed', '1',
                '-reconnect_delay_max', '5',
                '-rw_timeout', '15000000',

                '-i', url,
                '-t', str(duration_sec),

                # Copy original stream without re-encoding
                '-c', 'copy',
                '-movflags', '+faststart',
                filename
            ]

            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=duration_sec + 120
            )

            if result.returncode != 0:
                error = result.stderr[-2500:]

                raise RuntimeError(
                    f"FFmpeg failed:\n{error}"
                )

            if not os.path.exists(filename):
                raise RuntimeError(
                    "Recording file was not created."
                )

            size = os.path.getsize(filename)

            if size <= 0:
                raise RuntimeError(
                    "Recording file is empty."
                )

            if size > MAX_SIZE:
                bot.send_message(
                    message.chat.id,
                    "File is larger than 2GB, "
                    "cannot send on Telegram."
                )
                return

            bot.delete_message(
                message.chat.id,
                recording_msg.message_id
            )

            uploading_msg = bot.send_message(
                message.chat.id,
                "Uploading..."
            )

            size_mb = round(
                size / (1024 * 1024), 2
            )

            caption = (
                f"🎬 *Recording Completed!*\n"
                f"📺 Channel: *{channel_name}*\n"
                f"⏱ Duration: *{duration_str}*\n"
                f"💾 Size: *{size_mb} MB*"
            )

            send_video_with_retry(
                message.chat.id,
                filename,
                caption
            )

            try:
                bot.delete_message(
                    message.chat.id,
                    uploading_msg.message_id
                )
            except Exception:
                pass

        except Exception as e:
            try:
                bot.delete_message(
                    message.chat.id,
                    recording_msg.message_id
                )
            except Exception:
                pass

            try:
                bot.send_message(
                    message.chat.id,
                    f"Recording error: {str(e)[:3000]}"
                )
            except Exception:
                pass

        finally:
            if os.path.exists(filename):
                try:
                    os.remove(filename)
                except Exception:
                    pass

    threading.Thread(
        target=record_stream,
        daemon=True
    ).start()


# ------------------- UPLOAD WITH RETRY -------------------

def send_video_with_retry(
    chat_id,
    filepath,
    caption,
    retries=3,
    delay=5
):
    for attempt in range(retries):
        try:
            with open(filepath, 'rb') as file:
                bot.send_document(
                    chat_id=chat_id,
                    document=file,
                    timeout=300,
                    caption=caption,
                    parse_mode="Markdown"
                )

            return True

        except Exception as e:
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                bot.send_message(
                    chat_id,
                    f"Error sending video: {str(e)}"
                )
                return False


# ------------------- RUN BOT -------------------

print("Recording Bot Started Successfully!")
print("FFmpeg:", FFMPEG)

bot.infinity_polling(
    timeout=30,
    long_polling_timeout=30
        )
        
