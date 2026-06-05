# Polyscanner

Polls active Polymarket markets and sends Telegram alerts for sharp price moves, extreme prices, and new markets.

## Running locally

```bash
# 1. Clone the repo
git clone <repo-url>
cd polymarket-bot

# 2. Create a .env file with your Telegram credentials
cp .env.example .env   # or create it manually
# TELEGRAM_BOT_TOKEN=your_bot_token
# TELEGRAM_CHAT_ID=your_chat_id

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run
python monitor.py
```

Press `Ctrl+C` to stop.

## Alert types

| Alert | Trigger |
|---|---|
| 🆕 New Market | A market appears for the first time |
| 🔴 Sharp Move | Any outcome moves ≥ 15% since last poll |
| 🟡 Extreme Price | Volume > $50k and an outcome is priced < 8% or > 92% |

Sports and game markets are excluded from all alerts.
