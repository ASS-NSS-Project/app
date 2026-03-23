# We start from an official Python image.
# "slim" means it's a smaller version without unnecessary tools.
FROM python:3.11-slim

# Set the working directory inside the container.
# All commands below run from /app.
WORKDIR /app

# Install system dependencies needed by:
# - Playwright (the headless browser): needs Chromium + its libraries
# - sentence-transformers: needs some C libraries
# - psycopg2: needs libpq for PostgreSQL connection
RUN apt-get update && apt-get install -y \
    wget curl gnupg \
    libpq-dev gcc \
    # Chromium runtime dependencies (installed manually to avoid
    # playwright install-deps failing on missing font packages in Debian Trixie)
    libnss3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 \
    libpango-1.0-0 libcairo2 libx11-6 libxcb1 libxext6 \
    libx11-xcb1 libglib2.0-0 libdbus-1-3 libexpat1 \
    fonts-liberation fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (Docker caches this layer,
# so reinstalling packages only happens when requirements.txt changes)
COPY requirements.txt .

# Install Python packages
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright's Chromium browser
# We skip install-deps because we installed dependencies manually above
# (playwright install-deps fails on Debian Trixie due to missing font packages)
RUN playwright install chromium

# Copy all application code into the container
COPY . .

# Default command (overridden in docker-compose.yml per service)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
