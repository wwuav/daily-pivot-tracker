import requests
import os
import sys
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

DISCORD_WEBHOOK_BTC = os.environ["DISCORD_WEBHOOK_BTC"]
DISCORD_WEBHOOK_ALTS = os.environ["DISCORD_WEBHOOK"]

ET = ZoneInfo("America/New_York")
SESSION_HOUR = 20  # 8pm ET daily session close/open
FIRE_TOLERANCE_MIN = 10  # only actually post within this many minutes of the real 8pm ET close

# Kraken USDT pairs -> display labels
KRAKEN_COINS = [
    {"pair": "XBTUSDT", "label": "BTC", "webhook": DISCORD_WEBHOOK_BTC},
    {"pair": "ETHUSDT", "label": "ETH", "webhook": DISCORD_WEBHOOK_ALTS},
    {"pair": "SUIUSD", "label": "SUI", "webhook": DISCORD_WEBHOOK_ALTS},
    {"pair": "SOLUSDT", "label": "SOL", "webhook": DISCORD_WEBHOOK_ALTS},
    {"pair": "XMRUSDT", "label": "XMR", "webhook": DISCORD_WEBHOOK_ALTS},
]

# DEX coins via GeckoTerminal
GT_COINS = [
    {"network": "bsc", "pool": "0x7e58f160b5b77b8b24cd9900c09a3e730215ac47", "label": "ASTER", "webhook": DISCORD_WEBHOOK_ALTS},
]

# Hyperliquid coins (HYPE native chain)
HL_COINS = [
    {"coin": "HYPE", "label": "HYPE", "webhook": DISCORD_WEBHOOK_ALTS},
]


# ---------- Session boundary math (8pm ET, DST-safe) ----------

def _daily_bounds(now_et):
    close = now_et.replace(hour=SESSION_HOUR, minute=0, second=0, microsecond=0)
    if now_et < close:
        close -= timedelta(days=1)
    start = close - timedelta(days=1)
    return start, close


def _weekly_bounds(now_et):
    # Week runs Monday 8pm ET -> Monday 8pm ET (matches previous Mon-Sun convention)
    monday = now_et - timedelta(days=now_et.weekday())
    close = monday.replace(hour=SESSION_HOUR, minute=0, second=0, microsecond=0)
    if now_et < close:
        close -= timedelta(days=7)
    start = close - timedelta(days=7)
    return start, close


def _monthly_bounds(now_et):
    close = now_et.replace(day=1, hour=SESSION_HOUR, minute=0, second=0, microsecond=0)
    if now_et < close:
        last_day_prev_month = close - timedelta(days=1)
        close = last_day_prev_month.replace(day=1, hour=SESSION_HOUR, minute=0, second=0, microsecond=0)
    last_day_prev = close - timedelta(days=1)
    start = last_day_prev.replace(day=1, hour=SESSION_HOUR, minute=0, second=0, microsecond=0)
    return start, close


def get_session_window(timeframe, now_et):
    if timeframe == "daily":
        return _daily_bounds(now_et)
    elif timeframe == "weekly":
        return _weekly_bounds(now_et)
    else:
        return _monthly_bounds(now_et)


def should_fire_now(timeframe, now_et):
    """Only post right when the relevant session candle actually closes."""
    target = now_et.replace(hour=SESSION_HOUR, minute=0, second=0, microsecond=0)
    if abs((now_et - target).total_seconds()) > FIRE_TOLERANCE_MIN * 60:
        return False
    if timeframe == "weekly" and now_et.weekday() != 0:  # Monday close
        return False
    if timeframe == "monthly" and now_et.day != 1:
        return False
    return True


# ---------- Generic hourly aggregation ----------

def aggregate_hourly(candles, start_ts, end_ts):
    """candles: list of dicts {t, o, h, l, c} (t = unix seconds, start of hour, UTC)."""
    window = sorted([c for c in candles if start_ts <= c["t"] < end_ts], key=lambda c: c["t"])
    if not window:
        return None
    return {
        "open": window[0]["o"],
        "close": window[-1]["c"],
        "high": max(c["h"] for c in window),
        "low": min(c["l"] for c in window),
    }


# ---------- Kraken ----------

def get_kraken_hourly_range(pair, start_ts, end_ts):
    url = "https://api.kraken.com/0/public/OHLC"
    since = start_ts - 3600
    out = []
    for _ in range(6):  # safety cap on pagination loops
        params = {"pair": pair, "interval": 60, "since": since}
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        body = r.json()
        if body.get("error"):
            raise Exception(f"Kraken error: {body['error']}")
        result = body.get("result", {})
        rows = next((v for k, v in result.items() if k != "last" and isinstance(v, list)), [])
        if not rows:
            break
        for row in rows:
            out.append({"t": int(row[0]), "o": float(row[1]), "h": float(row[2]), "l": float(row[3]), "c": float(row[4])})
        last_ts = int(rows[-1][0])
        if last_ts >= end_ts or len(rows) < 500:
            break
        since = last_ts
    return out


def get_kraken_closed_candle(pair, timeframe, now_et):
    start_et, end_et = get_session_window(timeframe, now_et)
    start_ts = int(start_et.astimezone(timezone.utc).timestamp())
    end_ts = int(end_et.astimezone(timezone.utc).timestamp())
    candles = get_kraken_hourly_range(pair, start_ts, end_ts)
    return aggregate_hourly(candles, start_ts, end_ts)


