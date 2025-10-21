#!/usr/bin/env python3
# bot.py - IPTV Recorder Bot (final)
# Requirements: pip install pyTelegramBotAPI
# Ensure ffmpeg is installed & available in PATH (or provide a local ffmpeg binary)

import telebot
import subprocess
import threading
import os
import time
import math
import io
from functools import wraps
from telebot.apihelper import ApiTelegramException

# ---------------- CONFIG ----------------
BOT_TOKEN = "7994446557:AAFa6TdlfByY76o22j9D6nhtq-Lmg2U13uc"
bot = telebot.TeleBot(BOT_TOKEN, threaded=True, num_threads=10)

# Admins & approval
ADMIN_IDS = [6403142441, 7470440084]   # admins
approved_users = set(ADMIN_IDS)        # users allowed to run commands
pending_users = set()

# Dump channel to also upload recordings
DUMP_CHANNEL_ID = -1002627919828

# Split threshold (MB)
MAX_SPLIT_SIZE_MB = 40

# Active recordings: { chat_id: { msg_id: {proc, title, start_ts, duration_sec, output_file} } }
active_recordings = {}

# Developer tag for caption
DEVELOPER_TAG = "@Shitijbro"
BRAND_SUFFIX = ".IPTV.WEB-DL@Shitijbro.dfmdubber.mkv"

# ----------------- Utilities -----------------
def is_admin(user_id):
    return user_id in approved_users

def human_duration(sec):
    hr = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{hr}hr, {m}min, {s}sec"

def nice_filesize(bytes_size):
    kb = bytes_size / 1024
    if kb < 1024:
        return f"{kb:.2f} KB"
    mb = kb / 1024
    if mb < 1024:
        return f"{mb:.2f} MB"
    gb = mb / 1024
    return f"{gb:.2f} GB"

def safe_edit_message(text, chat_id, message_id, parse_mode=None):
    if len(text) > 4096:
        text = text[:4090] + "..."
    try:
        bot.edit_message_text(text, chat_id, message_id, parse_mode=parse_mode)
    except ApiTelegramException:
        pass
    except Exception:
        pass

def timestamp_to_timestr(ts):
    t = time.localtime(ts)
    return time.strftime("%H:%M:%S", t)

def timestamp_to_datestr(ts):
    t = time.localtime(ts)
    return time.strftime("%d-%m-%Y", t)

def make_filename(title, start_ts, duration_sec):
    start_str = timestamp_to_timestr(start_ts)
    end_ts = start_ts + int(duration_sec)
    end_str = timestamp_to_timestr(end_ts)
    date_str = timestamp_to_datestr(start_ts)
    # sanitize title (remove spaces for filename pattern? keep spaces replaced with .)
    safe_title = title.replace(" ", ".")
    filename = f"testing.{safe_title}.Quality.{start_str}-{end_str}.{date_str}{BRAND_SUFFIX}"
    return filename

# ---------------- Decorators ----------------
def admin_only(func):
    @wraps(func)
    def wrapped(message, *args, **kwargs):
        user_id = message.from_user.id
        if user_id in approved_users:
            return func(message, *args, **kwargs)
        else:
            # send a request to admins
            if user_id not in pending_users:
                pending_users.add(user_id)
                # notify admins
                for a in ADMIN_IDS:
                    try:
                        bot.send_message(a, f"🛡️ Access request from @{getattr(message.from_user, 'username', 'unknown')} ({user_id}). Use /addadmin {user_id} to approve.")
                    except: pass
                bot.reply_to(message, "⏳ Your request has been sent to admins for approval. Please wait.")
            else:
                bot.reply_to(message, "⏳ Your request is still pending admin approval.")
    return wrapped

# -------------- Bot Commands ---------------
@bot.message_handler(commands=['start'])
def cmd_start(message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        # same approval flow
        if user_id not in pending_users:
            pending_users.add(user_id)
            for a in ADMIN_IDS:
                try:
                    bot.send_message(a, f"🛡️ Access request from @{getattr(message.from_user, 'username', 'unknown')} ({user_id}). Use /addadmin {user_id} to approve.")
                except: pass
            bot.reply_to(message, "👋 Welcome! Your access request has been sent to admins.")
        else:
            bot.reply_to(message, "👋 Welcome back — your access request is pending.")
        return
    bot.reply_to(message, "🤖 Bot is running. Use /help to see commands.")

@bot.message_handler(commands=['help'])
@admin_only
def cmd_help(message):
    text = (
        "📌 *Available Commands* (admins/approved users)\n\n"
        "/start - Start bot\n"
        "/help - This help\n"
        "/status - Bot status\n"
        "/record <URL> <hh:mm:ss> <title> - Start recording\n"
        "/cancel - Cancel a recording (reply to the bot's recording message)\n"
        "/recordings - Your active recordings\n"
        "/screenshot <URL> - Take one frame screenshot\n"
        "/broadcast <message> - Send message to all admins\n\n"
        "*Admin-only*\n"
        "/addadmin <user_id> - Approve & add admin\n"
        "/removeadmin <user_id> - Remove admin\n"
        "/users - Show approved users\n"
        "/allrecordings - Show all active recordings\n"
    )
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['status'])
@admin_only
def cmd_status(message):
    total = sum(len(x) for x in active_recordings.values())
    bot.reply_to(message, f"✅ Bot running. Active recordings: {total}")

