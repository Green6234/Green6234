#!/bin/bash
cd "$(dirname "$0")"
python3 -m pip install -r requirements.txt -q
echo "Starting dashboard..."
python3 -m streamlit run dashboard.py