# ---------- GeckoTerminal ----------

def get_gt_hourly_range(network, pool, start_ts, end_ts):
    url = f"https://api.geckoterminal.com/api/v2/networks/{network}/pools/{pool}/ohlcv/hour"
    params = {"limit": 1000, "currency": "usd", "before_timestamp": end_ts + 3600}
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    rows = data.get("data", {}).get("attributes", {}).get("ohlcv_list", [])
    return [{"t": int(row[0]), "o": row[1], "h": row[2], "l": row[3], "c": row[4]} for row in rows]


def get_gt_closed_candle(network, pool, timeframe, now_et):
    start_et, end_et = get_session_window(timeframe, now_et)
    start_ts = int(start_et.astimezone(timezone.utc).timestamp())
    end_ts = int(end_et.astimezone(timezone.utc).timestamp())
    candles = get_gt_hourly_range(network, pool, start_ts, end_ts)
    return aggregate_hourly(candles, start_ts, end_ts)


# ---------- Hyperliquid ----------

def get_hl_hourly_range(coin, start_ts, end_ts):
    url = "https://api.hyperliquid.xyz/info"
    payload = {
        "type": "candleSnapshot",
        "req": {"coin": coin, "interval": "1h", "startTime": start_ts * 1000, "endTime": end_ts * 1000},
    }
    r = requests.post(url, json=payload, timeout=15)
    r.raise_for_status()
    data = r.json()
    return [{"t": int(c["t"]) // 1000, "o": float(c["o"]), "h": float(c["h"]), "l": float(c["l"]), "c": float(c["c"])} for c in data]


def get_hl_closed_candle(coin, timeframe, now_et):
    start_et, end_et = get_session_window(timeframe, now_et)
    start_ts = int(start_et.astimezone(timezone.utc).timestamp())
    end_ts = int(end_et.astimezone(timezone.utc).timestamp())
    candles = get_hl_hourly_range(coin, start_ts, end_ts)
    return aggregate_hourly(candles, start_ts, end_ts)


# ---------- Pivots / formatting (unchanged) ----------

def fmt(price):
    if price >= 1:
        return f"{price:,.2f}"
    else:
        return f"{price:,.4f}"


def calc_pivots(o, h, l, c):
    P = (h + l + c) / 3
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
            ("MP", mp(P, R1)), ("R1", R1), ("MP", mp(R1, R2)), ("R2", R2),
            ("MP", mp(R2, R3)), ("R3", R3), ("MP", mp(R3, R4)), ("R4", R4),
        ],
        "supports": [
            ("MP", mp(S1, P)), ("S1", S1), ("MP", mp(S2, S1)), ("S2", S2),
            ("MP", mp(S3, S2)), ("S3", S3), ("MP", mp(S4, S3)), ("S4", S4),
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
        lines.append(f"{name} {fmt(val)}")
    lines.append("")
    for name, val in pivots["supports"]:
        lines.append(f"{name} {fmt(val)}")

    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("Usage: python pivot_script.py [daily|weekly|monthly]")
        sys.exit(1)

    timeframe = sys.argv[1].lower()
    if timeframe not in ("daily", "weekly", "monthly"):
        print(f"Unknown timeframe: {timeframe}")
        sys.exit(1)

    now_et = datetime.now(ET)

    if not should_fire_now(timeframe, now_et):
        print(f"Skipping {timeframe}: not at an 8pm ET session close right now ({now_et.isoformat()}).")
        sys.exit(0)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    tf_label_map = {"daily": "Daily", "weekly": "Weekly", "monthly": "Monthly"}
    tf_label = tf_label_map.get(timeframe, timeframe.capitalize())
    header_msg = f"--- {tf_label} Targets | {now} ---"

    send(DISCORD_WEBHOOK_BTC, header_msg)
    send(DISCORD_WEBHOOK_ALTS, header_msg)

    for coin in KRAKEN_COINS:
        try:
            ohlc = get_kraken_closed_candle(coin["pair"], timeframe, now_et)
            if ohlc is None:
                send(coin["webhook"], f":warning: {coin['label']}: no candle data returned")
                continue
            msg = build_message(coin["label"], tf_label, ohlc)
            send(coin["webhook"], msg)
        except Exception as e:
            send(coin["webhook"], f":x: {coin['label']} error: {e}")

    for coin in GT_COINS:
        try:
            ohlc = get_gt_closed_candle(coin["network"], coin["pool"], timeframe, now_et)
            if ohlc is None:
                send(coin["webhook"], f":warning: {coin['label']}: no candle data returned")
                continue
            msg = build_message(coin["label"], tf_label, ohlc)
            send(coin["webhook"], msg)
        except Exception as e:
            send(coin["webhook"], f":x: {coin['label']} error: {e}")

    for coin in HL_COINS:
        try:
            ohlc = get_hl_closed_candle(coin["coin"], timeframe, now_et)
            if ohlc is None:
                send(coin["webhook"], f":warning: {coin['label']}: no candle data returned")
                continue
            msg = build_message(coin["label"], tf_label, ohlc)
            send(coin["webhook"], msg)
        except Exception as e:
            send(coin["webhook"], f":x: {coin['label']} error: {e}")


if __name__ == "__main__":
    main()
