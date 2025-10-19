import telebot
import subprocess
import threading
import os
import time
import re

# ---------------- CONFIG ----------------
BOT_TOKEN = "7994446557:AAHoC-lsN137MmZfVMHiTWHRXRBHCFlwCKA"
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="Markdown")

# Folder paths
RCLONE_CONF = "rclone.conf"
MAX_SIZE = 2 * 1024 * 1024 * 1024  # 2GB limit

# ---------------- INSTALL SETUP ----------------
def setup_environment():
    print("🔧 Checking dependencies...")
    try:
        subprocess.run(["which", "rclone"], check=True, stdout=subprocess.DEVNULL)
        print("✅ rclone already installed")
    except:
        print("⬇️ Installing rclone...")
        subprocess.run("sudo apt update -y && sudo apt install rclone -y", shell=True)
    
    try:
        subprocess.run(["which", "ffmpeg"], check=True, stdout=subprocess.DEVNULL)
        print("✅ ffmpeg already installed")
    except:
        print("⬇️ Installing ffmpeg...")
        subprocess.run("sudo apt install ffmpeg -y", shell=True)
    
    os.makedirs(os.path.expanduser("~/.config/rclone"), exist_ok=True)
    if os.path.exists(RCLONE_CONF):
        target = os.path.expanduser("~/.config/rclone/rclone.conf")
        subprocess.run(f"cp {RCLONE_CONF} {target}", shell=True)
        print("✅ rclone.conf configured")

# ---------------- UPLOAD FUNCTION ----------------
def upload_to_gdrive(file_path, chat_id):
    try:
        bot.send_message(chat_id, f"⏳ Uploading `{os.path.basename(file_path)}` to Google Drive...")
        result = subprocess.run(["rclone", "copy", file_path, "gdrive:/", "--progress"], capture_output=True, text=True)
        
        if result.returncode == 0:
            file_name = os.path.basename(file_path)
            # Generate sharable link
            link = subprocess.run(["rclone", "link", f"gdrive:/{file_name}"], capture_output=True, text=True).stdout.strip()
            if not link.startswith("http"):
                link = "❌ Failed to get share link"
            bot.send_message(chat_id, f"✅ Uploaded successfully:\n🎬 *{file_name}*\n🔗 [Open in Google Drive]({link})", disable_web_page_preview=True)
            os.remove(file_path)
        else:
            bot.send_message(chat_id, f"❌ Upload failed:\n```\n{result.stderr}\n```")
    except Exception as e:
        bot.send_message(chat_id, f"⚠️ Upload error: {e}")

# ---------------- COMMANDS ----------------
@bot.message_handler(commands=['start'])
def start_cmd(message):
    bot.reply_to(message, "👋 *Welcome!*\n\nSend me a video/document and I’ll upload it to your Google Drive.\n\n✅ Max size: 2GB")

@bot.message_handler(content_types=['video', 'document'])
def handle_file(message):
    file_info = bot.get_file(message.video.file_id if message.content_type == 'video' else message.document.file_id)
    file_name = message.video.file_name if message.content_type == 'video' else message.document.file_name
    downloaded = bot.download_file(file_info.file_path)
    with open(file_name, "wb") as f:
        f.write(downloaded)
    
    bot.reply_to(message, f"📦 File received: `{file_name}`")
    threading.Thread(target=upload_to_gdrive, args=(file_name, message.chat.id)).start()

# ---------------- MAIN ----------------
if __name__ == "__main__":
    setup_environment()
    print("🤖 Bot is running...")
    bot.infinity_polling(skip_pending=True)
