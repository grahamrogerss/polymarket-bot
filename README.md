# Polymarket Bot

A lightweight Python daemon that monitors [Polymarket](https://polymarket.com) prediction markets and sends real-time Telegram alerts when something significant happens.

## What it does

Polls all active Polymarket markets every 5 minutes and fires alerts for three signal types:

- **Sharp price move** — any outcome shifts more than 15% in a single poll cycle
- **Extreme consensus** — a market with >$50K volume has an outcome above 92% or below 8%
- **New market** — a qualifying market appears that wasn't there last poll

Filters out sports markets and low-volume markets (<$1K) to reduce noise.

## How it works

1. Fetches all active markets from the Polymarket API (paginated)
2. Compares current prices against a local state file from the previous poll
3. Fires a Telegram message for any market that hits a signal threshold
4. Saves updated state to disk so it persists across restarts

No AI in the loop — zero per-poll cost.

## Setup
```bash
git clone https://github.com/grahamrogerss/polymarket-bot
cd polymarket-bot
pip install -r requirements.txt


Create a .env file:

TELEGRAM_BOT_TOKEN=your_token_here
TELEGRAM_CHAT_ID=your_chat_id_here


Then run:
```
```bash
python monitor.py


The first poll seeds the state file. Alerts start firing on the second poll (5 minutes later).

Stack
Python 3.11+
requests for API calls
python-dotenv for config
Telegram Bot API for alerts
JSON file for state persistence
