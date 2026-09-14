"""Which symbol is the gold he actually trades?

The report was built on GC=F -- COMEX futures -- because that is what Yahoo
offers first for "gold". He trades XAUUSD, spot. They move together and are not
the same instrument: different price, different highs and lows, different
trading hours. He spotted it by holding the two charts side by side.

This asks the feed directly rather than arguing from screenshots: what does each
candidate return, and how far apart are they really.
"""

import json
import urllib.request

HOST = "https://query1.finance.yahoo.com/v8/finance/chart/"
HEAD = {"User-Agent": "Mozilla/5.0"}

CANDIDATES = [
    ("GC=F",     "COMEX gold futures, front month (what the report uses now)"),
    ("XAUUSD=X", "spot gold against the dollar"),
    ("XAU=X",    "another spelling Yahoo sometimes carries"),
    ("MGC=F",    "micro gold futures"),
]


def fetch(symbol, interval="15m", rng="5d"):
    url = "%s%s?interval=%s&range=%s" % (HOST, urllib.parse.quote(symbol), interval, rng)
    req = urllib.request.Request(url, headers=HEAD)
    with urllib.request.urlopen(req, timeout=30) as r:
        j = json.loads(r.read())
    res = j["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    ts = res["timestamp"]
    ks = [{"t": ts[i], "h": q["high"][i], "l": q["low"][i], "c": q["close"][i]}
          for i in range(len(ts)) if q["close"][i] is not None]
    return ks


import urllib.parse  # noqa: E402 - after the constants, for readability

for sym, what in CANDIDATES:
    try:
        ks = fetch(sym)
    except Exception as e:                      # noqa: BLE001 - a missing symbol is an answer
        print("%-10s UNAVAILABLE  (%s)  -- %s" % (sym, e, what))
        continue
    hi = max(k["h"] for k in ks)
    lo = min(k["l"] for k in ks)
    print("%-10s %5d candles   last %.2f   5d high %.2f   low %.2f   -- %s"
          % (sym, len(ks), ks[-1]["c"], hi, lo, what))

# The number that settles it: how far apart the two are at the same moment.
try:
    a = {k["t"]: k["c"] for k in fetch("GC=F")}
    b = {k["t"]: k["c"] for k in fetch("XAUUSD=X")}
    both = sorted(set(a) & set(b))
    if both:
        gaps = [a[t] - b[t] for t in both]
        print("\nshared 15m candles: %d" % len(both))
        print("futures minus spot: last %+.2f   mean %+.2f   min %+.2f   max %+.2f"
              % (gaps[-1], sum(gaps) / len(gaps), min(gaps), max(gaps)))
    else:
        print("\nno 15m candle stamps in common -- their sessions do not line up")
except Exception as e:                          # noqa: BLE001
    print("\ncomparison failed: %s" % e)
