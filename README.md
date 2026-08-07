# Delta Exchange RSI 60/35 Alerter

Alerts when RSI(14) on **closed 4H candles** crosses **above 60** or **below 35**.

Two independent implementations — use either or both:

| File | Runs on | Needs API keys? |
|---|---|---|
| `rsi_band_alert.pine` | TradingView (Pine Editor) | No |
| `rsi_alert.py` | Your machine / a VPS, off Delta's own candles | **No** |

Delta Exchange's chart is a TradingView *widget* and cannot load custom Pine Script —
see `IMPLEMENTATION_PLAN.md`. The Python path is what actually works against Delta data.

## Quick start

No dependencies — Python 3.9+ standard library only.

```bash
python3 rsi_alert.py --backtest   # list historical crosses, sends nothing
python3 rsi_alert.py --once       # one check (use from cron)
python3 rsi_alert.py --watch      # loop, wakes 30s after each 4H close
python3 rsi_alert.py --targets    # price levels that hit RSI 60/35 next bar
python3 rsi_alert.py --once --symbol ETHUSD
```

`--targets` exists for one purpose: Delta's app can only alert on **price**, never on
an indicator. It converts the RSI band into the exact close price that would trigger it,
so you can enter that into Delta's own price-alert screen. See `DELTA_SETUP_STEPS.md`
for why that route is manual-only.

Tune everything in `.env`: `SYMBOL`, `RESOLUTION`, `RSI_LENGTH`, `UPPER_BAND`, `LOWER_BAND`.

## Notifications

- **macOS Notification Center** — on by default (`MACOS_NOTIFY=1`).
- **Telegram** — set `TELEGRAM_BOT_TOKEN` (from `@BotFather`) and `TELEGRAM_CHAT_ID`
  (from `@userinfobot`). Best option if you want alerts on your phone.
- **ntfy.sh** — set `NTFY_TOPIC` to any hard-to-guess string, subscribe in the ntfy app.
  No account needed; note the topic is public to anyone who guesses it.

## Deployed: GitHub Actions (live)

Runs automatically in the cloud — your Mac can be asleep or off.

- Repo: `abhi-revwise/delta-rsi-alert` (**private**)
- Workflow: `.github/workflows/rsi-alert.yml`
- Schedule: `5 0,4,8,12,16,20 * * *` (UTC) — 5 min after each 4H close
- Delivery: ntfy, topic stored as the repo secret `NTFY_TOPIC`
- Dedupe: `rsi_alert.state.json` persisted between runs via `actions/cache`
- **No Delta API keys are used.** Candles are a public endpoint.

Tune the bands without touching code — set repo *variables* (not secrets):

```bash
gh variable set UPPER_BAND --body 70     # e.g. switch to classic overbought
gh variable set LOWER_BAND --body 30
gh variable set SYMBOL     --body ETHUSD
```

Useful commands:

```bash
gh workflow run "RSI 4H band alert"   # fire a check right now
gh run list --limit 5                 # recent runs
gh run view --log                     # output of the last run
```

Caveat: GitHub's scheduled triggers are best-effort — runs can be delayed
several minutes under load, and on rare occasions skipped. Fine for a 4H
signal, not for anything latency-sensitive.

## Run it unattended (local alternative)

`--watch` dies with your terminal. For a durable setup, cron every 4H just after close:

```
5 0,4,8,12,16,20 * * * cd "/Users/abhinavchamoli/delta exchange pine" && /usr/bin/python3 rsi_alert.py --once >> rsi.log 2>&1
```

Those hours are UTC-aligned candle closes; adjust if your machine's clock is local time
(IST = UTC+5:30, so use `35 5,9,13,17,21,1`). Your Mac must be awake — for real reliability
put this on a small VPS. `rsi_alert.state.json` prevents duplicate alerts across restarts.

## Safety notes

- `rsi_alert.py` only calls the **public** `/v2/history/candles` endpoint. It never
  authenticates, never reads your account, and cannot place orders.
- `delta_client.py` does contain signed-request support (`wallet_balances`, `positions`),
  used once to verify your keys work. Nothing calls it on the alerting path.
- `.env` is gitignored. Rotate the keys that were pasted in chat.

## Files

```
rsi_band_alert.pine      Pine v5 indicator for TradingView
rsi_alert.py             RSI monitor + alerter (the working path)
delta_client.py          Delta REST client: public candles + HMAC-signed calls
.env                     Secrets and config — gitignored
IMPLEMENTATION_PLAN.md   Full plan, both tracks, credential reference
```
