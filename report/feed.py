"""Candles for COMEX gold, with the real traded volume spot gold cannot give.

Yahoo's chart endpoint needs no key and answers from a GitHub runner, and each
interval carries its own history limit, measured rather than assumed:

    1m   7 days      5m   1 month     15m  1 month
    30m  1 month     1h   3 months    1d   6 months

4h is not offered and is folded from the hourly candles. 90m is refused
outright. Spot XAUUSD does not exist here at all -- the report is built on the
futures contract, which moves with spot but does not print the same prices.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

SYMBOL = "GC=F"
UA = {"User-Agent": "Mozilla/5.0 (compatible; session-report)"}

# interval -> the range that reaches as far back as the interval allows
RANGE = {"1m": "7d", "5m": "1mo", "15m": "1mo", "30m": "1mo", "60m": "3mo",
         "1d": "6mo"}
MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "60m": 60, "4h": 240}


def fetch(symbol, interval, rng=None, tries=3):
    """One interval of candles, newest last. Raises if the feed will not answer."""
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/%s?interval=%s&range=%s"
           % (urllib.parse.quote(symbol), interval, rng or RANGE[interval]))
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = json.loads(r.read().decode())
            break
        except Exception as e:              # noqa: BLE001 - retried, then reported
            last = e
            time.sleep(2 * (attempt + 1))
    else:
        raise RuntimeError("%s %s: %s" % (symbol, interval, last))

    res = raw["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    out = []
    for i, t in enumerate(ts):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        # Yahoo leaves holes where the contract did not trade. A candle missing
        # any of its four prices is not a candle.
        if None in (o, h, l, c):
            continue
        v = q.get("volume", [None] * len(ts))[i] or 0
        out.append({"t": t * 1000, "o": float(o), "h": float(h),
                    "l": float(l), "c": float(c), "v": float(v)})
    return out


def fold(candles, factor):
    """Build a longer interval from a shorter one, grouping on the clock.

    Buckets are cut on absolute time rather than by counting candles, so a gap
    in the feed shifts nothing: a 4h candle always covers the same four hours it
    would on the exchange's own chart.
    """
    step = factor * 60 * 1000
    out = []
    for k in candles:
        start = k["t"] - (k["t"] % step)
        if out and out[-1]["t"] == start:
            b = out[-1]
            b["h"] = max(b["h"], k["h"])
            b["l"] = min(b["l"], k["l"])
            b["c"] = k["c"]
            b["v"] += k["v"]
        else:
            out.append({"t": start, "o": k["o"], "h": k["h"], "l": k["l"],
                        "c": k["c"], "v": k["v"]})
    return out


BINANCE = ["https://data-api.binance.vision", "https://api.binance.com",
           "https://api1.binance.com"]
BN_TF = {"5m": "5m", "15m": "15m", "1h": "1h", "4h": "4h", "1m": "1m", "30m": "30m"}


def binance(symbol, tf, limit=1000):
    """Crypto comes from the exchange itself rather than a quote aggregator.

    Yahoo carries BTC and ETH, but the exchange prints the candles everyone
    else is reading, and the session report is meant to describe the chart he
    would open -- not a reconstruction of it.
    """
    path = "/api/v3/klines?symbol=%s&interval=%s&limit=%d" % (symbol, BN_TF[tf], limit)
    last = None
    for host in BINANCE:
        try:
            req = urllib.request.Request(host + path, headers=UA)
            with urllib.request.urlopen(req, timeout=25) as r:
                rows = json.loads(r.read().decode())
            return [{"t": int(k[0]), "o": float(k[1]), "h": float(k[2]),
                     "l": float(k[3]), "c": float(k[4]), "v": float(k[5])}
                    for k in rows]
        except Exception as e:          # noqa: BLE001 - a blocked host falls through
            last = e
    raise RuntimeError("binance %s %s: %s" % (symbol, tf, last))


def candles(source, symbol, tf):
    """One timeframe from whichever feed carries the instrument."""
    if source == "binance":
        return binance(symbol, tf)
    if tf == "4h":
        return fold(fetch(symbol, "60m"), 4)
    return fetch(symbol, "60m" if tf == "1h" else tf)


def load(timeframes):
    """Every timeframe the report needs, keyed by its own name."""
    out = {}
    for tf in timeframes:
        if tf == "4h":
            out[tf] = fold(fetch(SYMBOL, "60m"), 4)
        else:
            out[tf] = fetch(SYMBOL, "60m" if tf == "1h" else tf)
    return out
