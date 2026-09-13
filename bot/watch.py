"""Watch a few symbols for zones worth an order, and send the chart to Telegram.

WHAT COUNTS AS A ZONE HERE

Not "heavy volume". Heavy volume happens every hour and alerting on it is how a
bot becomes noise. What this looks for is the three-part shape:

  1. a BASE   — one to five candles whose range is small against the recent
                normal, yet whose volume is well ABOVE it. Money moved, price
                did not. That gap is the only observable trace of size being
                filled; nothing in any feed names who filled it.
  2. an EXIT  — the very next candle leaves the base with a wide range and
                volume of its own, closing clear of it. Held still, then let go.
  3. SILENCE  — price has not come back since. A zone price already traded
                back through is spent; it is dropped, not alerted.

THE ALERT IS NOT WHEN THE ZONE FORMS. It is when price RETURNS to it, because
that is the moment an order would be placed. A zone that formed three hours ago
and is being touched now is the message; the same zone sitting untouched is not.

ALL TIMEFRAMES: every symbol is scanned on 5m, 15m, 1h and 4h. A zone that
lines up with a zone in the same direction on another timeframe scores higher.
1m is deliberately left out — GitHub's schedule is five minutes at best, so a
1m zone would be reported after it had already been traded.

THE NUMBER on the image is a 0-10 conviction score built from: how heavy the
base volume was, how tight it was, how hard the exit left, which timeframe it
sits on, how many other timeframes agree, and whether the aggressor flow inside
the base pointed the OPPOSITE way from the exit — selling absorbed before a rise
is the cleanest version of this shape there is.

A score is a ranking, not a probability. Nothing here has been backtested.
"""

import io
import json
import os
import time
import urllib.parse
import urllib.request

# ---------------------------------------------------------------- settings


def env(name, default):
    """An unset repository variable arrives as an empty string, not as absent."""
    v = os.environ.get(name)
    return v.strip() if v and v.strip() else default


SYMBOLS = [s.strip().upper() for s in
           env("SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,PAXGUSDT").split(",")
           if s.strip()]

# Scanned on four timeframes; alerted on three. A 5m zone on crypto is noise
# more often than it is a level, so 5m is read only as agreement for a bigger
# zone -- it never raises an alert of its own.
TFS = ["5m", "15m", "1h", "4h"]
ALERT_TFS = ["15m", "1h", "4h"]
TF_WEIGHT = {"5m": 0, "15m": 1, "1h": 2, "4h": 3}
FINER = {"5m": "1m", "15m": "1m", "1h": "5m", "4h": "15m"}

MIN_SCORE = float(env("MIN_SCORE", "8"))       # out of 10
COOLDOWN_MIN = int(env("COOLDOWN_MIN", "180"))  # per symbol
MAX_PER_RUN = int(env("MAX_PER_RUN", "2"))

MIN_BASE, MAX_BASE = 1, 5        # his own count: one to five candles
BASE_TIGHT = 0.60                # base candle range vs the recent normal range
BASE_VOL = 2.00                  # base volume vs the recent normal volume
EXIT_RANGE = 2.00                # exit candle range vs normal
EXIT_VOL = 1.50                  # exit candle volume vs normal
EXIT_CLEAR = 1.00                # how far past the base the exit must close,
                                 # measured in base heights
MIN_IMPULSE = 3.00               # how far price ran from the zone afterwards,
                                 # in base heights, before coming back
NEAR = float(env("NEAR", "0.0005"))   # 0.05% counts as "arrived"
LOOKBACK = 20                    # candles forming "normal"
SCAN = 200                       # candles searched per timeframe

STATE_FILE = env("STATE_FILE", "state/seen.json")
CHART_URL = "https://khodadadiparsa11-source.github.io/Chart/"

HOSTS = ["https://data-api.binance.vision", "https://api.binance.com",
         "https://api1.binance.com", "https://api2.binance.com"]

# ---------------------------------------------------------------- plumbing


def get_json(path):
    """Try each Binance host in turn; a blocked or failing one falls through."""
    last = None
    for host in HOSTS:
        try:
            req = urllib.request.Request(host + path,
                                         headers={"User-Agent": "volume-watch"})
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.loads(r.read().decode())
        except Exception as e:      # noqa: BLE001 - any failure means try the next host
            last = e
    raise RuntimeError("all Binance hosts failed: %s" % last)


