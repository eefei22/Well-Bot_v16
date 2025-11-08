# syntax=docker/dockerfile:1

FROM python:3.12-slim AS base

WORKDIR /app

# Install system dependencies for audio processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    portaudio19-dev \
    libasound2-dev \
    libsndfile1 \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Dependencies stage - install Python packages
FROM base AS deps
COPY backend/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Final stage
FROM base AS final

# Copy installed dependencies from deps stage
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Create non-privileged user
ARG UID=10001
RUN groupadd -r appuser && useradd -r -u "${UID}" -g appuser appuser

# Copy backend code (includes all config files)
COPY backend/ /app/backend/

# Handle architecture-specific wake word model
ARG TARGETARCH=amd64
RUN if [ "$TARGETARCH" = "arm64" ]; then \
        cp /app/backend/config/WakeWord/WellBot_WakeWordModel_ARM.ppn /app/backend/config/WakeWord/WellBot_WakeWordModel.ppn; \
    fi && \
    rm -f /app/backend/config/WakeWord/WellBot_WakeWordModel_ARM.ppn && \
    chown -R appuser:appuser /app

USER appuser

WORKDIR /app/backend

ENTRYPOINT ["python", "main.py"]
