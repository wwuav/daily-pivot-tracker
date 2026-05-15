import requests
import os
import sys
from datetime import datetime, timezone

DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]

# CoinGecko IDs for each coin
COINS = [
    {"id": "bitcoin",       "symbol": "BTC"},
    {"id": "ethereum",      "symbol": "ETH"},
    {"id": "sui",           "symbol": "SUI"},
    {"id": "solana",        "symbol": "SOL"},
    {"id": "monero",        "symbol": "XMR"},
    {"id": "astar",         "symbol": "ASTR"},
]

def get_ohlc(coin_id, days):
    """Get OHLC data from CoinGecko. days=1 for daily, 7 for weekly, 30 for monthly."""
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc"
    params = {"vs_currency": "usd", "days": days}
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()  # [[timestamp, open, high, low, close], ...]
    if not data:
        return None
    # Use the most recent completed candle (second to last, last may be incomplete)
    candle = data[-2] if len(data) >= 2 else data[-1]
    _, open_, high, low, close = candle
    return {"open": open_, "high": high, "low": low, "close": close}

def calculate_levels(high, low, close):
    """Calculate pivot point + S1-S4 + R1-R4 + all midpoints."""
    P  = (high + low + close) / 3

    R1 = (2 * P) - low
    R2 = P + (high - low)
    R3 = R2 + (high - low)
    R4 = R3 + (high - low)

    S1 = (2 * P) - high
    S2 = P - (high - low)
    S3 = S2 - (high - low)
    S4 = S3 - (high - low)

    # Midpoints between each level
    mp_p_r1 = (P + R1) / 2
    mp_r1_r2 = (R1 + R2) / 2
    mp_r2_r3 = (R2 + R3) / 2
    mp_r3_r4 = (R3 + R4) / 2

    mp_p_s1 = (P + S1) / 2
    mp_s1_s2 = (S1 + S2) / 2
    mp_s2_s3 = (S2 + S3) / 2
    mp_s3_s4 = (S3 + S4) / 2

    return {
        "P":        P,
        "mp_p_s1":  mp_p_s1,
        "S1":       S1,
        "mp_s1_s2": mp_s1_s2,
        "S2":       S2,
        "mp_s2_s3": mp_s2_s3,
        "S3":       S3,
        "mp_s3_s4": mp_s3_s4,
        "S4":       S4,
        "mp_p_r1":  mp_p_r1,
        "R1":       R1,
        "mp_r1_r2": mp_r1_r2,
        "R2":       R2,
        "mp_r2_r3": mp_r2_r3,
        "R3":       R3,
        "mp_r3_r4": mp_r3_r4,
        "R4":       R4,
    }

def fmt(price):
    """Format price — no decimals for large coins, 4dp for small."""
    if price >= 100:
        return f"{price:,.0f}"
    elif price >= 1:
        return f"{price:,.2f}"
    else:
        return f"{price:,.4f}"

def build_message(symbol, timeframe_label, levels):
    """Build the vertical Discord message for one coin."""
    lines = [
        f"{symbol} {timeframe_label} Target is {fmt(levels['P'])}",
        f"MP    {fmt(levels['mp_p_s1'])}",
        f"S1    {fmt(levels['S1'])}",
        f"MP    {fmt(levels['mp_s1_s2'])}",
        f"S2    {fmt(levels['S2'])}",
        f"MP    {fmt(levels['mp_s2_s3'])}",
        f"S3    {fmt(levels['S3'])}",
        f"MP    {fmt(levels['mp_s3_s4'])}",
        f"S4    {fmt(levels['S4'])}",
        f"MP    {fmt(levels['mp_p_r1'])}",
        f"R1    {fmt(levels['R1'])}",
        f"MP    {fmt(levels['mp_r1_r2'])}",
        f"R2    {fmt(levels['R2'])}",
        f"MP    {fmt(levels['mp_r2_r3'])}",
        f"R3    {fmt(levels['R3'])}",
        f"MP    {fmt(levels['mp_r3_r4'])}",
        f"R4    {fmt(levels['R4'])}",
    ]
    return "\n".join(lines)

def send_to_discord(message):
    payload = {"content": message}
    r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
    r.raise_for_status()

def run(timeframe):
    """timeframe: daily | weekly | monthly"""
    if timeframe == "daily":
        days = 1
        label = "Daily"
    elif timeframe == "weekly":
        days = 7
        label = "Weekly"
    elif timeframe == "monthly":
        days = 30
        label = "Monthly"
    else:
        raise ValueError(f"Unknown timeframe: {timeframe}")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    header = f"--- {label} Pivot Targets | {now} ---"
    send_to_discord(header)

    for coin in COINS:
        ohlc = get_ohlc(coin["id"], days)
        if not ohlc:
            send_to_discord(f"{coin['symbol']}: no data available")
            continue
        levels = calculate_levels(ohlc["high"], ohlc["low"], ohlc["close"])
        msg = build_message(coin["symbol"], label, levels)
        send_to_discord(msg)
        print(msg)
        print()

if __name__ == "__main__":
    # Pass timeframe as argument: python pivot_script.py daily|weekly|monthly
    timeframe = sys.argv[1] if len(sys.argv) > 1 else "daily"
    run(timeframe)import requests
import os
from datetime import datetime, timezone

DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]

COINS = ["bitcoin", "ethereum", "solana", "ripple", "dogecoin"]

def get_pivot_data():
    ids = ",".join(COINS)
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {"vs_currency": "usd", "ids": ids, "order": "market_cap_desc", "per_page": 10, "page": 1, "sparkline": False, "price_change_percentage": "24h"}
    response = requests.get(url, params=params, timeout=15)
    response.raise_for_status()
    return response.json()

def calculate_pivot(high, low, close):
    pivot = (high + low + close) / 3
    r1 = (2 * pivot) - low
    s1 = (2 * pivot) - high
    r2 = pivot + (high - low)
    s2 = pivot - (high - low)
    return pivot, r1, s1, r2, s2

def format_message(coins_data):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = ["Daily Pivot Report - " + now]
    for coin in coins_data:
        name = coin["name"]
        symbol = coin["symbol"].upper()
        price = coin["current_price"]
        high = coin["high_24h"]
        low = coin["low_24h"]
        close = price
        change = coin.get("price_change_percentage_24h", 0) or 0
        pivot, r1, s1, r2, s2 = calculate_pivot(high, low, close)
        direction = "UP" if change >= 0 else "DN"
        lines.append(direction + " " + name + " (" + symbol + ") $" + str(round(price,2)) + " (" + str(round(change,2)) + "%)")
        lines.append("  Pivot: $" + str(round(pivot,2)) + " R1: $" + str(round(r1,2)) + " S1: $" + str(round(s1,2)))
        lines.append("  R2: $" + str(round(r2,2)) + " S2: $" + str(round(s2,2)))
    return "\n".join(lines)

def send_to_discord(message):
    payload = {"content": message}
    r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
    r.raise_for_status()

if __name__ == "__main__":
    data = get_pivot_data()
    msg = format_message(data)
    send_to_discord(msg)
