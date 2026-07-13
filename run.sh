#!/bin/bash

# Ensure we exit on error
set -e

# Path to the virtualenv
VENV_DIR=".venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "Virtual environment not found. Setting up..."
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install -r requirements.txt
    "$VENV_DIR/bin/playwright" install chromium
fi

echo "Activating virtual environment..."
source "$VENV_DIR/bin/activate"

echo "Starting FastAPI app via Uvicorn on http://localhost:8000..."
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