def klines(symbol, tf, limit=SCAN, start=None, end=None):
    q = "/api/v3/klines?symbol=%s&interval=%s&limit=%d" % (symbol, tf, limit)
    if start is not None:
        q += "&startTime=%d" % start
    if end is not None:
        q += "&endTime=%d" % end
    rows = get_json(q)
    out = []
    for k in rows:
        out.append({
            "t": int(k[0]), "o": float(k[1]), "h": float(k[2]),
            "l": float(k[3]), "c": float(k[4]), "v": float(k[5]),
            "ct": int(k[6]),
        })
    return out


def tg(method, data):
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        return None
    req = urllib.request.Request("https://api.telegram.org/bot%s/%s" % (token, method),
                                 data=data[0], headers=data[1])
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.read()
    except Exception as e:          # noqa: BLE001 - a failed send must not stop the rest
        print("telegram %s failed: %s" % (method, e))
        return None


def send_text(text):
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not os.environ.get("TELEGRAM_TOKEN") or not chat:
        print("no telegram credentials; would have sent:\n" + text)
        return
    body = urllib.parse.urlencode({
        "chat_id": chat, "text": text,
        "parse_mode": "HTML", "disable_web_page_preview": "true",
    }).encode()
    tg("sendMessage", (body, {"Content-Type": "application/x-www-form-urlencoded"}))


def send_photo(png, caption):
    """sendPhoto is multipart/form-data; the standard library has no builder."""
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not os.environ.get("TELEGRAM_TOKEN") or not chat or not png:
        send_text(caption)
        return
    b = "----zone%d" % int(time.time() * 1000)
    out = io.BytesIO()

    def field(name, value):
        out.write(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                   % (b, name, value)).encode())

    field("chat_id", chat)
    field("caption", caption)
    field("parse_mode", "HTML")
    out.write(("--%s\r\nContent-Disposition: form-data; name=\"photo\"; "
               "filename=\"zone.png\"\r\nContent-Type: image/png\r\n\r\n" % b).encode())
    out.write(png)
    out.write(("\r\n--%s--\r\n" % b).encode())
    tg("sendPhoto", (out.getvalue(),
                     {"Content-Type": "multipart/form-data; boundary=%s" % b}))


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:               # noqa: BLE001 - a missing or corrupt state starts fresh
        return {"zones": {}, "symbol_last": {}}


def save_state(st):
    cutoff = time.time() - 7 * 86400
    st["zones"] = {k: v for k, v in st["zones"].items() if v > cutoff}
    d = os.path.dirname(STATE_FILE)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(st, f)


# ---------------------------------------------------------------- detection


