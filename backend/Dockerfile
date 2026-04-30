FROM python:3.11-slim

WORKDIR /app

# System dependencies:
# - libpq-dev + gcc: required by psycopg2 and C-extension packages
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

RUN pip install --no-cache-dir poetry

COPY pyproject.toml poetry.lock* ./

# Export a flat requirements.txt from the lock file so pip handles the actual
# installation. This avoids Poetry's own installer, which does not support
# --mount=type=cache in Podman and has known issues with virtualenv detection
# in some container runtimes.
RUN poetry export -f requirements.txt --only main --without-hashes -o /tmp/requirements.txt

# Install torch before everything else.
# pytorch.org/whl/cpu only publishes linux_x86_64 wheels — installing one of
# those on an arm64 container causes SIGILL at import time.
# On arm64 (Apple Silicon Podman, etc.) we fall back to PyPI which has native wheels.
RUN arch=$(uname -m) && \
    if [ "$arch" = "x86_64" ]; then \
        pip install --no-cache-dir torch --extra-index-url https://download.pytorch.org/whl/cpu; \
    else \
        pip install --no-cache-dir torch; \
    fi

# Install remaining dependencies. pip skips torch because it is already satisfied.
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Chromium for Playwright (system libs installed above via apt)
RUN playwright install chromium

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
