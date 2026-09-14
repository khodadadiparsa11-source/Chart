"""A spot feed he can actually sign up for.

His gold is OANDA's XAUUSD. OANDA is closed to him -- Iran is not on their list
and every other country wants identity documents, which is not a door worth
forcing on a financial account. So the question becomes: which free source of
spot prices needs nothing but an email, answers from a GitHub runner, and
carries gold, the four pairs and the two indices.

Reachability and what each returns without a key. Nothing here signs anything
up; it only finds out which door is worth knocking on.
"""

import json
import os
import urllib.error
import urllib.request

HEAD = {"User-Agent": "Mozilla/5.0"}
KEY = os.environ.get("TWELVE_KEY", "demo")


def get(url, head=None, timeout=25):
    req = urllib.request.Request(url, headers=head or HEAD)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode()


def twelve(symbol, interval="15min"):
    url = ("https://api.twelvedata.com/time_series?symbol=%s&interval=%s"
           "&outputsize=5&apikey=%s" % (urllib.parse.quote(symbol), interval, KEY))
    j = json.loads(get(url))
    if j.get("status") == "error":
        raise RuntimeError(j.get("message", "")[:150])
    return j["values"]


import urllib.parse  # noqa: E402

print("=== twelvedata (email signup, no documents) — key=%s ==="
      % ("set" if KEY != "demo" else "demo"))
for sym in ("XAU/USD", "EUR/USD", "GBP/USD", "USD/JPY", "NZD/USD"):
    try:
        v = twelve(sym)
        print("  %-9s OK    last close %s   at %s" % (sym, v[0]["close"], v[0]["datetime"]))
    except Exception as e:                       # noqa: BLE001 - the error is the finding
        print("  %-9s %s" % (sym, e))

print("\n=== keyless snapshots, just to see the true spot number ===")
for name, url, pick in (
    ("gold-api", "https://api.gold-api.com/price/XAU", lambda j: j.get("price")),
    ("frankfurter", "https://api.frankfurter.app/latest?from=XAU&to=USD",
     lambda j: (j.get("rates") or {}).get("USD")),
):
    try:
        print("  %-12s %s" % (name, pick(json.loads(get(url)))))
    except Exception as e:                       # noqa: BLE001
        print("  %-12s unavailable: %s" % (name, e))

print("\n=== what the report uses now ===")
try:
    rows = json.loads(get("https://data-api.binance.vision/api/v3/klines"
                          "?symbol=XAUTUSDT&interval=15m&limit=1"))
    print("  XAUTUSDT     %s" % rows[-1][4])
except Exception as e:                           # noqa: BLE001
    print("  XAUTUSDT     unavailable: %s" % e)