def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def find_zones(ks, tf):
    """Base -> exit -> untouched since. Returns the zones still live."""
    n = len(ks)
    zones = []
    rng = [k["h"] - k["l"] for k in ks]
    vol = [k["v"] for k in ks]

    for i in range(LOOKBACK + MAX_BASE, n - 2):     # i = last base candle
        # "Normal" is measured from the candles BEFORE the widest base that
        # could end here. Measuring it up to i would fold the quiet base into
        # its own yardstick and make every base look less tight than it is.
        w = i - MAX_BASE
        nrng = mean(rng[w - LOOKBACK:w])
        nvol = mean(vol[w - LOOKBACK:w])
        if nrng <= 0 or nvol <= 0:
            continue

        # How many tight candles run back from i. One past the maximum is
        # counted on purpose: a longer quiet stretch is a range where price has
        # settled, not a base where it is being held still, and it is rejected
        # outright rather than trimmed to fit.
        run = 0
        j = i
        while j > 0 and rng[j] <= BASE_TIGHT * nrng and run <= MAX_BASE:
            run += 1
            j -= 1
        if run < MIN_BASE or run > MAX_BASE:
            continue

        base = ks[i - run + 1:i + 1]
        top = max(k["h"] for k in base)
        bot = min(k["l"] for k in base)
        height = top - bot
        if height <= 0:
            continue

        bvol = sum(k["v"] for k in base) / (run * nvol)
        if bvol < BASE_VOL:
            continue                                 # quiet base: nothing filled

        ex = ks[i + 1]
        exr = (ex["h"] - ex["l"]) / nrng
        exv = ex["v"] / nvol
        if exr < EXIT_RANGE or exv < EXIT_VOL:
            continue

        if ex["c"] >= top + EXIT_CLEAR * height:
            side = "demand"
        elif ex["c"] <= bot - EXIT_CLEAR * height:
            side = "supply"
        else:
            continue                                 # it did not really leave

        # Spent zones are dropped, not alerted: the candles after the exit must
        # not have traded back into the band. The newest candle is excluded --
        # that touch is the alert itself.
        spent = False
        run_far = 0.0
        for k in ks[i + 2:n - 1]:
            if k["l"] <= top and k["h"] >= bot:
                spent = True
                break
            if side == "demand" and k["c"] < bot:
                spent = True
                break
            if side == "supply" and k["c"] > top:
                spent = True
                break
            far = (k["h"] - top) if side == "demand" else (bot - k["l"])
            run_far = max(run_far, far / height)
        if spent:
            continue

        # A zone that never moved price is a zone with nothing behind it. This
        # one has to have already produced a run of several base heights before
        # price came back to it -- it has shown once that it can turn price.
        imp = max(run_far, ((ex["c"] - top) if side == "demand" else (bot - ex["c"])) / height)
        if imp < MIN_IMPULSE:
            continue

        zones.append({
            "tf": tf, "side": side, "top": top, "bot": bot,
            "start": i - run + 1, "exit": i + 1, "bars": run,
            "formed": base[0]["t"], "bvol": bvol, "exr": exr, "exv": exv,
            "imp": imp,
            "tight": mean(rng[i - run + 1:i + 1]) / nrng,
        })
    return zones


def price_arrived(z, price):
    """Has price come back to the edge of the zone without breaking through?"""
    pad = z["top"] * NEAR
    return z["bot"] - pad <= price <= z["top"] + pad


def overlaps(a, b):
    return a["side"] == b["side"] and a["bot"] <= b["top"] and b["bot"] <= a["top"]


def base_delta(symbol, z):
    """Aggressor split inside the base, read from a finer timeframe.

    Every trade would be exact and would cost dozens of requests per zone. One
    request of finer candles, each counted toward the side its own body points,
    is close enough to tell which way the flow leaned. It is called approximate
    everywhere it is shown.
    """
    fine = FINER[z["tf"]]
    try:
        rows = klines(symbol, fine, limit=1000,
                      start=z["formed"], end=z["formed"] + z["span"])
    except Exception as e:          # noqa: BLE001 - the score simply misses this bonus
        print("delta failed for %s: %s" % (symbol, e))
        return 0.0
    buy = sell = 0.0
    for k in rows:
        if k["v"] <= 0:
            continue
        if k["c"] < k["o"]:
            sell += k["v"]
        else:
            buy += k["v"]
    traded = buy + sell
    return (buy - sell) / traded if traded else 0.0


def score(z, agree, delta_ratio):
    s = 0.0
    s += 3 if z["bvol"] >= 3.0 else 2 if z["bvol"] >= 2.0 else 1
    s += 2 if z["tight"] <= 0.50 else 1
    s += 2 if z["exr"] >= 2.5 else 1
    s += TF_WEIGHT[z["tf"]]
    s += min(2, agree)
    # Flow inside the base pointing the opposite way from the exit: sellers
    # were being absorbed before the rise, or buyers before the fall.
    if delta_ratio is not None:
        if z["side"] == "demand" and delta_ratio <= -0.10:
            s += 2
        elif z["side"] == "supply" and delta_ratio >= 0.10:
            s += 2
    return min(10.0, s)


# ---------------------------------------------------------------- the image


