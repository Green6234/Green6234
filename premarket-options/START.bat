@echo off
cd /d "%~dp0"

echo Installing dependencies...
python -m pip install -r requirements.txt -q

if not exist .env (
  copy .env.example .env
  echo.
  echo Created .env — add your Alpaca keys, save, then double-click START.bat again.
  notepad .env
  exit /b 0
)

echo Starting dashboard...
python -m streamlit run dashboard.py
pause
