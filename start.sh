#!/bin/bash
echo "🔧 Setting up environment..."
sudo apt update -y
sudo apt install -y python3 python3-pip ffmpeg git

echo "📦 Installing dependencies..."
pip3 install -r requirements.txt

echo "🚀 Starting Telegram Bot..."
python3 bot.py