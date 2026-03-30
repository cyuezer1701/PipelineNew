FROM python:3.11-slim

# Install FFmpeg, curl (healthcheck), fonts, and faster-whisper dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg curl fonts-dejavu-core \
        libgomp1 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download whisper base model during build (faster startup)
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('base', device='cpu', compute_type='int8')"

# Copy application code and assets
COPY app/ ./app/
COPY assets/ ./assets/

# Create output directory
RUN mkdir -p /app/output

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
