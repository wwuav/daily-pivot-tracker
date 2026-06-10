import requests
import os
import sys
from datetime import datetime, timezone, timedelta

DISCORD_WEBHOOK_BTC  = os.environ["DISCORD_WEBHOOK_BTC"]
DISCORD_WEBHOOK_ALTS = os.environ["DISCORD_WEBHOOK"]

# Kraken USDT pairs -> display labels
KRAKEN_COINS = [
    {"pair": "XBTUSDT",  "label": "BTC", "webhook": DISCORD_WEBHOOK_BTC},
    {"pair": "ETHUSDT",  "label": "ETH", "webhook": DISCORD_WEBHOOK_ALTS},
    {"pair": "SUIUSD",  "label": "SUI", "webhook": DISCORD_WEBHOOK_ALTS},
    {"pair": "SOLUSDT",  "label": "SOL", "webhook": DISCORD_WEBHOOK_ALTS},
    {"pair": "XMRUSDT",  "label": "XMR", "webhook": DISCORD_WEBHOOK_ALTS},
]

# DEX coins via GeckoTerminal
GT_COINS = [
    {"network": "bsc", "pool": "0x7e58f160b5b77b8b24cd9900c09a3e730215ac47", "label": "ASTER", "webhook": DISCORD_WEBHOOK_ALTS},
]

# Hyperliquid coins (HYPE native chain)
HL_COINS = [
        {"coin": "HYPE", "label": "HYPE", "webhook": DISCORD_WEBHOOK_ALTS},
]


def get_kraken_ohlc(pair, interval=1440):
    """Fetch OHLC from Kraken for given interval (minutes). Returns list of [ts, o, h, l, c, vwap, vol, cnt]."""
    url = "https://api.kraken.com/0/public/OHLC"
    params = {"pair": pair, "interval": interval}
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    body = r.json()
    if body.get("error"):
        raise Exception(f"Kraken error: {body['error']}")
    result = body.get("result", {})
    for k, v in result.items():
        if k == "last":
            continue
        if isinstance(v, list):
            return v
    return []


def get_kraken_closed_candle(pair, timeframe):
    now_utc = datetime.now(timezone.utc)
    rows = get_kraken_ohlc(pair)
    if not rows or len(rows) < 2:
        return None

    if timeframe == "daily":
        # Kraken returns oldest-first; rows[-2] is the fully closed candle,
        # rows[-1] is the currently-open (incomplete) candle.
        row = rows[-2]
        return {
            "open":  float(row[1]),
            "high":  float(row[2]),
            "low":   float(row[3]),
            "close": float(row[4]),
        }

    elif timeframe == "weekly":
        # Use Kraken's native weekly candles (interval=10080 min) for accuracy
        rows_weekly = get_kraken_ohlc(pair, 10080)
        if not rows_weekly or len(rows_weekly) < 2:
            return None
        # rows_weekly[-2] = last fully closed weekly candle
        row = rows_weekly[-2]
        return {
            "open":  float(row[1]),
            "high":  float(row[2]),
            "low":   float(row[3]),
            "close": float(row[4]),
        }

    else:  # monthly
        today = now_utc.date()
        if today.month == 1:
            prev_month, prev_year = 12, today.year - 1
        else:
            prev_month, prev_year = today.month - 1, today.year

        month_rows = [
            r for r in rows
            if (
                datetime.fromtimestamp(int(r[0]), tz=timezone.utc).date().month == prev_month
                and
                datetime.fromtimestamp(int(r[0]), tz=timezone.utc).date().year  == prev_year
            )
        ]
        if not month_rows:
            return None
        o  = float(month_rows[0][1])
        h  = max(float(r[2]) for r in month_rows)
        l  = min(float(r[3]) for r in month_rows)
        cl = float(month_rows[-1][4])
        return {"open": o, "high": h, "low": l, "close": cl}


def get_gt_daily_candles(network, pool, limit=90):
    url = f"https://api.geckoterminal.com/api/v2/networks/{network}/pools/{pool}/ohlcv/day"
    params = {"limit": limit, "currency": "usd"}
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    return data.get("data", {}).get("attributes", {}).get("ohlcv_list", [])


def get_gt_closed_candle(network, pool, timeframe):
    now_utc = datetime.now(timezone.utc)

    if timeframe == "daily":
        candles = get_gt_daily_candles(network, pool, limit=3)
        if not candles:
            return None
        # GeckoTerminal returns newest-first.
        # candles[0] = current open candle (today), candles[1] = last closed candle.
        c = candles[1]
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
            if (
                start_of_last_week
                <= datetime.fromtimestamp(c[0], tz=timezone.utc).date()
                <= end_of_last_week
            )
        ]
        if not week_candles:
            return None
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
            month_candles = [candles[1]]

        o  = month_candles[-1][1]
        h  = max(c[2] for c in month_candles)
        l  = min(c[3] for c in month_candles)
        cl = month_candles[0][4]
        return {"open": o, "high": h, "low": l, "close": cl}



def get_hl_candles(coin, interval="1d", lookback_days=5):
        """Fetch OHLC candles from Hyperliquid. Returns list newest-first."""
        url = "https://api.hyperliquid.xyz/info"
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        start_ms = now_ms - lookback_days * 86400 * 1000
        payload = {
                    "type": "candleSnapshot",
                    "req": {"coin": coin, "interval": interval, "startTime": start_ms, "endTime": now_ms},
        }
        r = requests.post(url, json=payload, timeout=15)
        r.raise_for_status()
        data = r.json()
        return list(reversed(data))  # newest-first