@bot.message_handler(commands=['users'])
@admin_only
def cmd_users(message):
    txt = "✅ Approved users / admins:\n"
    for u in sorted(approved_users):
        txt += f"- {u}\n"
    bot.reply_to(message, txt)

@bot.message_handler(commands=['addadmin'])
@admin_only
def cmd_addadmin(message):
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /addadmin <user_id>")
        return
    try:
        uid = int(args[1])
        approved_users.add(uid)
        pending_users.discard(uid)
        bot.reply_to(message, f"✅ {uid} added to approved users.")
        try:
            bot.send_message(uid, "✅ You have been approved to use the recording bot.")
        except:
            pass
    except:
        bot.reply_to(message, "Invalid user id.")

@bot.message_handler(commands=['removeadmin'])
@admin_only
def cmd_removeadmin(message):
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /removeadmin <user_id>")
        return
    try:
        uid = int(args[1])
        if uid in approved_users:
            approved_users.discard(uid)
            bot.reply_to(message, f"✅ {uid} removed.")
        else:
            bot.reply_to(message, "User not in approved list.")
    except:
        bot.reply_to(message, "Invalid user id.")

@bot.message_handler(commands=['broadcast'])
@admin_only
def cmd_broadcast(message):
    try:
        text = message.text.split(None, 1)[1]
    except:
        bot.reply_to(message, "Usage: /broadcast <message>")
        return
    for a in ADMIN_IDS:
        try:
            bot.send_message(a, f"📣 Broadcast from {message.from_user.id}:\n\n{text}")
        except: pass
    bot.reply_to(message, "✅ Broadcast sent to admins.")

