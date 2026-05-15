import requests
import os
import sys
from datetime import datetime, timezone, timedelta

DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]

# CoinGecko coin IDs -> display labels (all priced in USDT via vs_currency=usd)
CG_COINS = [
    {"id": "bitcoin",  "label": "BTC"},
    {"id": "ethereum", "label": "ETH"},
    {"id": "sui",      "label": "SUI"},
    {"id": "solana",   "label": "SOL"},h
    {"id": "monero",   "label": "XMR"},
]

# DEX coins via GeckoTerminal (not on CoinGecko OHLC)
GT_COINS = [
    {"network": "bsc", "pool": "0x7e58f160b5b77b8b24cd9900c09a3e730215ac47", "label": "ASTER"},
]


def get_cg_ohlc(coin_id, days):
    """Fetch CoinGecko OHLC candles. Returns list of [ts_ms, o, h, l, c]."""
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc"
    params = {"vs_currency": "usd", "days": days}
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def get_cg_closed_candle(coin_id, timeframe):
    """Return the just-closed candle's OHLC as a dict.

    CoinGecko OHLC granularity by days param:
      days=1   -> 30-min candles (~48 points)
      days=7   -> 4-hour candles  (~42 points)
      days=14  -> 4-hour candles  (~84 points)
      days=90  -> daily candles   (~90 points)
      days=365 -> daily candles   (~365 points)

    Strategy per timeframe:
      daily   -> fetch days=90 (daily candles), use data[-1]
                 (at 00:05 UTC the last daily candle IS yesterday's closed candle)
      weekly  -> fetch days=90 (daily candles), aggregate the 7 days that
                 form the just-closed week (Mon–Sun UTC), use data[-1] if needed
      monthly -> fetch days=365 (daily candles), aggregate the just-closed month
    """
    now_utc = datetime.now(timezone.utc)

    if timeframe == "daily":
        data = get_cg_ohlc(coin_id, 90)
        if not data:
            return None
        # data[-1] = last daily candle = yesterday (we run right after midnight UTC)
        candle = data[-1]
        return {"open": candle[1], "high": candle[2], "low": candle[3], "close": candle[4]}

    elif timeframe == "weekly":
        data = get_cg_ohlc(coin_id, 90)
        if not data:
            return None
        # Find the just-closed week: Monday–Sunday that ended before today
        today = now_utc.date()
        # Monday of the current week
        start_of_this_week = today - timedelta(days=today.weekday())
        # The closed week ran Mon to Sun last week
        end_of_last_week   = start_of_this_week - timedelta(days=1)
        start_of_last_week = start_of_this_week - timedelta(days=7)

        week_candles = [
            c for c in data
            if start_of_last_week
            <= datetime.fromtimestamp(c[0] / 1000, tz=timezone.utc).date()
            <= end_of_last_week
        ]
        if not week_candles:
            # Fallback: take last 7 daily candles before the most recent
            week_candles = data[-8:-1] if len(data) >= 8 else data[:-1]
        if not week_candles:
            week_candles = [data[-1]]

        o  = week_candles[0][1]
        h  = max(c[2] for c in week_candles)
        l  = min(c[3] for c in week_candles)
        cl = week_candles[-1][4]
        return {"open": o, "high": h, "low": l, "close": cl}

    else:  # monthly
        data = get_cg_ohlc(coin_id, 365)
        if not data:
            return None
        today = now_utc.date()
        # Previous month
        if today.month == 1:
            prev_month, prev_year = 12, today.year - 1
        else:
            prev_month, prev_year = today.month - 1, today.year

        month_candles = [
            c for c in data
            if (
                datetime.fromtimestamp(c[0] / 1000, tz=timezone.utc).date().month == prev_month
                and
                datetime.fromtimestamp(c[0] / 1000, tz=timezone.utc).date().year  == prev_year
            )
        ]
        if not month_candles:
            month_candles = data[-32:-1] if len(data) >= 32 else data[:-1]
        if not month_candles:
            month_candles = [data[-1]]

        o  = month_candles[0][1]
        h  = max(c[2] for c in month_candles)
        l  = min(c[3] for c in month_candles)
        cl = month_candles[-1][4]
        return {"open": o, "high": h, "low": l, "close": cl}


def get_gt_closed_candle(network, pool, timeframe):
    """GeckoTerminal: newest-first, [0]=forming, [1]=just-closed."""
    tf_map = {"daily": "day", "weekly": "week", "monthly": "month"}
    url = (
        f"https://api.geckoterminal.com/api/v2/networks/{network}"
        f"/pools/{pool}/ohlcv/{tf_map[timeframe]}"
    )
    params = {"limit": 2, "currency": "usd"}
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    ohlcv_list = r.json()["data"]["attributes"]["ohlcv_list"]
    c = ohlcv_list[1] if len(ohlcv_list) >= 2 else ohlcv_list[0]
    return {"open": float(c[1]), "high": float(c[2]), "low": float(c[3]), "close": float(c[4])}


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
    send(f"--- {tf_label} Targets | {now} ---")

    for coin in CG_COINS:
        try:
            ohlc = get_cg_closed_candle(coin["id"], timeframe)
            if not ohlc:
                send(coin["label"] + ": no data")
                continue
            lv  = calculate_levels(ohlc["high"], ohlc["low"], ohlc["close"])
            msg = build_message(coin["label"], tf_label, lv)
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
