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

RUN pip install poetry

# Disable virtualenv creation — in a container the system Python is the env.
ENV POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1 \
    POETRY_CACHE_DIR=/root/.cache/pypoetry

COPY pyproject.toml poetry.lock* ./

# poetry.lock* is optional — if absent, Poetry resolves fresh (first build only).
# Commit the generated poetry.lock for reproducible subsequent builds.
RUN --mount=type=cache,target=/root/.cache/pypoetry \
    poetry install --no-root --only main

# Chromium for Playwright (system libs installed above via apt)
RUN playwright install chromium

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
