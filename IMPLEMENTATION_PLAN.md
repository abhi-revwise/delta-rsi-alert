# RSI 60/35 Band Alert on Delta Exchange — Implementation Plan

**Goal:** Get notified when RSI(14) on the **4-hour** candle crosses **above 60** or **below 35**
for a Delta Exchange instrument (e.g. `BTCUSD` perpetual).

---

## 0. The constraint you need to know first

Delta Exchange embeds the **TradingView Charting Library widget**, not full TradingView.
That widget exposes only built-in indicators — **there is no Pine editor and no way to load a
custom Pine Script into Delta Exchange's own chart.**

Consequences:

- Pine Script **can** be used, but it must run on **tradingview.com**, charting a Delta symbol
  (or a proxy symbol like `BINANCE:BTCUSDT` / `BYBIT:BTCUSDT` if Delta's feed isn't listed).
- If you want the alert sourced from **Delta's own price feed** with no third party, you need
  **Track B** (poll Delta's REST API and compute RSI yourself).
- A "no-code" middle option exists: Delta's chart has a built-in RSI you can eyeball, but it
  has **no server-side alerting on indicator values** — only price alerts. Not sufficient here.

Pick one track. Track A is faster; Track B is self-contained and uses Delta's exact candles.

---

## Track A — Pine Script on TradingView (recommended, ~30 min)

### A1. Add the script
1. Open tradingview.com → chart your symbol → set timeframe to **4h**.
2. **Pine Editor** (bottom panel) → paste `rsi_band_alert.pine` → **Save** → **Add to chart**.
3. Verify the two dashed bands sit at 60 and 35 and triangles appear at historical crosses.

Note on the `RSI Timeframe` input: it defaults to `240`. Leave the chart itself on 4h and the
input on `240` — they agree and nothing repaints. If you chart a lower timeframe, the input
still forces 4H RSI, but signals will render on the lower-TF bars.

`Signal only on closed bar` is ON by default. Keep it on: RSI wobbles intrabar and an
unconfirmed cross at 59.8 → 60.1 → 59.7 will fire and then un-fire.

### A2. Create the alert
- Right-click chart → **Add alert** → Condition = **RSI Band Alert (60 / 35)**.
- Either pick a specific `alertcondition` (one alert each for up/down), **or** select
  *"Any alert() function call"* to get all four events from a single alert. The latter is
  cheaper against your TradingView alert quota.
- Trigger: **Once Per Bar Close**.
- Expiration: TradingView alerts expire (Free/Essential ~2 months); set a calendar reminder to renew.

### A3. Choose notification delivery
| Delivery | Needs API key? | Notes |
|---|---|---|
| TradingView popup / email / mobile push | No | Zero setup. Enough if you just want to *know*. |
| **Webhook → your endpoint** | Needs a **paid TradingView plan (Essential+)** | Required for anything programmatic. |
| Webhook → Telegram bot | Telegram bot token | Most popular for phone alerts. |
| Webhook → Discord/Slack | Incoming webhook URL | Zero-code; paste URL straight into the alert. |

The script's alert payload is already JSON, so a receiver can `json.loads()` it directly.

### A4. (Optional) Auto-trade on Delta
Only if you want the alert to *place orders*: stand up a small webhook receiver
(FastAPI/Flask on Railway, Render, Fly.io, or a VPS) that verifies a shared secret in the
payload and then calls Delta's `POST /v2/orders`. **This is where Delta API keys enter.**
Do this only after running alert-only for a couple of weeks.

---

## Track B — Poll Delta's REST API directly (no TradingView, no Pine)

A ~100-line Python service:

1. Every 4H boundary +30s, `GET /v2/history/candles` with `resolution=4h`, ~200 candles.
2. Compute Wilder's RSI(14) on closes (`pandas_ta`, `ta`, or hand-rolled — Wilder smoothing,
   *not* a simple moving average, or your numbers won't match TradingView).
3. Compare `rsi[-2]` (previous closed) vs `rsi[-1]` (just-closed) to detect the cross.
4. Push to Telegram / email / ntfy.
5. Persist last-signalled bar timestamp so a restart doesn't re-alert.

Run it on a cheap VPS or as a GitHub Actions cron. `/v2/history/candles` is a **public**
endpoint — no key needed just to read candles.

**Verify RSI parity once:** compute one value from Delta candles and compare to the same
timestamp in TradingView. Differences mean a different candle open-time convention or
SMA-vs-Wilder smoothing.

---

## Prerequisites & API keys — complete list

### Alert-only (Track A, no trading) — **zero API keys**
- TradingView account (Free tier is enough for popup/email/push).
- Upgrade to **Essential or higher** *only* if you need webhooks.

### Track A + webhook to a messaging app
| Item | Where to get it | Secret? |
|---|---|---|
| TradingView paid plan | tradingview.com/pricing | — |
| Telegram **Bot Token** | Message `@BotFather` → `/newbot` | Yes |
| Telegram **Chat ID** | Message `@userinfobot`, or read `getUpdates` | No |
| Discord/Slack **Incoming Webhook URL** | Server Settings → Integrations | Yes (URL == auth) |
| Your own **webhook shared secret** | Generate: `openssl rand -hex 32` | Yes |
| Public HTTPS endpoint | Railway / Render / Fly.io / VPS + Caddy | — |

### Delta Exchange API keys — needed **only** for placing/managing orders or reading your account
Create at: **Delta Exchange → Profile → API Keys → Create New API Key**

| Credential | Notes |
|---|---|
| `DELTA_API_KEY` | Public identifier. |
| `DELTA_API_SECRET` | **Shown exactly once at creation. Copy it immediately.** |
| Base URL | India: `https://api.india.delta.exchange` · Global: `https://api.delta.exchange` |
| Testnet URL | `https://cdn-ind.testnet.deltaex.org` (India testnet) — **start here** |
| **IP whitelist** | Delta (esp. Delta India) requires whitelisting your server's egress IP. Get a **static IP** before you create the key — dynamic-IP hosts will 401 intermittently. |
| Permissions | Enable **Read** + **Trading**. Leave **Withdrawal disabled.** |
| 2FA | Must be enabled on the account to mint keys. |

**Auth scheme:** HMAC-SHA256. Signature is computed over
`method + timestamp + requestPath + queryString + body`, sent as headers
`api-key`, `timestamp` (Unix seconds), `signature`, plus a `User-Agent`.
Timestamps drift-check server-side — **run NTP on your box**.
Confirm the exact concatenation order against **docs.delta.exchange** before coding; treat
the line above as the shape, not gospel.

### Not required (common misconceptions)
- No Delta key is needed to read candles or to run the Pine Script.
- No TradingView API key exists — TradingView has no public REST API; webhooks are the only egress.

---

## Recommended sequencing

1. **Day 1** — Track A, alert-only, mobile push. Confirms the 60/35 logic on your symbol. No keys.
2. **Week 1** — Observe. Count how many signals fire in 4H on your instrument and whether 60/35
   is actually the threshold you want (see below).
3. **Week 2** — Add webhook → Telegram if you want richer/faster delivery.
4. **Later, only if automating** — testnet Delta keys → paper-trade → mainnet keys with a
   hard position-size cap and withdrawals disabled.

---

## One note on the 60/35 levels

60/35 is asymmetric around 50 and neither level is a classic overbought/oversold boundary
(70/30) — 60 will trip on ordinary bullish momentum, not exhaustion. On 4H crypto that
typically means **frequent** upper-band signals. That may be exactly what you intend if
you're using 60 as a trend-confirmation filter rather than a reversal signal. Both levels
are inputs in the script, so retune from the chart without editing code.

---

## Files

- `rsi_band_alert.pine` — the indicator. Paste into TradingView's Pine Editor.
