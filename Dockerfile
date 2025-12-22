FROM python:3.11-slim

# Install FFmpeg and its dependencies
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Set the working directory inside the container
WORKDIR /app

# Copy the entire project directory (requirements.txt and bot folder)
COPY . /app/

# Install Python dependencies from the requirements.txt file
RUN pip install --no-cache-dir -r requirements.txt

# Run the bot using python3 -m when the container starts
CMD ["python3", "-m", "bot"]