def get_hl_closed_candle(coin, timeframe):
    if timeframe == "daily":
        candles = get_hl_candles(coin, "1d", lookback_days=5)
        if not candles or len(candles) < 2:
            return None
        c = candles[1]  # candles[0]=open today, candles[1]=last closed
        return {"open": float(c["o"]), "high": float(c["h"]), "low": float(c["l"]), "close": float(c["c"])}

    elif timeframe == "weekly":
        candles = get_hl_candles(coin, "1d", lookback_days=20)
        if not candles:
            return None
        now_utc = datetime.now(timezone.utc)
        today = now_utc.date()
        start_of_this_week = today - timedelta(days=today.weekday())
        end_of_last_week   = start_of_this_week - timedelta(days=1)
        start_of_last_week = start_of_this_week - timedelta(days=7)
        week_candles = [
            c for c in candles
            if (
                start_of_last_week
                <= datetime.fromtimestamp(c["t"] / 1000, tz=timezone.utc).date()
                <= end_of_last_week
            )
        ]
        if not week_candles:
            return None
        o  = float(week_candles[-1]["o"])
        h  = max(float(c["h"]) for c in week_candles)
        l  = min(float(c["l"]) for c in week_candles)
        cl = float(week_candles[0]["c"])
        return {"open": o, "high": h, "low": l, "close": cl}

    else:  # monthly
        candles = get_hl_candles(coin, "1d", lookback_days=65)
        if not candles:
            return None
        now_utc = datetime.now(timezone.utc)
        today = now_utc.date()
        if today.month == 1:
            prev_month, prev_year = 12, today.year - 1
        else:
            prev_month, prev_year = today.month - 1, today.year
        month_candles = [
            c for c in candles
            if (
                datetime.fromtimestamp(c["t"] / 1000, tz=timezone.utc).date().month == prev_month
                and
                datetime.fromtimestamp(c["t"] / 1000, tz=timezone.utc).date().year == prev_year
            )
        ]
        if not month_candles:
            return None
        o  = float(month_candles[-1]["o"])
        h  = max(float(c["h"]) for c in month_candles)
        l  = min(float(c["l"]) for c in month_candles)
        cl = float(month_candles[0]["c"])
        return {"open": o, "high": h, "low": l, "close": cl}
def fmt(price):
    if price >= 1:
        return f"{price:,.2f}"
    else:
        return f"{price:,.4f}"


def calc_pivots(o, h, l, c):
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
            ("MP", mp(P, R1)),
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


def send(webhook, msg):
    resp = requests.post(webhook, json={"content": msg}, timeout=10)
    resp.raise_for_status()


def build_message(label, tf_label, ohlc):
    o, h, l, c = ohlc["open"], ohlc["high"], ohlc["low"], ohlc["close"]
    pivots = calc_pivots(o, h, l, c)
    P = pivots["P"]

    lines = [f"{label} {tf_label} Target is {fmt(P)}", ""]
    for name, val in pivots["resistances"]:
        lines.append(f"{name}    {fmt(val)}")
    lines.append("")
    for name, val in pivots["supports"]:
        lines.append(f"{name}    {fmt(val)}")

    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("Usage: python pivot_script.py [daily|weekly|monthly]")
        sys.exit(1)

    timeframe = sys.argv[1].lower()
    if timeframe not in ("daily", "weekly", "monthly"):
        print(f"Unknown timeframe: {timeframe}")
        sys.exit(1)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    tf_label_map = {"daily": "Daily", "weekly": "Weekly", "monthly": "Monthly"}
    tf_label = tf_label_map.get(timeframe, timeframe.capitalize())
    header_msg = f"--- {tf_label} Targets | {now} ---"

    send(DISCORD_WEBHOOK_BTC,  header_msg)
    send(DISCORD_WEBHOOK_ALTS, header_msg)

    for coin in KRAKEN_COINS:
        try:
            ohlc = get_kraken_closed_candle(coin["pair"], timeframe)
            if ohlc is None:
                send(coin["webhook"], f":warning: {coin['label']}: no candle data returned")
                continue
            msg = build_message(coin["label"], tf_label, ohlc)
            send(coin["webhook"], msg)
        except Exception as e:
            send(coin["webhook"], f":x: {coin['label']} error: {e}")

    for coin in GT_COINS:
        try:
            ohlc = get_gt_closed_candle(coin["network"], coin["pool"], timeframe)
            if ohlc is None:
                send(coin["webhook"], f":warning: {coin['label']}: no candle data returned")
                continue
            msg = build_message(coin["label"], tf_label, ohlc)
            send(coin["webhook"], msg)
        except Exception as e:
            send(coin["webhook"], f":x: {coin['label']} error: {e}")


    for coin in HL_COINS:
        try:
            ohlc = get_hl_closed_candle(coin["coin"], timeframe)
            if ohlc is None:
                send(coin["webhook"], f":warning: {coin['label']}: no candle data returned")
                continue
            msg = build_message(coin["label"], tf_label, ohlc)
            send(coin["webhook"], msg)
        except Exception as e:
            send(coin["webhook"], f":x: {coin['label']} error: {e}")


if __name__ == "__main__":
    main()
