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
    {"id": "solana",   "label": "SOL"},
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
    """Return the just-closed candle's OHLC as a dict."""
    now_utc = datetime.now(timezone.utc)

    if timeframe == "daily":
        data = get_cg_ohlc(coin_id, 90)
        if not data:
            return None
        candle = data[-1]
        return {"open": candle[1], "high": candle[2], "low": candle[3], "close": candle[4]}

    elif timeframe == "weekly":
        data = get_cg_ohlc(coin_id, 90)
        if not data:
            return None
        today = now_utc.date()
        start_of_this_week = today - timedelta(days=today.weekday())
        end_of_last_week   = start_of_this_week - timedelta(days=1)
        start_of_last_week = start_of_this_week - timedelta(days=7)

        week_candles = [
            c for c in data
            if start_of_last_week
               <= datetime.fromtimestamp(c[0] / 1000, tz=timezone.utc).date()
               <= end_of_last_week
        ]
        if not week_candles:
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


def get_gt_daily_candles(network, pool, limit=90):
    """Fetch daily OHLCV candles from GeckoTerminal. Returns list newest-first."""
    url = f"https://api.geckoterminal.com/api/v2/networks/{network}/pools/{pool}/ohlcv/day"
    params = {"limit": limit, "currency": "usd"}
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    return data.get("data", {}).get("attributes", {}).get("ohlcv_list", [])


def get_gt_closed_candle(network, pool, timeframe):
    """Return the just-closed candle from GeckoTerminal for a DEX pool.
    Always uses daily candles and aggregates for weekly/monthly.
    GeckoTerminal daily: newest-first, each entry = [ts, o, h, l, c, v]
    """
    now_utc = datetime.now(timezone.utc)

    if timeframe == "daily":
        candles = get_gt_daily_candles(network, pool, limit=2)
        if len(candles) < 2:
            return None
        c = candles[1]  # [0]=forming, [1]=just closed
        return {"open": c[1], "high": c[2], "low": c[3], "close": c[4]}

    elif timeframe == "weekly":
        candles = get_gt_daily_candles(network, pool, limit=90)
        if not candles:
            return None
        today = now_utc.date()
        start_of_this_week = today - timedelta(days=today.weekday())
        end_of_last_week   = start_of_this_week - timedelta(days=1)
        start_of_last_week = start_of_this_week - timedelta(days=7)

        week_candles = [
            c for c in candles
            if start_of_last_week
               <= datetime.fromtimestamp(c[0], tz=timezone.utc).date()
               <= end_of_last_week
        ]
        if not week_candles:
            week_candles = candles[1:8] if len(candles) >= 8 else candles[1:]
        if not week_candles:
            week_candles = [candles[0]]

        # candles are newest-first so [-1] is oldest open, [0] is newest close
        o  = week_candles[-1][1]
        h  = max(c[2] for c in week_candles)
        l  = min(c[3] for c in week_candles)
        cl = week_candles[0][4]
        return {"open": o, "high": h, "low": l, "close": cl}

    else:  # monthly
        candles = get_gt_daily_candles(network, pool, limit=365)
        if not candles:
            return None
        today = now_utc.date()
        if today.month == 1:
            prev_month, prev_year = 12, today.year - 1
        else:
            prev_month, prev_year = today.month - 1, today.year

        month_candles = [
            c for c in candles
            if (
                datetime.fromtimestamp(c[0], tz=timezone.utc).date().month == prev_month
                and
                datetime.fromtimestamp(c[0], tz=timezone.utc).date().year  == prev_year
            )
        ]
        if not month_candles:
            month_candles = candles[1:32] if len(candles) >= 32 else candles[1:]
        if not month_candles:
            month_candles = [candles[0]]

        o  = month_candles[-1][1]
        h  = max(c[2] for c in month_candles)
        l  = min(c[3] for c in month_candles)
        cl = month_candles[0][4]
        return {"open": o, "high": h, "low": l, "close": cl}


def fmt(price):
    """Format price: no decimals >=100, 2dp >=1, 4dp <1."""
    if price >= 100:
        return f"{price:,.0f}"
    elif price >= 1:
        return f"{price:,.2f}"
    else:
        return f"{price:,.4f}"


def calc_pivots(o, h, l, c):
    """Classic pivot point calculation."""
    P  = (h + l + c) / 3
    S1 = 2 * P - h
    S2 = P - (h - l)
    S3 = S2 - (h - l)
    S4 = S3 - (h - l)
    R1 = 2 * P - l
    R2 = P + (h - l)
    R3 = R2 + (h - l)
    R4 = R3 + (h - l)

    def mp(a, b):
        return (a + b) / 2

    return {
        "P": P,
        "resistances": [
            ("MP", mp(P,  R1)),
            ("R1", R1),
            ("MP", mp(R1, R2)),
            ("R2", R2),
            ("MP", mp(R2, R3)),
            ("R3", R3),
            ("MP", mp(R3, R4)),
            ("R4", R4),
        ],
        "supports": [
            ("MP", mp(S1, P)),
            ("S1", S1),
            ("MP", mp(S2, S1)),
            ("S2", S2),
            ("MP", mp(S3, S2)),
            ("S3", S3),
            ("MP", mp(S4, S3)),
            ("S4", S4),
        ],
    }


def send(msg):
    """Post a message to Discord via webhook."""
    resp = requests.post(DISCORD_WEBHOOK, json={"content": msg}, timeout=10)
    resp.raise_for_status()


def build_message(label, tf_label, ohlc):
    """Build the Discord message for one coin."""
    o, h, l, c = ohlc["open"], ohlc["high"], ohlc["low"], ohlc["close"]
    pivots = calc_pivots(o, h, l, c)

    header = f"{label} {tf_label} Target is {fmt(pivots['P'])}"

    res_lines = "\n".join(f"{lbl:<4}  {fmt(price)}" for lbl, price in pivots["resistances"])
    sup_lines = "\n".join(f"{lbl:<4}  {fmt(price)}" for lbl, price in pivots["supports"])

    return header + "\n\n" + res_lines + "\n\n" + sup_lines


def run(timeframe):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    tf_label_map = {"daily": "Daily", "weekly": "Weekly", "monthly": "Monthly"}
    tf_label = tf_label_map.get(timeframe, timeframe.capitalize())

    send(f"--- {tf_label} Targets | {now} ---")

    for coin in CG_COINS:
        try:
            ohlc = get_cg_closed_candle(coin["id"], timeframe)
            if ohlc is None:
                send(f":warning: {coin['label']}: no candle data returned")
                continue
            msg = build_message(coin["label"], tf_label, ohlc)
            send(msg)
        except Exception as e:
            send(f":x: {coin['label']} error: {e}")

    for coin in GT_COINS:
        try:
            ohlc = get_gt_closed_candle(coin["network"], coin["pool"], timeframe)
            if ohlc is None:
                send(f":warning: {coin['label']}: no candle data returned")
                continue
            msg = build_message(coin["label"], tf_label, ohlc)
            send(msg)
        except Exception as e:
            send(f":x: {coin['label']} error: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("daily", "weekly", "monthly"):
        print("Usage: python pivot_script.py [daily|weekly|monthly]")
        sys.exit(1)
    run(sys.argv[1])
