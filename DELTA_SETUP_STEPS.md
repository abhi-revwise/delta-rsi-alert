# Getting notified on RSI 60/35 crosses — without TradingView

Verified against Delta Exchange live (BTCUSD, India) and the Delta API on 2026-08-07.

## What Delta Exchange can and cannot do

| Capability | Available? | How verified |
|---|---|---|
| Show RSI on the 4H chart | **Yes** — built-in indicator | Found "Relative Strength Index" in the Indicators dialog |
| Load custom Pine Script | **No** | Indicators list is a flat built-in library; searching "pine" returns only "Cho**ppine**ss Index". No Pine Editor, no import. |
| Alert on an indicator condition | **No** | No bell/alert control anywhere in the chart toolbar |
| Alert on a **price** level, push to the Delta app | **Unconfirmed** — see below | Not verifiable while logged out |
| Create price alerts via API | **No** | `/v2/price_alerts`, `/v2/alerts`, `/v2/user/alerts`, `/v2/notifications` all 404; API docs list no alert or notification category |

### Correction on Delta price alerts

An earlier version of this file stated Delta Exchange has a price-alert feature. That was
asserted, not verified. On checking:

- Delta Exchange's **Help Center has no "Alerts" or "Notifications" category at all**
  (categories are: Account, Deposits, KYC, Withdrawals, Fees, Taxation, Trading & Order
  Management, Banking, Perpetuals/Options, Offers, API & Automation, Trust & Safety,
  Troubleshooting, Chart Related, Spot, TradingView, Algo Trading).
- Delta's own automation blog routes alerting **out** to TradingView + a third-party bot,
  which is not what a platform with native alerts would document.
- Most "Delta price alert" search hits are for **Delta by eToro** (`delta.app`), an
  unrelated portfolio-tracker app. Do not follow those instructions.
- A couple of YouTube tutorials specifically titled for Delta Exchange do exist, so the
  **mobile app** may have price alerts even though the web app and help center do not
  surface them.

**Check it yourself in 10 seconds:** open the Delta mobile app → BTCUSD → look for a bell
icon or "Alerts". If it is there, Route A works. If not, Route A is off the table entirely
and Route B is the only option. Either way it is price-only and never RSI-aware.

**Bottom line:** Delta's app cannot watch RSI for you under any configuration.

---

## Route A — Delta app push, via RSI-to-price conversion (manual, every 4H)

RSI is strictly monotonic in the current bar's close, so the RSI band can be converted
into an **exact price**: the close that would print RSI = 60 (or 35) on this bar.
Set a Delta price alert at that number and **the notification comes from the Delta app**.

```bash
python3 rsi_alert.py --targets
```

```
BTCUSD 4h — RSI now 63.79, last close 65003
Levels for the bar closing 2026-08-07 16:00 UTC:

  RSI 60  <-  close at/above  64,819.5   (-0.28%)
  RSI 35  <-  close at/below  62,611.5   (-3.68%)
```

(The inversion is exact, not an estimate — round-trip tested: feeding 64,819.52 back
through the RSI calculation returns 60.000000.)

Steps:
1. Run `python3 rsi_alert.py --targets`
2. In the Delta app: open BTCUSD → **Price Alert** → create one alert at each level
3. Enable push notifications for Delta in your phone's OS settings
4. **Repeat after every 4H close** — the levels move each bar

### The catch, stated plainly
These levels are valid for **one bar only**, and there is no API to automate setting
them. You would be re-entering two numbers by hand six times a day, including at
01:30, 05:30 and 09:30 IST. Delta also fires on *price touching* the level intrabar,
whereas an RSI cross is confirmed only at bar **close** — so you will get false
positives when price spikes through and comes back.

This is the only way to make the notification originate from the Delta app. It is not
a good way to run the strategy.

---

## Route B — automatic phone push (recommended)

Delta's app will not do this unattended, so the push has to come from something else.
No TradingView involved — this reads Delta's own BTCUSD candles.

### Free notification channels, ranked

All of these are already wired into `rsi_alert.py` or are a few lines away.

