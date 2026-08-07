#!/usr/bin/env python3
"""
RSI band-cross alerter for Delta Exchange.

Fires when RSI(14) on closed 4H candles crosses ABOVE the upper band (60)
or BELOW the lower band (35). Read-only: uses the public candles endpoint
and never touches your account or places orders.

Usage:
    python3 rsi_alert.py --once      # one check, for cron
    python3 rsi_alert.py --watch     # loop, wakes just after each 4H close
    python3 rsi_alert.py --backtest  # list historical crosses, no alerts sent
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from delta_client import DeltaClient, _resolution_seconds, load_env

STATE = Path(__file__).parent / "rsi_alert.state.json"


# ---------------- RSI (Wilder smoothing — matches TradingView's ta.rsi) ----------------
def wilder_rsi(closes, length=14):
    if len(closes) < length + 1:
        raise ValueError(f"need >{length} closes, got {len(closes)}")

    gains, losses = [], []
    for prev, cur in zip(closes, closes[1:]):
        d = cur - prev
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))

    avg_gain = sum(gains[:length]) / length
    avg_loss = sum(losses[:length]) / length

    out = [None] * length  # RSI undefined for the first `length` bars
    for i in range(length, len(gains) + 1):
        if i > length:
            avg_gain = (avg_gain * (length - 1) + gains[i - 1]) / length
            avg_loss = (avg_loss * (length - 1) + losses[i - 1]) / length
        if avg_loss == 0:
            out.append(100.0)
        elif avg_gain == 0:
            out.append(0.0)
        else:
            rs = avg_gain / avg_loss
            out.append(100.0 - 100.0 / (1.0 + rs))
    # out is aligned 1:1 with `closes`; the averages are the running state
    # after the final close, which is what target-price inversion needs.
    return out, avg_gain, avg_loss


def rsi_target_price(last_close, avg_gain, avg_loss, target, length=14):
    """
    Invert Wilder RSI: what close price makes the NEXT bar print exactly `target`?

    RSI is monotonic in the next close, so this is exact, not an approximation.
    Returns None when the target is unreachable in that direction on one bar
    (e.g. asking for the RSI-35 level while RSI is already climbing).
    """
    if not 0 < target < 100:
        return None
    rs_t = target / (100.0 - target)
    n1 = length - 1
    g, l = avg_gain * n1, avg_loss * n1

    up = rs_t * l - g          # price must RISE by this to hit target
    if up > 0:
        return last_close + up

    down = (g / rs_t) - l if rs_t > 0 else None   # price must FALL by this
    if down is not None and down > 0:
        return last_close - down
    return None


# ---------------- notifications ----------------
def notify(title, message, cfg):
    print(f"\n*** {title}\n    {message}\n", flush=True)

    if cfg["macos"] and sys.platform == "darwin":
        safe_m = message.replace('"', "'")
        safe_t = title.replace('"', "'")
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{safe_m}" with title "{safe_t}" sound name "Glass"'],
            check=False, capture_output=True)

    if cfg["tg_token"] and cfg["tg_chat"]:
        try:
            data = urllib.parse.urlencode({
                "chat_id": cfg["tg_chat"],
                "text": f"*{title}*\n{message}",
                "parse_mode": "Markdown",
            }).encode()
            urllib.request.urlopen(
                f"https://api.telegram.org/bot{cfg['tg_token']}/sendMessage",
                data=data, timeout=15).read()
        except Exception as e:
            print(f"    [telegram failed: {e}]", flush=True)

    if cfg["ntfy"]:
        try:
            req = urllib.request.Request(
                f"https://ntfy.sh/{cfg['ntfy']}", data=message.encode(), method="POST")
            req.add_header("Title", title)
            urllib.request.urlopen(req, timeout=15).read()
        except Exception as e:
            print(f"    [ntfy failed: {e}]", flush=True)


# ---------------- core ----------------
def closed_candles(client, symbol, resolution, count=300):
    """Candles oldest-first with the still-forming bucket removed."""
    secs = _resolution_seconds(resolution)
    current_bucket = int(time.time()) // secs * secs
    return [c for c in client.candles(symbol, resolution, count)
            if c["time"] < current_bucket]


def targets(cfg, client):
    """Price levels that would trigger each band on the NEXT closed bar.

    Punch these into Delta's own price-alert UI to get a push from the Delta app.
    They must be refreshed every bar — see DELTA_SETUP_STEPS.md.
    """
    candles = closed_candles(client, cfg["symbol"], cfg["resolution"])
    closes = [float(c["close"]) for c in candles]
    rsi, ag, al = wilder_rsi(closes, cfg["length"])
    last = closes[-1]

    up = rsi_target_price(last, ag, al, cfg["upper"], cfg["length"])
    dn = rsi_target_price(last, ag, al, cfg["lower"], cfg["length"])

    secs = _resolution_seconds(cfg["resolution"])
    nxt = datetime.fromtimestamp((int(time.time()) // secs + 1) * secs, timezone.utc)

    print(f"\n{cfg['symbol']} {cfg['resolution']} — RSI now {rsi[-1]:.2f}, last close {last:g}")
    print(f"Levels for the bar closing {nxt:%Y-%m-%d %H:%M UTC}:\n")
    if up:
        print(f"  RSI {cfg['upper']:g}  <-  close at/above  {up:,.1f}"
              f"   ({(up / last - 1) * 100:+.2f}%)")
    else:
        print(f"  RSI {cfg['upper']:g}  <-  unreachable on a single bar")
    if dn:
        print(f"  RSI {cfg['lower']:g}  <-  close at/below  {dn:,.1f}"
              f"   ({(dn / last - 1) * 100:+.2f}%)")
    else:
        print(f"  RSI {cfg['lower']:g}  <-  unreachable on a single bar")
    print("\n  Valid for ONE bar only. Re-run after each close.\n")
    return up, dn


def check(cfg, client, send=True):
    candles = closed_candles(client, cfg["symbol"], cfg["resolution"])
    closes = [float(c["close"]) for c in candles]
    rsi, _ag, _al = wilder_rsi(closes, cfg["length"])

    prev, cur = rsi[-2], rsi[-1]
    bar = candles[-1]
    bar_ts = bar["time"]
    when = datetime.fromtimestamp(bar_ts, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    print(f"[{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S UTC}] "
          f"{cfg['symbol']} {cfg['resolution']} | bar {when} | "
          f"close {bar['close']} | RSI {prev:.2f} -> {cur:.2f}", flush=True)

    event = None
    if prev <= cfg["upper"] < cur:
        event = ("rsi_cross_up",
                 f"RSI crossed ABOVE {cfg['upper']:g}",
                 f"{cfg['symbol']} {cfg['resolution']}\nRSI {prev:.2f} -> {cur:.2f}\n"
                 f"Close {bar['close']}\nBar {when}")
    elif prev >= cfg["lower"] > cur:
        event = ("rsi_cross_down",
                 f"RSI crossed BELOW {cfg['lower']:g}",
                 f"{cfg['symbol']} {cfg['resolution']}\nRSI {prev:.2f} -> {cur:.2f}\n"
                 f"Close {bar['close']}\nBar {when}")

    if not event:
        return None

    kind, title, body = event

    # Dedupe: never alert twice for the same closed bar (survives restarts).
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    skey = f"{cfg['symbol']}:{cfg['resolution']}"
    if state.get(skey, {}).get("bar_time") == bar_ts:
        print("    (already alerted for this bar — suppressed)", flush=True)
        return None

    if send:
        notify(title, body, cfg)
        state[skey] = {"bar_time": bar_ts, "event": kind, "rsi": round(cur, 2)}
        STATE.write_text(json.dumps(state, indent=2))
    return kind


def backtest(cfg, client, bars=300):
    candles = closed_candles(client, cfg["symbol"], cfg["resolution"], bars)
    closes = [float(c["close"]) for c in candles]
    rsi, _ag, _al = wilder_rsi(closes, cfg["length"])

    print(f"\nHistorical crosses — {cfg['symbol']} {cfg['resolution']}, "
          f"{len(candles)} closed bars, bands {cfg['lower']:g}/{cfg['upper']:g}\n")
    n_up = n_dn = 0
    for i in range(1, len(rsi)):
        p, c = rsi[i - 1], rsi[i]
        if p is None or c is None:
            continue
        when = datetime.fromtimestamp(candles[i]["time"], timezone.utc).strftime("%Y-%m-%d %H:%M")
        if p <= cfg["upper"] < c:
            n_up += 1
            print(f"  {when} UTC   UP   {p:6.2f} -> {c:6.2f}   close {candles[i]['close']}")
        elif p >= cfg["lower"] > c:
            n_dn += 1
            print(f"  {when} UTC   DOWN {p:6.2f} -> {c:6.2f}   close {candles[i]['close']}")

    span_days = len(candles) * _resolution_seconds(cfg["resolution"]) / 86400
    print(f"\n  {n_up} up-crosses, {n_dn} down-crosses over ~{span_days:.0f} days "
          f"({(n_up + n_dn) / max(span_days, 1) * 30:.1f} signals/month)\n")


def load_cfg():
    load_env()
    return {
        "symbol": os.environ.get("SYMBOL", "BTCUSD"),
        "resolution": os.environ.get("RESOLUTION", "4h"),
        "length": int(os.environ.get("RSI_LENGTH", 14)),
        "upper": float(os.environ.get("UPPER_BAND", 60)),
        "lower": float(os.environ.get("LOWER_BAND", 35)),
        "macos": os.environ.get("MACOS_NOTIFY", "1") == "1",
        "tg_token": os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
        "tg_chat": os.environ.get("TELEGRAM_CHAT_ID", "").strip(),
        "ntfy": os.environ.get("NTFY_TOPIC", "").strip(),
    }


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--once", action="store_true", help="single check (for cron)")
    g.add_argument("--watch", action="store_true", help="loop, wake after each bar close")
    g.add_argument("--backtest", action="store_true", help="list historical crosses")
    g.add_argument("--targets", action="store_true",
                   help="print the price levels that trigger each band next bar")
    ap.add_argument("--symbol", help="override SYMBOL")
    args = ap.parse_args()

    cfg = load_cfg()
    if args.symbol:
        cfg["symbol"] = args.symbol
    client = DeltaClient()

    if args.backtest:
        backtest(cfg, client)
    elif args.targets:
        targets(cfg, client)
    elif args.once:
        check(cfg, client)
    else:
        secs = _resolution_seconds(cfg["resolution"])
        print(f"Watching {cfg['symbol']} {cfg['resolution']} "
              f"RSI({cfg['length']}) bands {cfg['lower']:g}/{cfg['upper']:g}. Ctrl-C to stop.",
              flush=True)
        while True:
            try:
                check(cfg, client)
            except Exception as e:
                print(f"    [check failed: {e}]", flush=True)
            now = int(time.time())
            sleep_for = (now // secs + 1) * secs + 30 - now  # 30s past next close
            nxt = datetime.fromtimestamp(now + sleep_for, timezone.utc)
            print(f"    next check {nxt:%H:%M:%S UTC} ({sleep_for // 60}m)", flush=True)
            time.sleep(sleep_for)


if __name__ == "__main__":
    main()
