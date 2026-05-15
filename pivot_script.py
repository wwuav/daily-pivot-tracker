import requests
import os
import sys
from datetime import datetime, timezone, timedelta

DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]

# CoinGecko coins (id, symbol)
CG_COINS = [
    {"id": "bitcoin",  "symbol": "BTC"},
    {"id": "ethereum", "symbol": "ETH"},
    {"id": "sui",      "symbol": "SUI"},
    {"id": "solana",   "symbol": "SOL"},
    {"id": "monero",   "symbol": "XMR"},
]

# GeckoTerminal DEX coins (network, pool_address, symbol)
GT_COINS = [
    {"network": "bsc", "pool": "0x7e58f160b5b77b8b24cd9900c09a3e730215ac47", "symbol": "ASTER"},
]


def get_prev_candle_cg(coin_id, timeframe):
    """Fetch previous completed candle OHLC from CoinGecko.
    Uses days=90 to get daily granularity candles, then picks the correct previous period."""
    if timeframe == "daily":
        # days=90 gives daily candles; data[-2] = yesterday (previous completed day)
        days = 90
    elif timeframe == "weekly":
        days = 90
    else:  # monthly
        days = 365

    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc"
    params = {"vs_currency": "usd", "days": days}
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()  # [[timestamp_ms, open, high, low, close], ...]
    if not data:
        return None

    now_utc = datetime.now(timezone.utc)

    if timeframe == "daily":
        # Get yesterday's date
        yesterday = (now_utc - timedelta(days=1)).date()
        # Find candles belonging to yesterday
        day_candles = [c for c in data
                       if datetime.fromtimestamp(c[0] / 1000, tz=timezone.utc).date() == yesterday]
        if not day_candles:
            # Fallback: use second-to-last candle
            day_candles = [data[-2]] if len(data) >= 2 else [data[-1]]
        o  = day_candles[0][1]
        h  = max(c[2] for c in day_candles)
        l  = min(c[3] for c in day_candles)
        cl = day_candles[-1][4]
        return {"open": o, "high": h, "low": l, "close": cl}

    elif timeframe == "weekly":
        # Current week starts on Monday UTC
        today = now_utc.date()
        start_of_this_week = today - timedelta(days=today.weekday())
        start_of_prev_week = start_of_this_week - timedelta(days=7)
        end_of_prev_week   = start_of_this_week - timedelta(days=1)
        prev_candles = [c for c in data
                        if start_of_prev_week
                        <= datetime.fromtimestamp(c[0] / 1000, tz=timezone.utc).date()
                        <= end_of_prev_week]
        if not prev_candles:
            # Fallback: last 7 candles before final candle
            prev_candles = data[-8:-1] if len(data) >= 8 else data[:-1]
        if not prev_candles:
            prev_candles = [data[-2]] if len(data) >= 2 else [data[-1]]
        o  = prev_candles[0][1]
        h  = max(c[2] for c in prev_candles)
        l  = min(c[3] for c in prev_candles)
        cl = prev_candles[-1][4]
        return {"open": o, "high": h, "low": l, "close": cl}

    else:  # monthly
        today = now_utc.date()
        # Previous month
        if today.month == 1:
            prev_month = 12
            prev_year  = today.year - 1
        else:
            prev_month = today.month - 1
            prev_year  = today.year
        prev_candles = [c for c in data
                        if datetime.fromtimestamp(c[0] / 1000, tz=timezone.utc).date().month == prev_month
                        and datetime.fromtimestamp(c[0] / 1000, tz=timezone.utc).date().year == prev_year]
        if not prev_candles:
            prev_candles = data[-31:-1] if len(data) >= 32 else data[:-1]
        if not prev_candles:
            prev_candles = [data[-2]] if len(data) >= 2 else [data[-1]]
        o  = prev_candles[0][1]
        h  = max(c[2] for c in prev_candles)
        l  = min(c[3] for c in prev_candles)
        cl = prev_candles[-1][4]
        return {"open": o, "high": h, "low": l, "close": cl}


def get_prev_candle_gt(network, pool, timeframe):
    """Fetch previous completed candle OHLCV from GeckoTerminal free API."""
    tf_map = {"daily": "day", "weekly": "week", "monthly": "month"}
    gt_tf  = tf_map[timeframe]
    # limit=2 fetches current + previous; index 0 = oldest (previous completed)
    url = f"https://api.geckoterminal.com/api/v2/networks/{network}/pools/{pool}/ohlcv/{gt_tf}"
    params = {"limit": 2, "currency": "usd"}
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    ohlcv_list = data["data"]["attributes"]["ohlcv_list"]
    # ohlcv_list: [[timestamp, o, h, l, c, v], ...] newest first
    # index 1 = the previous completed candle
    if len(ohlcv_list) < 2:
        candle = ohlcv_list[0]
    else:
        candle = ohlcv_list[1]
    _, o, h, l, cl, _ = candle
    return {"open": float(o), "high": float(h), "low": float(l), "close": float(cl)}


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
    valid = ("daily", "weekly", "monthly")
    if timeframe not in valid:
        raise ValueError("Unknown timeframe: " + timeframe)
    label_map = {"daily": "Daily", "weekly": "Weekly", "monthly": "Monthly"}
    label = label_map[timeframe]
    now   = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    send(f"--- {label} Pivot Targets | {now} ---")

    # CoinGecko coins
    for coin in CG_COINS:
        try:
            ohlc = get_prev_candle_cg(coin["id"], timeframe)
            if not ohlc:
                send(coin["symbol"] + ": no data")
                continue
            lv  = calculate_levels(ohlc["high"], ohlc["low"], ohlc["close"])
            msg = build_message(coin["symbol"], label, lv)
            send(msg)
            print(msg)
        except Exception as e:
            err = coin["symbol"] + ": error - " + str(e)
            print(err)
            send(err)

    # GeckoTerminal DEX coins
    for coin in GT_COINS:
        try:
            ohlc = get_prev_candle_gt(coin["network"], coin["pool"], timeframe)
            if not ohlc:
                send(coin["symbol"] + ": no data")
                continue
            lv  = calculate_levels(ohlc["high"], ohlc["low"], ohlc["close"])
            msg = build_message(coin["symbol"], label, lv)
            send(msg)
            print(msg)
        except Exception as e:
            err = coin["symbol"] + ": error - " + str(e)
            print(err)
            send(err)


if __name__ == "__main__":
    timeframe = sys.argv[1] if len(sys.argv) > 1 else "daily"
    run(timeframe)
