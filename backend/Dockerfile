# syntax=docker/dockerfile:1
FROM python:3.11-slim

WORKDIR /app

# System dependencies:
# - libpq-dev + gcc: required by psycopg2 and any C-extension packages
# - Chromium runtime libs: installed manually because playwright install-deps
#   fails on Debian Trixie due to missing font packages
RUN apt-get update && apt-get install -y \
    libpq-dev gcc \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 \
    libpango-1.0-0 libcairo2 libx11-6 libxcb1 libxext6 \
    libx11-xcb1 libglib2.0-0 libdbus-1-3 libexpat1 \
    fonts-liberation fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install CPU-only PyTorch before everything else.
# Without this, sentence-transformers and FlagEmbedding pull in the CUDA
# variant of torch (~2 GB) even though no GPU is present in the container.
# The CPU wheel is ~250 MB and fully sufficient for BGE-M3 inference.
#
# The BuildKit cache mount keeps downloaded wheels across rebuilds — changing
# requirements.txt no longer triggers a full re-download from PyPI.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install torch --extra-index-url https://download.pytorch.org/whl/cpu && \
    pip install -r requirements.txt

# Chromium for Playwright (skipping install-deps — handled by apt above)
RUN playwright install chromium

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
