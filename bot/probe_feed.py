"""Is there a free feed for the gold he actually trades?

Yahoo has no spot gold -- XAUUSD=X and XAU=X both 404 -- only COMEX futures,
which run about forty dollars above spot because a future carries the interest
to its delivery date. Forty dollars is fatal for a report whose whole output is
price levels to leave limit orders at.

So: what else is reachable without an API key, and how close does it actually
sit to the chart he reads.
"""

import csv
import io
import json
import urllib.parse
import urllib.request

HEAD = {"User-Agent": "Mozilla/5.0"}


def get(url, timeout=30):
    req = urllib.request.Request(url, headers=HEAD)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def yahoo(symbol, interval="15m", rng="5d"):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/%s?interval=%s&range=%s"
           % (urllib.parse.quote(symbol), interval, rng))
    res = json.loads(get(url))["chart"]["result"][0]
    q, ts = res["indicators"]["quote"][0], res["timestamp"]
    return [{"t": ts[i], "c": q["close"][i], "h": q["high"][i], "l": q["low"][i]}
            for i in range(len(ts)) if q["close"][i] is not None]


def binance(symbol, interval="15m", limit=500):
    for host in ("api.binance.com", "api-gcp.binance.com", "data-api.binance.vision"):
        try:
            url = ("https://%s/api/v3/klines?symbol=%s&interval=%s&limit=%d"
                   % (host, symbol, interval, limit))
            rows = json.loads(get(url))
            return [{"t": r[0] // 1000, "c": float(r[4]),
                     "h": float(r[2]), "l": float(r[3])} for r in rows]
        except Exception:                        # noqa: BLE001 - try the next host
            continue
    raise RuntimeError("every Binance host refused")


def stooq(symbol, interval="5"):
    body = get("https://stooq.com/q/d/l/?s=%s&i=%s" % (symbol, interval)).decode()
    rows = list(csv.DictReader(io.StringIO(body)))
    if not rows or "Close" not in (rows[0] or {}):
        raise RuntimeError("no usable rows: %s" % body[:120].replace("\n", " "))
    return [{"t": r["Date"], "c": float(r["Close"]),
             "h": float(r["High"]), "l": float(r["Low"])} for r in rows]


SOURCES = [
    ("GC=F  (yahoo)",     lambda: yahoo("GC=F"),        "COMEX futures -- what the report uses"),
    ("PAXGUSDT (binance)", lambda: binance("PAXGUSDT"), "token redeemable for one ounce of gold"),
    ("XAUTUSDT (binance)", lambda: binance("XAUTUSDT"), "the same idea from Tether"),
    ("xauusd (stooq)",    lambda: stooq("xauusd"),      "spot, if stooq serves intraday without a key"),
]

series = {}
for name, call, what in SOURCES:
    try:
        ks = call()
    except Exception as e:                       # noqa: BLE001 - failure is the answer
        print("%-20s UNAVAILABLE  (%s)  -- %s" % (name, e, what))
        continue
    series[name] = ks
    print("%-20s %4d candles   last %9.2f   high %9.2f   low %9.2f   -- %s"
          % (name, len(ks), ks[-1]["c"], max(k["h"] for k in ks),
             min(k["l"] for k in ks), what))

# His screen said 4296.47 at 02:12 Tehran. Distance from that is the only test
# that matters: a level forty dollars off his chart cannot be traded from.
HIS = 4296.47
print("\nagainst his own screen (%.2f):" % HIS)
for name, ks in series.items():
    print("  %-20s %+8.2f   (%+.2f%%)"
          % (name, ks[-1]["c"] - HIS, (ks[-1]["c"] - HIS) / HIS * 100))
