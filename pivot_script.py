import requests
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
