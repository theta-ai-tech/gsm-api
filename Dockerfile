# --- Base: slim Python runtime ---
FROM python:3.11-slim AS base

# Prevents Python from writing .pyc files & enables unbuffered logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Set a working directory inside the image
WORKDIR /app

# System deps (kept minimal). Add build tools only if you truly need them.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# --- Install deps first for better layer caching ---
# Copy only the project metadata first
COPY api/pyproject.toml /app/api/pyproject.toml

# Upgrade pip and install runtime + dev deps for the app package
# We use editable install so the package name is resolved cleanly.
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -e /app/api

# --- Copy the application source ---
COPY api/ /app/api/

# For FastAPI/Uvicorn, we’ll listen on $PORT (Cloud Run convention)
ENV PORT=8080

# Create a non-root user for security
RUN useradd -m appuser
USER appuser

# Default command: run FastAPI with Uvicorn
# Note: --host 0.0.0.0 is required in containers; port comes from $PORT
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --app-dir /app/api"]
