"""Every candidate for every symbol, priced now, so he can match them in one pass.

Gold cost a day because the symbol was chosen from what the feed offered rather
than from what he trades. Rather than repeat that discovery eight more times,
this prints each instrument's plausible tickers side by side. He holds the list
against his own charts once and says which line matches; nothing here is
decided by guessing what a trader "probably" looks at.
"""

import json
import urllib.parse
import urllib.request

HEAD = {"User-Agent": "Mozilla/5.0"}


def get(url, timeout=25):
    req = urllib.request.Request(url, headers=HEAD)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode()


def yahoo(symbol):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/%s?interval=15m&range=1d"
           % urllib.parse.quote(symbol))
    res = json.loads(get(url))["chart"]["result"][0]
    c = [x for x in res["indicators"]["quote"][0]["close"] if x is not None]
    return c[-1]


def binance(symbol):
    for host in ("https://data-api.binance.vision", "https://api.binance.com"):
        try:
            rows = json.loads(get("%s/api/v3/klines?symbol=%s&interval=15m&limit=1"
                                  % (host, symbol)))
            return float(rows[-1][4])
        except Exception:                        # noqa: BLE001 - try the next host
            continue
    raise RuntimeError("no Binance host answered")


GROUPS = [
    ("طلا  GOLD", [
        ("XAUTUSDT   binance", binance, "XAUTUSDT", "tokenised gold -- what the report uses now"),
        ("PAXGUSDT   binance", binance, "PAXGUSDT", "the other gold token"),
        ("GC=F       yahoo",   yahoo,   "GC=F",     "COMEX future -- the old wrong one"),
    ]),
    ("نزدک  NASDAQ", [
        ("NQ=F       yahoo",   yahoo, "NQ=F",  "E-mini Nasdaq-100 FUTURE -- what the report uses now"),
        ("^NDX       yahoo",   yahoo, "^NDX",  "Nasdaq-100 CASH index"),
        ("^IXIC      yahoo",   yahoo, "^IXIC", "Nasdaq Composite -- a different index entirely"),
    ]),
    ("داوجونز  DOW", [
        ("YM=F       yahoo",   yahoo, "YM=F", "E-mini Dow FUTURE -- what the report uses now"),
        ("^DJI       yahoo",   yahoo, "^DJI", "Dow Jones Industrial Average, CASH"),
    ]),
    ("یورو/دلار  EURUSD", [("EURUSD=X   yahoo", yahoo, "EURUSD=X", "spot")]),
    ("پوند/دلار  GBPUSD", [("GBPUSD=X   yahoo", yahoo, "GBPUSD=X", "spot")]),
    ("دلار/ین  USDJPY",   [("USDJPY=X   yahoo", yahoo, "USDJPY=X", "spot")]),
    ("کیوی/دلار  NZDUSD", [("NZDUSD=X   yahoo", yahoo, "NZDUSD=X", "spot")]),
    ("بیت‌کوین  BTC", [
        ("BTCUSDT    binance", binance, "BTCUSDT", "what the report uses now"),
        ("BTC-USD    yahoo",   yahoo,   "BTC-USD", "an aggregator's version"),
    ]),
    ("اتریوم  ETH", [
        ("ETHUSDT    binance", binance, "ETHUSDT", "what the report uses now"),
        ("ETH-USD    yahoo",   yahoo,   "ETH-USD", "an aggregator's version"),
    ]),
]

for title, rows in GROUPS:
    print("\n%s" % title)
    for label, call, sym, what in rows:
        try:
            print("   %-22s %14.4f   %s" % (label, call(sym), what))
        except Exception as e:                   # noqa: BLE001 - unavailable is an answer
            print("   %-22s %14s   %s  (%s)" % (label, "--", what, e))
