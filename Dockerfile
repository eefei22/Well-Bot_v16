# syntax=docker/dockerfile:1

FROM python:3.13-slim AS base
WORKDIR /app

# Builder stage: install dependencies in a venv
FROM base AS builder
WORKDIR /app

# Copy only requirements.txt first for better caching
COPY --link backend/requirements.txt ./requirements.txt

# Create virtual environment and install dependencies
RUN python -m venv .venv \
    && .venv/bin/pip install --upgrade pip \
    && --mount=type=cache,target=/root/.cache/pip \
       .venv/bin/pip install -r requirements.txt

# Copy backend source code and relevant files
COPY --link backend ./backend

# Final stage: minimal runtime image
FROM base AS final
WORKDIR /app

# Copy backend source code
COPY --link backend ./backend

# Copy the virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Set PATH to use the venv
ENV PATH="/app/.venv/bin:$PATH"

# Create a non-root user
RUN useradd -m backenduser
USER backenduser

# Expose port if needed (uncomment if your app listens on a port)
# EXPOSE 8000

# Set entrypoint to run the backend service
CMD ["python", "backend/main.py"]
