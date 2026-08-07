"""Minimal Delta Exchange REST client: public candles + HMAC-signed private calls."""

import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "delta-rsi-alert/1.0"


def load_env(path=".env"):
    """Load KEY=VALUE lines into os.environ without overwriting real env vars."""
    f = Path(__file__).parent / path
    if not f.exists():
        return
    for line in f.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def _request(method, url, headers=None, body=None, timeout=20):
    data = body.encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("User-Agent", USER_AGENT)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"raw": raw}


class DeltaClient:
    def __init__(self, base_url=None, api_key=None, api_secret=None):
        self.base = (base_url or os.environ.get(
            "DELTA_BASE_URL", "https://api.india.delta.exchange")).rstrip("/")
        self.key = api_key or os.environ.get("DELTA_API_KEY", "")
        self.secret = api_secret or os.environ.get("DELTA_API_SECRET", "")

    # ---------- public ----------
    def candles(self, symbol, resolution, count=300):
        """Return candles oldest-first. Public endpoint — no auth required."""
        secs = _resolution_seconds(resolution)
        end = int(time.time())
        start = end - count * secs
        q = urllib.parse.urlencode(
            {"resolution": resolution, "symbol": symbol, "start": start, "end": end})
        status, payload = _request("GET", f"{self.base}/v2/history/candles?{q}")
        if status != 200 or not payload.get("success"):
            raise RuntimeError(f"candles failed [{status}]: {payload}")
        return sorted(payload["result"], key=lambda c: c["time"])

    # ---------- private ----------
    def _signed(self, method, path, query="", body=""):
        """Delta auth: HMAC-SHA256 over method + timestamp + path + query + body."""
        ts = str(int(time.time()))
        message = method + ts + path + query + body
        sig = hmac.new(self.secret.encode(), message.encode(),
                       hashlib.sha256).hexdigest()
        headers = {"api-key": self.key, "timestamp": ts, "signature": sig}
        url = f"{self.base}{path}{query}"
        return _request(method, url, headers=headers,
                        body=body if body else None)

    def wallet_balances(self):
        return self._signed("GET", "/v2/wallet/balances")

    def positions(self):
        return self._signed("GET", "/v2/positions/margined")


def _resolution_seconds(res):
    unit = res[-1]
    n = int(res[:-1])
    return n * {"m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]