| Channel | Cost | Account needed | Phone push | Setup | Notes |
|---|---|---|---|---|---|
| **ntfy.sh** | Free | **None** | Yes | ~2 min | Pick a secret topic, subscribe in the app. Easiest by far. Self-hostable later. |
| **Telegram bot** | Free | Telegram | Yes | ~5 min | Most reliable, rich formatting, full history. Two IDs to fetch. |
| **Discord webhook** | Free | Discord | Yes | ~2 min | Paste one URL. Good if you already live in Discord. |
| **Slack webhook** | Free | Slack | Yes | ~3 min | Same idea; workspace admin may need to approve. |
| **Email (Gmail SMTP)** | Free | Gmail | Weak | ~10 min | Needs an App Password. Slow and easy to miss. |
| **macOS notification** | Free | None | No | 0 min | Already on. Dies when the Mac sleeps — misses 01:30 / 05:30 IST closes. |
| **Pushover** | $5 once | Pushover | Yes | ~5 min | Not free, but the most polished. Only if the free ones annoy you. |

**Recommendation: ntfy.sh.** No signup, no token to leak, real push, and it is the only
one on this list that costs you nothing and asks for nothing. Telegram if you want the
alert history in a chat you already read.

### Where the RSI numbers come from

You do not need a data subscription. RSI is computed locally from candles:

| Source | Cost | Why / why not |
|---|---|---|
| **Delta `/v2/history/candles`** | Free, no key | **In use.** Public endpoint, and it is the exact instrument you trade. Correct choice. |
| Binance / Bybit public API | Free, no key | Fallback if Delta's API is down. Prices differ slightly. |
| TAAPI.io | Free tier ~1 req/15s | Returns RSI ready-made. Pointless here — you would add a rate limit and a dependency to avoid 30 lines of arithmetic. |
| Twelve Data / Alpha Vantage | Free tier, key needed | Same objection, plus poor crypto-perp coverage. |

Computing RSI yourself is free, instant, has no rate limit, and matches Delta's candles
exactly. The Wilder-smoothing implementation in `rsi_alert.py` is round-trip verified.

### ntfy.sh — closest thing to "an app notification", zero accounts

1. Install **ntfy** (iOS App Store / Google Play / F-Droid)
2. Pick a private topic string — treat it like a password, anyone who guesses it can
   read your alerts. e.g. `delta-rsi-` plus random characters:
   ```bash
   echo "delta-rsi-$(openssl rand -hex 8)"
   ```
3. In the ntfy app: **Subscribe to topic** → paste it
4. Put the same string in `.env` as `NTFY_TOPIC=`
5. Test: `python3 rsi_alert.py --once`

### Telegram — better formatting, needs two IDs

1. Message `@BotFather` → `/newbot` → copy the token → `.env` `TELEGRAM_BOT_TOKEN=`
2. Message `@userinfobot` → copy your numeric ID → `.env` `TELEGRAM_CHAT_ID=`
3. Send your new bot any message once, so it is allowed to message you back
4. Test: `python3 rsi_alert.py --once`

### Then run it unattended

```
5 0,4,8,12,16,20 * * * cd "/Users/abhinavchamoli/delta exchange pine" && /usr/bin/python3 rsi_alert.py --once >> rsi.log 2>&1
```

UTC candle closes. If your Mac's cron runs on IST, use `35 5,9,13,17,21,1` instead.
Your machine must be awake at those times — for real reliability run it on a small VPS.
`rsi_alert.state.json` prevents duplicate alerts across restarts.

Unlike Route A this fires on **confirmed bar close**, matching the actual RSI cross,
and needs no manual input ever.

---

## Optional — see the bands on Delta's chart

Independent of alerting, you can display RSI 60/35 on Delta itself:

1. Chart toolbar → timeframe (`1h`) → **HOURS → 4 hours**
2. **ƒx Indicators** → search `relative strength` → **Relative Strength Index**
3. Gear on the "RSI 14" pane → **Inputs**: Length `14`
4. **Style** tab → change the band levels from the default 70/30 to **60** and **35**

Visual only. Delta raises no alert from this.

---

## Files

```
rsi_alert.py             RSI monitor, alerter, and --targets calculator
delta_client.py          Delta REST client
.env                     Config and secrets (gitignored)
rsi_band_alert.pine      Pine version — unused unless you ever want TradingView
```
