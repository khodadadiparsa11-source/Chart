"""Watch a handful of symbols for heavy, one-sided volume and report to Telegram.

WHAT IT LOOKS FOR, on each freshly closed candle:

  absorption   volume well above its own recent normal, a delta that is a real
               share of what traded, and that delta pointing the OPPOSITE way
               from where the candle closed. Price rose while selling dominated
               means someone large was filling the other way behind the move.

  spike        volume far above normal, whichever way it went. Not a signal on
               its own — a heads-up that something happened here.

ON THE DELTA: counting aggressors needs every trade, and a five-minute candle on
BTC holds thousands. One-second klines give a price and a volume for every
second with the side taken from that second's own direction — one request per
symbol instead of dozens, and close enough to judge a candle by. The messages
say so rather than implying the figure is exact.

No dependencies beyond the standard library, so the workflow needs no install
step. Credentials come from the environment and never from the repository.
"""

import json
import os
import time
import urllib.parse
import urllib.request

SYMBOLS  = os.environ.get("SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,PAXGUSDT").split(",")
INTERVAL = os.environ.get("INTERVAL", "5m")
CHART_URL = "https://khodadadiparsa11-source.github.io/Chart/"

VOL_MULT   = float(os.environ.get("VOL_MULT", "1.8"))    # vs the recent normal
DELTA_MIN  = float(os.environ.get("DELTA_MIN", "0.15"))  # |delta| / traded volume
SPIKE_MULT = float(os.environ.get("SPIKE_MULT", "3.0"))
LOOKBACK   = 20                                          # candles forming "normal"

HOSTS = ["https://data-api.binance.vision", "https://api.binance.com",
         "https://api1.binance.com", "https://api2.binance.com"]

SECONDS = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600}


def get_json(path):
    """Try each Binance host in turn; a blocked or failing one falls through."""
    last = None
    for host in HOSTS:
        try:
            req = urllib.request.Request(host + path, headers={"User-Agent": "volume-watch"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode())
        except Exception as e:      # noqa: BLE001 - any failure means try the next host
            last = e
    raise RuntimeError("all Binance hosts failed: %s" % last)


def send(text):
    token = os.environ.get("TELEGRAM_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("no telegram credentials; would have sent:\n" + text)
        return
    data = urllib.parse.urlencode({
        "chat_id": chat, "text": text,
        "parse_mode": "HTML", "disable_web_page_preview": "true",
    }).encode()
    req = urllib.request.Request("https://api.telegram.org/bot%s/sendMessage" % token, data=data)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            r.read()
    except Exception as e:          # noqa: BLE001 - a failed send must not stop the other symbols
        print("telegram send failed: %s" % e)


def delta_for(symbol, start_ms, end_ms):
    """Approximate buy/sell split across a candle from its one-second klines."""
    buy = sell = 0.0
    rows = get_json("/api/v3/klines?symbol=%s&interval=1s&limit=1000&startTime=%d&endTime=%d"
                    % (symbol, start_ms, end_ms))
    for k in rows:
        o, c, v = float(k[1]), float(k[4]), float(k[5])
        if v <= 0:
            continue
        if c < o:
            sell += v
        else:
            buy += v
    return buy, sell


def human(v):
    if v >= 1e9:
        return "%.2fB" % (v / 1e9)
    if v >= 1e6:
        return "%.2fM" % (v / 1e6)
    if v >= 1e3:
        return "%.1fK" % (v / 1e3)
    return "%.2f" % v


def check(symbol):
    ks = get_json("/api/v3/klines?symbol=%s&interval=%s&limit=%d"
                  % (symbol, INTERVAL, LOOKBACK + 3))
    if len(ks) < LOOKBACK + 2:
        return None

    closed = ks[-2]                      # ks[-1] is still forming
    open_ms, close_ms = int(closed[0]), int(closed[6])
    o, h, l, c, vol = (float(closed[1]), float(closed[2]),
                       float(closed[3]), float(closed[4]), float(closed[5]))

    # Only the candle that closed since the last run. With the schedule matching
    # the candle length this is the whole of the de-duplication: an older candle
    # was either already reported or is not worth reporting now.
    age = time.time() * 1000 - close_ms
    if age > (SECONDS.get(INTERVAL, 300) * 1000) + 90_000:
        return None

    prior = [float(k[5]) for k in ks[-(LOOKBACK + 2):-2]]
    normal = sum(prior) / len(prior) if prior else 0
    if normal <= 0:
        return None
    rvol = vol / normal

    if rvol < min(VOL_MULT, SPIKE_MULT):
        return None

    buy, sell = delta_for(symbol, open_ms, close_ms)
    traded = buy + sell
    delta = buy - sell
    ratio = abs(delta) / traded if traded else 0

    rose, fell = c > o, c < o
    absorbed = (rvol >= VOL_MULT and ratio >= DELTA_MIN
                and ((rose and delta < 0) or (fell and delta > 0)))

    if absorbed:
        hidden = "فروش" if rose else "خرید"
        arrow = "🔻" if rose else "🔼"
        title = "%s <b>جذب</b> — %s پنهان" % (arrow, hidden)
    elif rvol >= SPIKE_MULT:
        title = "⚡ <b>حجم سنگین</b>"
    else:
        return None

    return (
        "{title}\n"
        "<b>{sym}</b> · {tf}\n"
        "قیمت <code>{price}</code>\n"
        "حجم <b>{rvol:.1f}x</b> نرمال\n"
        "دلتا <code>{delta}</code> ({pct:.0f}٪ حجم)\n"
        "<a href=\"{url}\">باز کردن چارت</a>\n"
        "<i>دلتا از کندل ۱ ثانیه‌ای — تقریبی</i>"
    ).format(title=title, sym=symbol, tf=INTERVAL, price=("%g" % c),
             rvol=rvol, delta=("+" if delta >= 0 else "-") + human(abs(delta)),
             pct=ratio * 100, url=CHART_URL)


def main():
    if os.environ.get("TEST") == "1":
        send("✅ ربات وصل است.\nنمادها: %s\nتایم‌فریم: %s" % (", ".join(SYMBOLS), INTERVAL))
        return

    sent = 0
    for sym in SYMBOLS:
        sym = sym.strip().upper()
        if not sym:
            continue
        try:
            msg = check(sym)
        except Exception as e:      # noqa: BLE001 - one bad symbol must not stop the rest
            print("%s failed: %s" % (sym, e))
            continue
        if msg:
            send(msg)
            sent += 1
            print("alerted %s" % sym)
        else:
            print("%s quiet" % sym)
    print("done, %d alert(s)" % sent)


if __name__ == "__main__":
    main()
