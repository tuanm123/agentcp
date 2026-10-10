# ── Stage 1: Build React frontend ──────────────────────────────────────────
FROM node:20-alpine AS ui

WORKDIR /app

COPY frontend/package*.json ./
RUN npm ci --prefer-offline

COPY frontend/ ./
RUN npm run build          # output -> /app/dist


# ── Stage 2: Python backend ─────────────────────────────────────────────────
FROM python:3.11-slim AS backend

# System deps for Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
        libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY agentcp/ agentcp/
COPY backend.py .

# Copy built React static files
COPY --from=ui /app/dist /app/static

# Serve static files from FastAPI
ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn backend:app --host 0.0.0.0 --port ${PORT}"]
