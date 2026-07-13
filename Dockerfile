FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

WORKDIR /app

# Install system dependencies needed for Playwright's browser installation
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browser binaries and their system dependencies.
# Since Docker builds run as the root user, this command succeeds without su/sudo errors.
RUN playwright install --with-deps chromium

# Copy the rest of the application
COPY . .

# Run the FastAPI application
CMD uvicorn main:app --host 0.0.0.0 --port $PORT
