"""Find out whether a free gold feed is reachable, before promising one.

Everything built here so far runs on Binance, which has no gold. A nightly
session report needs XAUUSD, and the honest order of work is to check that the
data exists and carries what it needs to carry -- volume above all -- before
designing anything on top of it.

Prints what each source actually returned. Nothing is decided from a guess.
"""

import json
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (compatible; session-report-probe)"}


def get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode()


def yahoo(symbol, interval="15m", rng="5d"):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/%s"
           "?interval=%s&range=%s" % (urllib.parse.quote(symbol), interval, rng))
    raw = json.loads(get(url))
    res = raw["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    vols = [v for v in q.get("volume", []) if v]
    closes = [c for c in q.get("close", []) if c]
    return {
        "candles": len(ts),
        "first": ts[0], "last": ts[-1],
        "close_last": closes[-1] if closes else None,
        "volume_bars": len(vols),
        "volume_sample": vols[-5:] if vols else [],
        "currency": res["meta"].get("currency"),
        "exchange": res["meta"].get("exchangeName"),
        "tz": res["meta"].get("exchangeTimezoneName"),
    }


import urllib.parse  # noqa: E402  (after the helpers, for readability above)

for sym in ("GC=F", "XAUUSD=X", "MGC=F", "EURUSD=X"):
    for interval, rng in (("15m", "5d"), ("1h", "1mo")):
        try:
            print("%-10s %-4s %s" % (sym, interval, yahoo(sym, interval, rng)))
        except Exception as e:              # noqa: BLE001 - a probe reports failures
            print("%-10s %-4s FAILED: %s" % (sym, interval, e))

# Stooq as a fallback: plain CSV, no key, but daily only for most symbols.
try:
    csv = get("https://stooq.com/q/d/l/?s=xauusd&i=d")
    rows = csv.strip().splitlines()
    print("stooq xauusd daily: %d rows, last: %s" % (len(rows) - 1, rows[-1]))
except Exception as e:                      # noqa: BLE001
    print("stooq FAILED: %s" % e)
