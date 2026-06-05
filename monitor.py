#!/usr/bin/env python3
"""Polymarket monitoring daemon — polls active markets and sends Telegram alerts."""

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

POLYMARKET_BASE = "https://gamma-api.polymarket.com"
TELEGRAM_BASE = "https://api.telegram.org"
STATE_FILE = Path("polymarket_state.json")
POLL_INTERVAL = 300  # seconds
PAGE_LIMIT = 100

SHARP_MOVE_THRESHOLD = 0.15  # 15%
HIGH_VOLUME_THRESHOLD = 50_000  # USD
EXTREME_PRICE_LOW = 0.08
EXTREME_PRICE_HIGH = 0.92
MIN_VOLUME = 1_000  # skip markets with volume below this (USD)
MIN_LIQUIDITY_API = 50_000  # server-side filter: only fetch markets with liquidity >= this (USD)

# Keywords that indicate sports/game markets — excluded from all alerts
SPORTS_KEYWORDS = [
    "win the", "win on ", "fc win", "vs.", " draw", "world cup",
    "premier league", "nba", "nfl", "mlb", "nhl", "la liga", "bundesliga",
    "serie a", "ligue 1", "champions league", "europa league",
    "super bowl", "stanley cup", "world series",
    "gold medal", "olympic", "ufc ", "boxing match", "wimbledon",
    "grand slam", "tour de france",
]

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

def send_telegram(token: str, chat_id: str, text: str) -> None:
    url = f"{TELEGRAM_BASE}/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.error("Telegram send failed: %s", exc)


# ---------------------------------------------------------------------------
# Polymarket API
# ---------------------------------------------------------------------------

def fetch_active_markets() -> list[dict]:
    """Paginate through all active markets and return them."""
    markets: list[dict] = []
    offset = 0
    session = requests.Session()

    while True:
        url = f"{POLYMARKET_BASE}/markets"
        params = {"active": "true", "limit": PAGE_LIMIT, "offset": offset, "liquidity_num_min": MIN_LIQUIDITY_API}
        try:
            resp = session.get(url, params=params, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as exc:
            log.error("Error fetching markets (offset=%d): %s", offset, exc)
            break

        page = resp.json()
        if not isinstance(page, list):
            log.error("Unexpected response shape: %r", type(page))
            break

        markets.extend(page)
        log.info("Fetched %d markets (offset=%d)", len(page), offset)

        if len(page) < PAGE_LIMIT:
            break
        offset += PAGE_LIMIT

    return markets


def parse_prices(market: dict) -> list[float]:
    """Return outcome prices as floats; empty list on failure."""
    raw = market.get("outcomePrices")
    if not raw:
        return []
    try:
        if isinstance(raw, str):
            raw = json.loads(raw)
        return [float(p) for p in raw]
    except (json.JSONDecodeError, ValueError, TypeError):
        return []


def market_volume(market: dict) -> float:
    try:
        return float(market.get("volume") or 0)
    except (ValueError, TypeError):
        return 0.0


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text())
            log.info("Loaded state: %d markets known", len(data))
            return data
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Could not read state file, starting fresh: %s", exc)
    return {}


def save_state(state: dict) -> None:
    try:
        STATE_FILE.write_text(json.dumps(state, indent=2))
    except OSError as exc:
        log.error("Could not save state: %s", exc)


# ---------------------------------------------------------------------------
# Alert logic
# ---------------------------------------------------------------------------

