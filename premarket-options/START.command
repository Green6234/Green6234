#!/bin/bash
# Double-click this file in Finder to launch the dashboard.
cd "$(dirname "$0")"

echo "Installing dependencies (first run may take a minute)..."
python3 -m pip install -r requirements.txt -q

if [ ! -f .env ]; then
  cp .env.example .env
  echo ""
  echo "Created .env — add your Alpaca keys, then double-click START.command again."
  open -e .env
  exit 0
fi

echo "Starting dashboard — your browser will open shortly..."
python3 -m streamlit run dashboard.py
