# Mac quick start (read this first)

## Do NOT double-click dashboard.py

That opens **IDLE** (a code editor). You are not running the app — you are just viewing code.

## Easiest way: double-click START.command

1. Unzip the download **once**
2. Open the **`premarket-options`** folder
3. Double-click **`START.command`**
4. First time: it creates `.env` — add your Alpaca keys, save, double-click again
5. Browser opens with the dashboard

If Mac says "can't be opened": right-click **START.command** → **Open** → **Open**

## Or use Cursor (you already have it open)

1. In Cursor, open the **`premarket-options`** folder (one copy only — delete duplicates)
2. Menu: **Terminal → New Terminal**
3. Run:

```bash
pip3 install -r requirements.txt
cp .env.example .env
```

4. Edit `.env` in Cursor sidebar — add your keys
5. Run:

```bash
python3 -m streamlit run dashboard.py
```

Browser opens automatically.
