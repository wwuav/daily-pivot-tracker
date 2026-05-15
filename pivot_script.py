import requests
import os
import sys
from datetime import datetime, timezone

DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]

# Binance USDT pairs (symbol on Binance, display label)
BINANCE_COINS = [
    {"symbol": "BTCUSDT",  "label": "BTC"},
    {"symbol": "ETHUSDT",  "label": "ETH"},
    {"symbol": "SUIUSDT",  "label": "SUI"},
    {"symbol": "SOLUSDT",  "label": "SOL"},
    {"symbol": "XMRUSDT",  "label": "XMR"},
]

# DEX coins via GeckoTerminal (not on Binance)
GT_COINS = [
    {"network": "bsc", "pool": "0x7e58f160b5b77b8b24cd9900c09a3e730215ac47", "label": "ASTER"},
]

# Binance interval codes per timeframe
BINANCE_INTERVAL = {
    "daily":   "1d",
    "weekly":  "1w",
    "monthly": "1M",
}


def get_binance_closed_candle(symbol, timeframe):
    """Fetch the most recently CLOSED candle from Binance klines.
    With limit=2: index 0 = just-closed candle, index 1 = currently forming candle.
    Returns dict with open, high, low, close."""
    interval = BINANCE_INTERVAL[timeframe]
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": 2}
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    # data[0] = just-closed, data[1] = currently forming
    candle = data[0]
    # kline format: [open_time, open, high, low, close, volume, ...]
    return {
        "open":  float(candle[1]),
        "high":  float(candle[2]),
        "low":   float(candle[3]),
        "close": float(candle[4]),
    }


def get_gt_closed_candle(network, pool, timeframe):
    """Fetch the most recently CLOSED candle from GeckoTerminal.
    With limit=2: ohlcv_list[0] = currently forming, ohlcv_list[1] = just closed.
    Returns dict with open, high, low, close."""
    tf_map = {"daily": "day", "weekly": "week", "monthly": "month"}
    gt_tf = tf_map[timeframe]
    url = f"https://api.geckoterminal.com/api/v2/networks/{network}/pools/{pool}/ohlcv/{gt_tf}"
    params = {"limit": 2, "currency": "usd"}
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    ohlcv_list = data["data"]["attributes"]["ohlcv_list"]
    # newest first: [0] = forming now, [1] = just closed
    candle = ohlcv_list[1] if len(ohlcv_list) >= 2 else ohlcv_list[0]
    # format: [timestamp, open, high, low, close, volume]
    return {
        "open":  float(candle[1]),
        "high":  float(candle[2]),
        "low":   float(candle[3]),
        "close": float(candle[4]),
    }


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
    return {
        "P":        P,
        "mp_p_s1":  (P  + S1) / 2,
        "S1":       S1,
        "mp_s1_s2": (S1 + S2) / 2,
        "S2":       S2,
        "mp_s2_s3": (S2 + S3) / 2,
        "S3":       S3,
        "mp_s3_s4": (S3 + S4) / 2,
        "S4":       S4,
        "mp_p_r1":  (P  + R1) / 2,
        "R1":       R1,
        "mp_r1_r2": (R1 + R2) / 2,
        "R2":       R2,
        "mp_r2_r3": (R2 + R3) / 2,
        "R3":       R3,
        "mp_r3_r4": (R3 + R4) / 2,
        "R4":       R4,
    }


def fmt(price):
    if price >= 100:
        return f"{price:,.0f}"
    elif price >= 1:
        return f"{price:,.2f}"
    else:
        return f"{price:,.4f}"


def build_message(label, tf_label, lv):
    lines = [
        f"{label} {tf_label} Target is {fmt(lv['P'])}",
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
    valid = ("daily", "weekly", "monthly")
    if timeframe not in valid:
        raise ValueError("Unknown timeframe: " + timeframe)
    tf_label = {"daily": "Daily", "weekly": "Weekly", "monthly": "Monthly"}[timeframe]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    send(f"--- {tf_label} Pivot Targets | {now} ---")

    for coin in BINANCE_COINS:
        try:
            ohlc = get_binance_closed_candle(coin["symbol"], timeframe)
            lv   = calculate_levels(ohlc["high"], ohlc["low"], ohlc["close"])
            msg  = build_message(coin["label"], tf_label, lv)
            send(msg)
            print(msg)
        except Exception as e:
            err = coin["label"] + ": error - " + str(e)
            print(err)
            send(err)

    for coin in GT_COINS:
        try:
            ohlc = get_gt_closed_candle(coin["network"], coin["pool"], timeframe)
            lv   = calculate_levels(ohlc["high"], ohlc["low"], ohlc["close"])
            msg  = build_message(coin["label"], tf_label, lv)
            send(msg)
            print(msg)
        except Exception as e:
            err = coin["label"] + ": error - " + str(e)
            print(err)
            send(err)


if __name__ == "__main__":
    timeframe = sys.argv[1] if len(sys.argv) > 1 else "daily"
    run(timeframe)
