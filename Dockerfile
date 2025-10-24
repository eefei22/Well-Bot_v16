# syntax=docker/dockerfile:1
ARG PY_VER=3.11
FROM python:${PY_VER}-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# --- Install required system libs for audio, mic, and ffmpeg ---
RUN apt-get update && apt-get install -y --no-install-recommends \
    libportaudio2 portaudio19-dev libasound2 libsndfile1 ffmpeg \
    build-essential pkg-config \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- Copy and install Python dependencies ---
COPY backend/requirements.txt ./requirements.txt
RUN pip install --upgrade pip setuptools wheel && \
    pip install -r requirements.txt

# --- Copy backend source code ---
COPY backend /app/backend

# --- Create non-root user (optional but good practice) ---
RUN useradd -m app && chown -R app:app /app
USER app

EXPOSE 8000

# --- Launch the application ---
CMD ["python", "backend/main.py"]
