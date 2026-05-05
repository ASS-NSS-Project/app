FROM python:3.11-slim

WORKDIR /app

# Chromium runtime libs: installed manually because
# playwright install-deps fails on Debian Trixie
# due to missing font packages
RUN apt-get update && apt-get install -y \
    libpq-dev gcc zlib1g-dev \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 \
    libpango-1.0-0 libcairo2 libx11-6 libxcb1 libxext6 \
    libx11-xcb1 libglib2.0-0 libdbus-1-3 libexpat1 \
    fonts-liberation fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1

COPY pyproject.toml uv.lock ./

# Export a flat requirements.txt from the lock file, then install into
# the system Python so scripts land in /usr/local/bin (always on PATH).
RUN --mount=type=cache,target=/root/.cache/uv \
    uv export --frozen --no-dev --no-hashes -o /tmp/requirements.txt && \
    uv pip install --system \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        -r /tmp/requirements.txt

RUN playwright install chromium

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
