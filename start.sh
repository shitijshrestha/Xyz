#!/bin/bash
# Ensure rclone config exists
if [ ! -f rclone.conf ]; then
    echo "rclone.conf not found!"
fi

# Run bot
python3 bot.py
