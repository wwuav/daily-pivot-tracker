import requests
import os
import sys
from datetime import datetime, timezone

DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]

COINS = [
    {"id": "bitcoin",  "symbol": "BTC"},
    {"id": "ethereum", "symbol": "ETH"},
    {"id": "sui",      "symbol": "SUI"},
    {"id": "solana",   "symbol": "SOL"},
    {"id": "monero",   "symbol": "XMR"},
    {"id": "astar",    "symbol": "ASTR"},
]

def get_ohlc(coin_id, days):
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc"
    params = {"vs_currency": "usd", "days": days}
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    if not data:
        return None
    candle = data[-2] if len(data) >= 2 else data[-1]
    _, open_, high, low, close = candle
    return {"open": open_, "high": high, "low": low, "close": close}

def calculate_levels(high, low, close):
    P  = (high + low + close) / 3
    R1 = (2 * P) - low
    R2 = P + (high - low)
    R3 = R2 + (high - low)
    R4 = R3 + (high - low)
    S1 = (2 * P) - high
    S2 = P - (high - low)
    S3 = S2 - (high - low)
    S4 = S3 - (high - low)
    mp_p_s1  = (P  + S1) / 2
    mp_s1_s2 = (S1 + S2) / 2
    mp_s2_s3 = (S2 + S3) / 2
    mp_s3_s4 = (S3 + S4) / 2
    mp_p_r1  = (P  + R1) / 2
    mp_r1_r2 = (R1 + R2) / 2
    mp_r2_r3 = (R2 + R3) / 2
    mp_r3_r4 = (R3 + R4) / 2
    return {"P": P, "mp_p_s1": mp_p_s1, "S1": S1, "mp_s1_s2": mp_s1_s2, "S2": S2, "mp_s2_s3": mp_s2_s3, "S3": S3, "mp_s3_s4": mp_s3_s4, "S4": S4, "mp_p_r1": mp_p_r1, "R1": R1, "mp_r1_r2": mp_r1_r2, "R2": R2, "mp_r2_r3": mp_r2_r3, "R3": R3, "mp_r3_r4": mp_r3_r4, "R4": R4}

def fmt(price):
    if price >= 100:
        return f"{price:,.0f}"
    elif price >= 1:
        return f"{price:,.2f}"
    else:
        return f"{price:,.4f}"

def build_message(symbol, label, lv):
    lines = [
        f"{symbol} {label} Target is {fmt(lv['P'])}",
        f"MP    {fmt(lv['mp_p_s1'])}",
        f"S1    {fmt(lv['S1'])}",
        f"MP    {fmt(lv['mp_s1_s2'])}",
        f"S2    {fmt(lv['S2'])}",
        f"MP    {fmt(lv['mp_s2_s3'])}",
        f"S3    {fmt(lv['S3'])}",
        f"MP    {fmt(lv['mp_s3_s4'])}",
        f"S4    {fmt(lv['S4'])}",
        f"MP    {fmt(lv['mp_p_r1'])}",
        f"R1    {fmt(lv['R1'])}",
        f"MP    {fmt(lv['mp_r1_r2'])}",
        f"R2    {fmt(lv['R2'])}",
        f"MP    {fmt(lv['mp_r2_r3'])}",
        f"R3    {fmt(lv['R3'])}",
        f"MP    {fmt(lv['mp_r3_r4'])}",
        f"R4    {fmt(lv['R4'])}",
    ]
    return "\n".join(lines)

def send(msg):
    r = requests.post(DISCORD_WEBHOOK, json={"content": msg}, timeout=10)
    r.raise_for_status()

def run(timeframe):
    cfg = {"daily": (1, "Daily"), "weekly": (7, "Weekly"), "monthly": (30, "Monthly")}
    if timeframe not in cfg:
        raise ValueError("Unknown timeframe: " + timeframe)
    days, label = cfg[timeframe]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    send("--- " + label + " Pivot Targets | " + now + " ---")
    for coin in COINS:
        ohlc = get_ohlc(coin["id"], days)
        if not ohlc:
            send(coin["symbol"] + ": no data")
            continue
        lv = calculate_levels(ohlc["high"], ohlc["low"], ohlc["close"])
        msg = build_message(coin["symbol"], label, lv)
        send(msg)
        print(msg)

if __name__ == "__main__":
    timeframe = sys.argv[1] if len(sys.argv) > 1 else "daily"
    run(timeframe)
