# syntax=docker/dockerfile:1
ARG PY_VER=3.11
FROM python:${PY_VER}-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# Install system libs (audio, mic, ffmpeg) — good
RUN apt-get update && apt-get install -y --no-install-recommends \
      libportaudio2 portaudio19-dev libasound2 libsndfile1 ffmpeg \
      build-essential pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --upgrade pip setuptools wheel \
    && pip install -r requirements.txt

COPY backend /app/backend

# Non-root user
RUN useradd -m app && chown -R app:app /app
USER app

# Expose port
EXPOSE 8000

# Default command
CMD ["python", "backend/main.py"]