@bot.message_handler(commands=['screenshot'])
@admin_only
def cmd_screenshot(message):
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /screenshot <URL>")
        return
    url = args[1]
    filename = f"screenshot_{int(time.time())}.jpg"
    try:
        subprocess.run(['ffmpeg','-y','-i',url,'-vframes','1',filename], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if os.path.exists(filename):
            with open(filename, 'rb') as f:
                bot.send_photo(message.chat.id, f, caption=f"Screenshot from {url}")
            os.remove(filename)
        else:
            bot.reply_to(message, "❌ Screenshot failed.")
    except Exception as e:
        bot.reply_to(message, f"❌ Screenshot error: {str(e)}")

# ---------------- Recording Commands ----------------
@bot.message_handler(commands=['record'])
@admin_only
def cmd_record(message):
    """
    /record <URL> <hh:mm:ss> <title>
    Example: /record https://example.m3u8 00:05:00 Disney
    """
    args = message.text.split()
    if len(args) < 4:
        bot.reply_to(message, "Usage: /record <URL> <hh:mm:ss> <title>")
        return
    url = args[1].strip()
    dur_str = args[2].strip()
    title = " ".join(args[3:]).strip()
    try:
        h, m, s = map(int, dur_str.split(":"))
        duration_sec = h*3600 + m*60 + s
    except:
        bot.reply_to(message, "Invalid duration. Use hh:mm:ss")
        return

    # prepare file and start recording thread
    start_ts = int(time.time())
    filename = make_filename(title, start_ts, duration_sec)
    output_file = f"rec_{message.chat.id}_{start_ts}.mp4"

    sent = bot.reply_to(message, f"🎬 Recording '{title}' for {human_duration(duration_sec)} started...")
    msg_id = sent.message_id

    # launch thread
    t = threading.Thread(target=record_stream_worker, args=(message.chat.id, msg_id, url, duration_sec, title, output_file, filename, start_ts))
    t.daemon = True
    t.start()

@bot.message_handler(commands=['cancel'])
@admin_only
def cmd_cancel(message):
    # User should reply to the bot's recording message
    if not message.reply_to_message:
        bot.reply_to(message, "Reply to the recording message (the bot's 'Recording started' message) to cancel.")
        return
    chat_id = message.chat.id
    reply_id = message.reply_to_message.message_id
    if chat_id in active_recordings and reply_id in active_recordings[chat_id]:
        info = active_recordings[chat_id][reply_id]
        proc = info.get('proc')
        try:
            proc.terminate()
        except:
            try:
                proc.kill()
            except:
                pass
        bot.reply_to(message, "❌ Recording canceled.")
    else:
        bot.reply_to(message, "No active recording found for that message.")

@bot.message_handler(commands=['recordings'])
@admin_only
def cmd_recordings(message):
    chat_id = message.chat.id
    if chat_id not in active_recordings or not active_recordings[chat_id]:
        bot.reply_to(message, "No active recordings.")
        return
    text = "🎬 Your active recordings:\n"
    for mid, info in active_recordings[chat_id].items():
        title = info.get('title', 'Unknown')
        pid = None
        try:
            pid = info['proc'].pid
        except:
            pid = "N/A"
        started = info.get('start_ts')
        started_str = time.strftime("%d-%m-%Y %H:%M:%S", time.localtime(started)) if started else "N/A"
        text += f"- MsgID {mid}: {title} (PID: {pid}) Started: {started_str}\n"
    bot.reply_to(message, text)

@bot.message_handler(commands=['allrecordings'])
@admin_only
def cmd_allrecordings(message):
    total = sum(len(x) for x in active_recordings.values())
    if total == 0:
        bot.reply_to(message, "No active recordings.")
        return
    text = f"🎬 All active recordings ({total}):\n"
    for chat_id, recs in active_recordings.items():
        text += f"\nChat {chat_id}:\n"
        for mid, info in recs.items():
            title = info.get('title','Unknown')
            pid = info.get('proc').pid if info.get('proc') else "N/A"
            text += f"- MsgID {mid}: {title} (PID: {pid})\n"
    bot.reply_to(message, text)

# ---------------- Recording Worker ----------------
def record_stream_worker(chat_id, msg_id, url, duration_sec, title, output_file, final_filename, start_ts):
    # initialize active_recordings entry
    if chat_id not in active_recordings:
        active_recordings[chat_id] = {}
    # build ffmpeg command: copy stream to mp4 for given duration
    cmd = ['ffmpeg', '-y', '-i', url, '-t', str(duration_sec), '-c', 'copy', output_file]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    except Exception as e:
        safe_edit_message(f"❌ Failed to start ffmpeg: {e}", chat_id, msg_id)
        return

    # register
    active_recordings[chat_id][msg_id] = {
        'proc': proc,
        'title': title,
        'start_ts': start_ts,
        'duration_sec': duration_sec,
        'output_file': output_file,
        'final_filename': final_filename
    }

    # wait for process
    proc.wait()

    # check if file exists
    if not os.path.exists(output_file):
        safe_edit_message("❌ Recording failed (no output file).", chat_id, msg_id)
        # cleanup
        active_recordings[chat_id].pop(msg_id, None)
        if not active_recordings[chat_id]:
            active_recordings.pop(chat_id, None)
        return

    # upload steps
    safe_edit_message("✅ Recording finished. Preparing upload...", chat_id, msg_id)
    try:
        split_and_upload(chat_id, msg_id, output_file, title, start_ts, duration_sec, final_filename)
        safe_edit_message("✅ All uploads finished. Cleaning up...", chat_id, msg_id)
    except Exception as e:
        safe_edit_message(f"❌ Upload error: {e}", chat_id, msg_id)

    # cleanup active
    active_recordings[chat_id].pop(msg_id, None)
    if not active_recordings[chat_id]:
        active_recordings.pop(chat_id, None)

# ---------------- Split and Upload ----------------
def split_and_upload(chat_id, msg_id, file_path, title, start_ts, duration_sec, final_filename):
    total_bytes = os.path.getsize(file_path)
    total_mb = total_bytes / (1024*1024)

    if total_mb <= MAX_SPLIT_SIZE_MB:
        # single file - send
        caption = make_caption(final_filename, duration_sec, total_bytes)
        # send to chat with progress bar
        send_with_progress(chat_id, file_path, caption, status_parent_msg_id=msg_id)
        # also send to dump channel (no progress)
        send_to_dump(file_path, caption)
        os.remove(file_path)
        return

    # need to split by time into num_parts equal durations
    num_parts = math.ceil(total_mb / MAX_SPLIT_SIZE_MB)
    part_duration = math.ceil(duration_sec / num_parts)
    base, ext = os.path.splitext(file_path)
    parts = []

    for i in range(num_parts):
        part_file = f"{base}_part{i+1}{ext}"
        ss = i * part_duration
        # ensure last part doesn't exceed duration
        t = part_duration
        if ss + t > duration_sec:
            t = max(1, duration_sec - ss)
        ff = ['ffmpeg', '-y', '-i', file_path, '-ss', str(ss), '-t', str(t), '-c', 'copy', part_file]
        subprocess.run(ff, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if os.path.exists(part_file):
            parts.append((part_file, t))
        else:
            # fallback: abort splitting
            raise Exception("Splitting failed: missing part file.")

    # upload each part
    for idx, (part_file, part_dur) in enumerate(parts, start=1):
        bytes_part = os.path.getsize(part_file)
        caption = make_caption_part(final_filename, idx, len(parts), part_dur, bytes_part)
        send_with_progress(chat_id, part_file, caption, status_parent_msg_id=msg_id)
        send_to_dump(part_file, caption)
        try:
            os.remove(part_file)
        except: pass

    # remove original
    try:
        os.remove(file_path)
    except: pass

def make_caption(final_filename, duration_sec, bytes_size):
    return (
        f"📁 Filename: {final_filename}\n"
        f"⏱ Duration: {human_duration(int(duration_sec))}\n"
        f"📦 File-Size: {nice_filesize(bytes_size)}\n"
        f"👨‍💻 Developer: {DEVELOPER_TAG}"
    )

def make_caption_part(final_filename, idx, total, part_dur, bytes_size):
    # append part indicator to filename in caption
    name_part = final_filename.replace(BRAND_SUFFIX, f".part{idx}-of-{total}{BRAND_SUFFIX}")
    return (
        f"📁 Filename: {name_part}\n"
        f"⏱ Duration: {human_duration(int(part_dur))}\n"
        f"📦 File-Size: {nice_filesize(bytes_size)}\n"
        f"👨‍💻 Developer: {DEVELOPER_TAG}"
    )

# ---------------- Sending helpers ----------------
def send_with_progress(chat_id, file_path, caption, status_parent_msg_id=None):
    """
    Sends file to chat_id with a status message that shows upload progress.
    Reads file into memory (safe because we split to <= MAX_SPLIT_SIZE_MB).
    """
    try:
        status_msg = bot.send_message(chat_id, f"⬆️ Uploading... {os.path.basename(file_path)}")
    except:
        status_msg = None

    class ProgressIO(io.BytesIO):
        def __init__(self, buf, chat_id, status_msg_id):
            super().__init__(buf)
            self.chat_id = chat_id
            self.status_msg_id = status_msg_id
            self.total = len(buf)
            self.sent = 0
            self.last_update = 0

        def read(self, n=-1):
            chunk = super().read(n)
            if not chunk:
                return chunk
            self.sent += len(chunk)
            now = time.time()
            if now - self.last_update > 1.5:
                self.last_update = now
                try:
                    percent = (self.sent / self.total) * 100
                    bar = '█' * int(percent // 10) + '░' * (10 - int(percent // 10))
                    if self.status_msg_id:
                        safe_edit_message(f"⬆️ Uploading\n📊 {percent:.1f}% [{bar}]", self.chat_id, self.status_msg_id)
                    elif status_msg:
                        safe_edit_message(f"⬆️ Uploading\n📊 {percent:.1f}% [{bar}]", self.chat_id, status_msg.message_id)
                except:
                    pass
            return chunk

    with open(file_path, 'rb') as f:
        data = f.read()
    pio = ProgressIO(data, chat_id, status_msg.message_id if status_msg else None)
    try:
        bot.send_video(chat_id, pio, caption=caption)
    except Exception as e:
        # try sending as document if video fails
        try:
            pio.seek(0)
            bot.send_document(chat_id, pio, caption=caption)
        except:
            raise e

    # finish update
    if status_msg:
        try:
            safe_edit_message("✅ Upload complete!", chat_id, status_msg.message_id)
        except: pass

def send_to_dump(file_path, caption):
    """
    Send the same file to the dump channel (without progress bar).
    """
    try:
        with open(file_path, 'rb') as f:
            try:
                bot.send_video(DUMP_CHANNEL_ID, f, caption=caption)
            except:
                f.seek(0)
                bot.send_document(DUMP_CHANNEL_ID, f, caption=caption)
    except Exception:
        pass

# ------------- Start polling -------------
if __name__ == "__main__":
    print("🤖 Bot started!")
    try:
        bot.infinity_polling()
    except KeyboardInterrupt:
        print("Shutting down...")
    except Exception as e:
        print("Bot crashed:", e)