def draw(symbol, ks, z, pts, agree_tfs):
    """Candles, volume, and a box around the zone. Returns PNG bytes or None."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
    except Exception as e:          # noqa: BLE001 - text still goes out without it
        print("no matplotlib: %s" % e)
        return None

    i0 = max(0, z["start"] - 40)
    view = ks[i0:]
    if len(view) < 5:
        return None
    zs = z["start"] - i0

    bg, up, dn = "#0e1116", "#26a69a", "#ef5350"
    fig, (ax, av) = plt.subplots(
        2, 1, figsize=(9, 6.2), dpi=130, sharex=True,
        gridspec_kw={"height_ratios": [4, 1], "hspace": 0.06})
    fig.patch.set_facecolor(bg)

    for a in (ax, av):
        a.set_facecolor(bg)
        a.tick_params(colors="#8892a0", labelsize=8)
        for sp in a.spines.values():
            sp.set_color("#242a33")
        a.grid(color="#1b2029", linewidth=0.6)
        a.set_axisbelow(True)

    for i, k in enumerate(view):
        col = up if k["c"] >= k["o"] else dn
        ax.plot([i, i], [k["l"], k["h"]], color=col, linewidth=0.8, zorder=2)
        lo, hi = min(k["o"], k["c"]), max(k["o"], k["c"])
        ax.add_patch(Rectangle((i - 0.32, lo), 0.64, max(hi - lo, (k["h"] - k["l"]) * 0.002),
                               facecolor=col, edgecolor=col, linewidth=0.5, zorder=3))
        av.bar(i, k["v"], width=0.64, color=col, alpha=0.55, zorder=2)

    # the zone: drawn from its base and carried to the right edge, because it is
    # a price band that stays live until price comes back to it
    edge = "#4dd0e1" if z["side"] == "demand" else "#ffa726"
    ax.add_patch(Rectangle((zs - 0.5, z["bot"]), len(view) - zs, z["top"] - z["bot"],
                           facecolor=edge, alpha=0.13, edgecolor=edge,
                           linewidth=1.6, zorder=4))
    # The number sits at the right edge, clear of the candles: a tight base is
    # a thin band and a label on top of it hides the very thing it points at.
    ax.annotate("%d/10" % round(pts), xy=(len(view) - 1, z["top"]),
                xytext=(-4, 7), textcoords="offset points", ha="right",
                color=bg, fontsize=11, fontweight="bold", zorder=6,
                bbox=dict(boxstyle="round,pad=0.3", fc=edge, ec="none"))

    last = view[-1]["c"]
    ax.axhline(last, color="#8892a0", linewidth=0.7, linestyle=(0, (4, 3)), zorder=5)

    ax.set_title("%s   %s   %s   score %d/10%s"
                 % (symbol, z["tf"], z["side"].upper(), round(pts),
                    ("   +" + ",".join(agree_tfs)) if agree_tfs else ""),
                 color="#e6edf3", fontsize=12, fontweight="bold", loc="left", pad=10)
    ax.set_ylabel("price", color="#8892a0", fontsize=8)
    av.set_ylabel("vol", color="#8892a0", fontsize=8)
    av.set_xlabel("last %d candles" % len(view), color="#8892a0", fontsize=8)
    ax.set_xlim(-1, len(view))

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=bg, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


# ---------------------------------------------------------------- per symbol


def fmt(p):
    if p >= 1000:
        return "%.1f" % p
    if p >= 1:
        return "%.3f" % p
    return "%.6f" % p


def examine(symbol, state, now_ms):
    """Returns (zone, score, agreeing timeframes, candles) or None."""
    found = {}
    price = None
    for tf in TFS:
        ks = klines(symbol, tf)
        if len(ks) < LOOKBACK + MAX_BASE + 5:
            continue
        if price is None:
            price = ks[-1]["c"]
        found[tf] = (ks, find_zones(ks, tf))
    if price is None:
        return None

    best = None
    for tf, (ks, zs) in found.items():
        if tf not in ALERT_TFS:
            continue
        for z in zs:
            if not price_arrived(z, price):
                continue
            z["span"] = (z["exit"] - z["start"] + 1) * (ks[1]["t"] - ks[0]["t"])
            # Required, not a bonus: a level only one timeframe can see is a
            # level only one timeframe will respect.
            agree = [otf for otf, (_, ozs) in found.items()
                     if otf != tf and any(overlaps(z, o) for o in ozs)]
            if not agree:
                continue
            pts = score(z, len(agree), None)
            if pts + 2 < MIN_SCORE:          # even a perfect delta cannot save it
                continue
            if best is None or pts > best[1]:
                best = (z, pts, agree, ks)

    if best is None:
        return None

    z, pts, agree, ks = best
    d = base_delta(symbol, z)
    # Also required: the flow inside the base must have pointed the OPPOSITE way
    # from the exit. Sellers were being filled and price still rose -- that is
    # the difference between a level someone defended and a level price passed.
    if (z["side"] == "demand" and d > -0.10) or (z["side"] == "supply" and d < 0.10):
        print("%s %s zone: flow agreed with the exit, skipped" % (symbol, z["tf"]))
        return None
    pts = score(z, len(agree), d)
    if pts < MIN_SCORE:
        return None
    z["delta"] = d

    key = "%s|%s|%s|%d" % (symbol, z["tf"], z["side"], z["formed"])
    if key in state["zones"]:
        return None
    last = state["symbol_last"].get(symbol, 0)
    if now_ms / 1000 - last < COOLDOWN_MIN * 60:
        print("%s in cooldown" % symbol)
        return None

    state["zones"][key] = time.time()
    state["symbol_last"][symbol] = now_ms / 1000
    return (z, pts, agree, ks, price)


def caption(symbol, z, pts, agree, price):
    kind = "تقاضا (خرید)" if z["side"] == "demand" else "عرضه (فروش)"
    arrow = "🟦" if z["side"] == "demand" else "🟧"
    d = z.get("delta", 0.0)
    flow = "خریدار" if d > 0 else "فروشنده"
    return (
        "{a} <b>{sym}</b> — {kind}\n"
        "امتیاز <b>{pts}/10</b> · تایم‌فریم <b>{tf}</b>\n\n"
        "محدوده <code>{bot} — {top}</code>\n"
        "قیمت الان <code>{price}</code> — رسیده به محدوده\n\n"
        "بیس: <b>{bars}</b> کندل، حجم <b>{bvol:.1f}x</b> نرمال، طول <b>{tight:.0%}</b> نرمال\n"
        "خروج: طول <b>{exr:.1f}x</b>، حجم <b>{exv:.1f}x</b>\n"
        "حرکتی که از این محدوده گرفت: <b>{imp:.1f} برابر</b> ارتفاع محدوده\n"
        "جریان داخل بیس: <b>{flow}</b> ({dp:.0f}٪) — تقریبی\n"
        "{agree}\n"
        "<a href=\"{url}\">باز کردن چارت</a>\n\n"
        "<i>امتیاز یک رتبه‌بندی است، نه احتمال. هیچ بک‌تستی پشتش نیست.</i>"
    ).format(a=arrow, sym=symbol, kind=kind, pts=int(round(pts)), tf=z["tf"],
             bot=fmt(z["bot"]), top=fmt(z["top"]), price=fmt(price),
             bars=z["bars"], bvol=z["bvol"], tight=z["tight"],
             exr=z["exr"], exv=z["exv"], imp=z["imp"], flow=flow, dp=abs(d) * 100,
             agree=("تایم‌فریم‌های هم‌جهت: <b>%s</b>" % ", ".join(agree))
                   if agree else "بدون هم‌پوشانی با تایم‌فریم دیگر",
             url=CHART_URL)


def main():
    if os.environ.get("TEST") == "1":
        send_text("✅ ربات وصل است.\nنمادها: %s\nهشدار روی: %s (۵م فقط برای تایید)\n"
                  "حداقل امتیاز: %g/10\nروزها ممکنه ساکت باشه — همینه که قرار بود باشه."
                  % (", ".join(SYMBOLS), ", ".join(ALERT_TFS), MIN_SCORE))
        return

    state = load_state()
    now_ms = time.time() * 1000
    sent = 0
    for sym in SYMBOLS:
        if sent >= MAX_PER_RUN:
            print("run cap reached")
            break
        try:
            hit = examine(sym, state, now_ms)
        except Exception as e:      # noqa: BLE001 - one bad symbol must not stop the rest
            print("%s failed: %s" % (sym, e))
            continue
        if not hit:
            print("%s quiet" % sym)
            continue
        z, pts, agree, ks, price = hit
        png = draw(sym, ks, z, pts, agree)
        send_photo(png, caption(sym, z, pts, agree, price))
        sent += 1
        print("alerted %s %s %s %.1f" % (sym, z["tf"], z["side"], pts))
    save_state(state)
    print("done, %d alert(s)" % sent)


if __name__ == "__main__":
    main()