def check_market(
    market: dict,
    state: dict,
    token: str,
    chat_id: str,
    is_first_run: bool,
) -> None:
    cid = market.get("conditionId") or market.get("id") or market.get("slug")
    if not cid:
        return

    question = market.get("question", "(no question)")
    prices = parse_prices(market)
    volume = market_volume(market)
    end_date = market.get("endDate", "?")

    known = state.get(cid)

    # --- New market ---
    if known is None:
        state[cid] = {"prices": prices, "question": question}
        if not is_first_run:
            msg = (
                f"🆕 *New Market* — {question}\n"
                f"Vol: ${volume:,.0f} | Ends: {end_date}"
            )
            log.info("NEW MARKET: %s", question)
            send_telegram(token, chat_id, msg)
        return

    old_prices: list[float] = known.get("prices", [])

    # --- Sharp price move ---
    outcomes = market.get("outcomes")
    if isinstance(outcomes, str):
        try:
            outcomes = json.loads(outcomes)
        except json.JSONDecodeError:
            outcomes = None

    for i, new_price in enumerate(prices):
        if i >= len(old_prices):
            break
        old_price = old_prices[i]
        delta = abs(new_price - old_price)
        if delta >= SHARP_MOVE_THRESHOLD:
            label = outcomes[i] if outcomes and i < len(outcomes) else f"Outcome {i}"
            msg = (
                f"🔴 *Sharp Move* — {question}\n"
                f"{label}: {old_price:.0%} → {new_price:.0%}"
            )
            log.info("SHARP MOVE: %s | %s: %.0f%% → %.0f%%", question, label, old_price * 100, new_price * 100)
            send_telegram(token, chat_id, msg)

    # --- High volume + extreme price ---
    # Only alert once; clear flag if price normalizes back into range
    was_extreme = known.get("extreme_alerted", False)
    is_extreme_now = False

    if volume > HIGH_VOLUME_THRESHOLD:
        for i, price in enumerate(prices):
            if price < EXTREME_PRICE_LOW or price > EXTREME_PRICE_HIGH:
                is_extreme_now = True
                if not was_extreme:
                    label = outcomes[i] if outcomes and i < len(outcomes) else f"Outcome {i}"
                    msg = (
                        f"🟡 *Extreme Price* — {question}\n"
                        f"Vol: ${volume:,.0f} | {label}: {price:.0%}"
                    )
                    log.info("EXTREME PRICE: %s | vol=%.0f price=%.2f", question, volume, price)
                    send_telegram(token, chat_id, msg)
                break  # one alert per market per poll

    state[cid]["extreme_alerted"] = is_extreme_now

    # Update stored prices
    state[cid]["prices"] = prices


# ---------------------------------------------------------------------------
# Main poll loop
# ---------------------------------------------------------------------------

def poll(state: dict, token: str, chat_id: str, is_first_run: bool) -> None:
    log.info("Starting poll (first_run=%s)", is_first_run)
    markets = fetch_active_markets()
    log.info("Total active markets fetched: %d", len(markets))

    skipped = 0
    for market in markets:
        if market_volume(market) < MIN_VOLUME:
            skipped += 1
            continue
        if market.get("closed"):
            skipped += 1
            continue
        question_lower = (market.get("question") or "").lower()
        if any(kw in question_lower for kw in SPORTS_KEYWORDS):
            skipped += 1
            continue
        try:
            check_market(market, state, token, chat_id, is_first_run)
        except Exception as exc:
            log.error("Error processing market %r: %s", market.get("conditionId"), exc)

    log.info("Skipped %d low-volume markets (< $%s)", skipped, f"{MIN_VOLUME:,}")

    save_state(state)
    log.info("Poll complete — state has %d markets", len(state))


def main() -> None:
    load_dotenv()

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        log.warning(
            "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set — alerts will be skipped"
        )

    print(f"Polyscanner running — polling every {POLL_INTERVAL // 60} min, alerts → Telegram")

    state = load_state()
    is_first_run = len(state) == 0

    try:
        while True:
            try:
                poll(state, token, chat_id, is_first_run)
                is_first_run = False
            except Exception as exc:
                log.error("Unhandled error in poll cycle: %s", exc)

            log.info("Sleeping %d seconds until next poll …", POLL_INTERVAL)
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        print("\nPolyscanner stopped.")


if __name__ == "__main__":
    main()
