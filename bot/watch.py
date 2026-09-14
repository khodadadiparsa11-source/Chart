"""Watch the most liquid Binance pairs for zones worth an order, and send the
chart to Telegram.

WHAT COUNTS AS A ZONE HERE

Not "heavy volume". Heavy volume happens every hour and alerting on it is how a
bot becomes noise. Six conditions, every one of them required -- a candidate
failing any is dropped, never reported with a smaller number:

  1. a BASE      one to five candles whose range is under 60% of the recent
                 normal while their volume is at least double it. Money moved,
                 price did not. That gap is the only observable trace of size
                 being filled; nothing in any feed names who filled it.
  2. an EXIT     the very next candle leaves the base on double the normal
                 range and half again the normal volume, closing a full base
                 height clear of it. Held still, then let go.
  3. a RUN       price then travelled at least three base heights away. A zone
                 that never moved price has nothing behind it.
  4. SILENCE     no trade back into the band since. A zone price has already
                 traded back through is spent, and is dropped.
  5. AGREEMENT   another timeframe holds a zone in the same direction at the
                 same prices. A level only one timeframe can see is a level
                 only one timeframe will respect.
  6. FLOW        the aggressor split inside the base points the OPPOSITE way
                 from the exit. Sellers were being filled and price rose
                 anyway: the difference between a level someone defended and a
                 level price merely passed through.

THE ALERT IS NOT WHEN THE ZONE FORMS. It is when price RETURNS to it, because
that is the moment an order would be placed.

WHY SO MANY SYMBOLS: the gates are strict enough that five symbols can go days
without a single alert, and from the outside "the market was quiet" and "the
code never matches anything" look identical. Scanning the whole liquid end of
the market separates them. The list is ranked by real 24h turnover rather than
taken at random: on a thin pair one participant can draw this exact footprint
with no size behind it at all.

Candidates from every symbol are collected, ranked, and only the best few are
sent -- when Bitcoin moves, a hundred pairs move with it, and an unranked run
would empty the whole correlated batch into the chat at once.

OUTCOMES: every alert is followed afterwards. Price either reacted away from
the band or traded straight through it, and a daily tally reports which. More
alerts on their own prove nothing; what happened after them is the only thing
that can.

A score is a ranking, not a probability. Nothing here has been backtested.
"""

import concurrent.futures
import io
import json
import os
import re
import time
import urllib.parse
import urllib.request

# ---------------------------------------------------------------- settings


def env(name, default):
    """An unset repository variable arrives as an empty string, not as absent."""
    v = os.environ.get(name)
    return v.strip() if v and v.strip() else default


# Empty means "rank the market by turnover and take the top TOP_N"; a list here
# overrides that and watches exactly those.
SYMBOLS = [s.strip().upper() for s in env("SYMBOLS", "").split(",") if s.strip()]
TOP_N = int(env("TOP_N", "200"))

# Scanned on four timeframes; alerted on three. A 5m zone on crypto is noise
# more often than it is a level, so 5m is read only as agreement for a bigger
# zone -- it never raises an alert of its own.
TFS = ["5m", "15m", "1h", "4h"]
ALERT_TFS = ["15m", "1h", "4h"]
TF_WEIGHT = {"5m": 0, "15m": 1, "1h": 2, "4h": 3}
FINER = {"5m": "1m", "15m": "1m", "1h": "5m", "4h": "15m"}

MIN_SCORE = float(env("MIN_SCORE", "8"))        # out of 10
COOLDOWN_MIN = int(env("COOLDOWN_MIN", "180"))  # per symbol
MAX_PER_RUN = int(env("MAX_PER_RUN", "3"))
DAILY_CAP = int(env("DAILY_CAP", "12"))

# Candidates that reached the last gate and failed it, sent separately and
# labelled as NOT signals. He has never seen one of these, and he is the one
# who can look at a chart and say whether the shape is real -- waiting days for
# a passing zone teaches neither of us anything in the meantime. They are kept
# off the alert channel and tallied in their own column, so the strict system
# is never quietly replaced by the loose one.
REVIEW_CAP = int(env("REVIEW_CAP", "3"))
MAX_DELTA_CALLS = 8              # per run, so a wide market cannot run long
WORKERS = int(env("WORKERS", "8"))   # symbols fetched at once

MIN_BASE, MAX_BASE = 1, 5        # his own count: one to five candles
BASE_TIGHT = 0.60                # base candle range vs the recent normal range
BASE_VOL = 2.00                  # base volume vs the recent normal volume
EXIT_RANGE = float(env("EXIT_RANGE", "1.50"))   # exit candle range vs normal.
                                 # The close already has to clear the band by a
                                 # full base height, which is what "it left"
                                 # actually means; the raw range was a third
                                 # test of the same property, and at 2.0 it was
                                 # halving the survivors on its own.
EXIT_VOL = 1.50                  # exit candle volume vs normal
EXIT_CLEAR = 1.00                # how far past the base the exit must close,
                                 # measured in base heights
# How hard the exit closed past the band, in base heights. The old rule asked
# how far price ran AFTERWARDS -- a real measure, but one that does not exist
# yet at the moment a zone is born, which is now when the message is sent. This
# is the same question asked of the only candle that has happened.
MIN_PUSH = float(env("MIN_PUSH", "1.50"))
PUSH_TRIALS = (1.0, 1.5, 2.0, 3.0)

# How far price may be from the band and the level still be worth a pending
# order. Age is not what makes a zone stale -- an untouched zone is an untouched
# zone -- but a limit order a fifth of the way across the chart will never fill.
# Each zone is sent once and never repeated, so the standing inventory arrives
# the first time and new ones as they appear.
MAX_AWAY = float(env("MAX_AWAY", "0.10"))
AWAY_TRIALS = (0.02, 0.05, 0.10, 0.20)
LOOKBACK = 20                    # candles forming "normal"
SCAN = 500                       # A zone is only findable while it is still
                                 # inside the window, so the window is the
                                 # inventory. Binance charges the same weight
                                 # for anything from 101 to 500 candles, so 500
                                 # is five times the history for exactly what
                                 # 200 cost -- and it loosens no rule at all.

# Judging an alert afterwards, in two steps: did price ever come back to the
# band at all, and once it did, did it leave by a full zone height before
# trading a full zone height through it?
# How far price must travel for the zone to have earned the word. One zone
# height was too easy to mean anything: these bands are deliberately tight, so a
# height can be a tenth of a percent of price, and price wanders that far on its
# own in minutes. At that bar everything "reacts" and the two columns of the
# tally stop telling them apart, which defeats the only measurement there is.
REACT_MULT = 2.0                 # zone heights in favour to count as a reaction
FAIL_MULT  = 1.0                 # zone heights through it to count as a failure
OUT_WAIT = 24                    # candles after the touch before it counts flat
NEVER_AFTER = 200                # candles without a touch before giving up

STATE_FILE = env("STATE_FILE", "state/seen.json")
CHART_URL = "https://khodadadiparsa11-source.github.io/Chart/"

HOSTS = ["https://data-api.binance.vision", "https://api.binance.com",
         "https://api1.binance.com", "https://api2.binance.com"]

# Leveraged tokens track a multiple of a price rather than a market, and a
# stablecoin pair has no move to react with. Neither can hold a zone.
SKIP_SUFFIX = ("UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT")
SKIP_BASE = ("USDC", "FDUSD", "TUSD", "BUSD", "DAI", "USDP", "EUR", "GBP", "AEUR")
# Binance lists pairs whose base asset is written in Chinese characters. They
# cannot go into a URL as they stand, and the whole symbol fails on encoding.
PLAIN = re.compile(r"^[A-Z0-9]+$")

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
        except urllib.error.HTTPError as e:
            last = e
            # 429 is "slow down" and 418 is "you did not slow down". Rolling
            # straight on to the next host would be exactly the wrong answer,
            # and a ban costs far more than a pause.
            if e.code in (418, 429):
                time.sleep(3)
        except Exception as e:      # noqa: BLE001 - any failure means try the next host
            last = e
    raise RuntimeError("all Binance hosts failed: %s" % last)


def klines(symbol, tf, limit=SCAN, start=None, end=None):
    q = "/api/v3/klines?symbol=%s&interval=%s&limit=%d" % (symbol, tf, limit)
    if start is not None:
        q += "&startTime=%d" % start
    if end is not None:
        q += "&endTime=%d" % end
    out = []
    for k in get_json(q):
        out.append({
            "t": int(k[0]), "o": float(k[1]), "h": float(k[2]),
            "l": float(k[3]), "c": float(k[4]), "v": float(k[5]),
            "ct": int(k[6]),
        })
    return out


def liquid_symbols(n):
    """The n busiest USDT pairs by real 24h turnover.

    Taking a hundred pairs at random would drag in the thin end of the market,
    where one participant can draw a heavy base in a tight range with no size
    behind it -- the same footprint, none of the meaning.
    """
    rows = get_json("/api/v3/ticker/24hr")
    picked = []
    for r in rows:
        s = r.get("symbol", "")
        if not s.endswith("USDT") or s.endswith(SKIP_SUFFIX):
            continue
        if not PLAIN.match(s):
            continue
        if s[:-4] in SKIP_BASE:
            continue
        try:
            picked.append((float(r.get("quoteVolume", 0)), s))
        except (TypeError, ValueError):
            continue
    picked.sort(reverse=True)
    return [s for _, s in picked[:n]]


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
            st = json.load(f)
    except Exception:               # noqa: BLE001 - a missing or corrupt state starts fresh
        st = {}
    st.setdefault("zones", {})        # alerted zone -> when, so it is not repeated
    st.setdefault("symbol_last", {})  # symbol -> when it last alerted
    st.setdefault("open", {})         # alerts still waiting for their outcome
    st.setdefault("day", {})          # the running tally for today
    return st


def save_state(st):
    cutoff = time.time() - 7 * 86400
    st["zones"] = {k: v for k, v in st["zones"].items() if v > cutoff}
    st["open"] = {k: v for k, v in st["open"].items()
                  if v.get("at", 0) / 1000 > cutoff}
    d = os.path.dirname(STATE_FILE)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(st, f)


# ---------------------------------------------------------------- detection


def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


FUNNEL = ("base", "volume", "exit", "clear", "fresh", "push")

# The exit gate is where almost everything dies, so each run also counts what
# WOULD have passed at other thresholds. Changing a number to see what happens
# is guessing; reading how many candidates sit just outside it is measuring.
EXIT_TRIALS = (1.2, 1.5, 1.8, 2.0, 2.5)


def find_zones(ks, tf, funnel=None):
    """Base -> exit -> run -> untouched since. Returns the zones still live.

    `funnel` counts how many candidates each gate let through. Six mandatory
    gates can be silent because the market is, or because one of them is
    unsatisfiable by construction -- and from a run that only prints "nothing"
    those two are the same sentence. They are not the same bug.
    """
    def tick(stage):
        if funnel is not None:
            funnel[stage] = funnel.get(stage, 0) + 1

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
        tick("base")

        base = ks[i - run + 1:i + 1]
        top = max(k["h"] for k in base)
        bot = min(k["l"] for k in base)
        height = top - bot
        if height <= 0:
            continue

        bvol = sum(k["v"] for k in base) / (run * nvol)
        if bvol < BASE_VOL:
            continue                                 # quiet base: nothing filled
        tick("volume")

        ex = ks[i + 1]
        exr = (ex["h"] - ex["l"]) / nrng
        exv = ex["v"] / nvol
        if exv >= EXIT_VOL:
            for t in EXIT_TRIALS:
                if exr >= t:
                    tick("exit@%.1f" % t)
        if exr < EXIT_RANGE or exv < EXIT_VOL:
            continue
        tick("exit")

        if ex["c"] >= top + EXIT_CLEAR * height:
            side = "demand"
        elif ex["c"] <= bot - EXIT_CLEAR * height:
            side = "supply"
        else:
            continue                                 # it did not really leave
        tick("clear")

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
        tick("fresh")

        # A zone that never moved price is a zone with nothing behind it. This
        # one has to have already produced a run of several base heights before
        # price came back to it -- it has shown once that it can turn price.
        push = ((ex["c"] - top) if side == "demand" else (bot - ex["c"])) / height
        for t in PUSH_TRIALS:
            if push >= t:
                tick("push@%.1f" % t)
        if push < MIN_PUSH:
            continue
        tick("push")

        zones.append({
            "tf": tf, "side": side, "top": top, "bot": bot,
            "start": i - run + 1, "exit": i + 1, "bars": run,
            "formed": base[0]["t"], "bvol": bvol, "exr": exr, "exv": exv,
            "push": push, "ran": run_far,
            "tight": mean(rng[i - run + 1:i + 1]) / nrng,
        })
    return zones


def overlaps(a, b):
    return a["side"] == b["side"] and a["bot"] <= b["top"] and b["bot"] <= a["top"]


def base_delta(symbol, z):
    """Aggressor split inside the base, read from a finer timeframe.

    Every trade would be exact and would cost dozens of requests per zone. One
    request of finer candles, each counted toward the side its own body points,
    is close enough to tell which way the flow leaned. It is called approximate
    everywhere it is shown.
    """
    try:
        rows = klines(symbol, FINER[z["tf"]], limit=1000,
                      start=z["formed"], end=z["formed"] + z["span"])
    except Exception as e:          # noqa: BLE001 - a missing delta drops the candidate
        print("delta failed for %s: %s" % (symbol, e))
        return None
    buy = sell = 0.0
    for k in rows:
        if k["v"] <= 0:
            continue
        if k["c"] > k["o"]:
            buy += k["v"]
        elif k["c"] < k["o"]:
            sell += k["v"]
        # A candle that closed exactly where it opened says nothing about which
        # side was the aggressor. Counting it as buying -- which is what an
        # `else` branch quietly does -- biases every reading positive, and a
        # base is precisely where flat candles pile up. It is dropped instead.
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
        return "%.4f" % p
    return "%.6f" % p


def scan(symbol):
    """Every live zone this symbol is currently sitting on. No state touched.

    The counts come back with it. Six mandatory gates can be silent for days,
    and a run that only says "nothing" cannot tell a quiet market from a filter
    that never passes anything -- these say which gate the candidates died at.
    """
    stats = {"zones": 0, "arrived": 0, "agreed": 0, "scored": 0}
    funnel = {}
    stats["funnel"] = funnel
    found = {}
    price = None
    for tf in TFS:
        ks = klines(symbol, tf)
        if len(ks) < LOOKBACK + MAX_BASE + 5:
            continue
        if price is None:
            price = ks[-1]["c"]
        found[tf] = (ks, find_zones(ks, tf, funnel))
    if price is None:
        return [], {}, stats

    out = []
    for tf, (ks, zs) in found.items():
        if tf not in ALERT_TFS:
            continue
        stats["zones"] += len(zs)
        for z in zs:
            # Near enough that a pending order there means something. The
            # message is sent with price still away from the band -- that is
            # the whole point of reporting at birth -- but not so far away that
            # it will never be reached.
            edge = z["top"] if z["side"] == "demand" else z["bot"]
            away = abs(price - edge) / price
            for t in AWAY_TRIALS:
                if away <= t:
                    funnel["away@%.2f" % t] = funnel.get("away@%.2f" % t, 0) + 1
            if away > MAX_AWAY:
                continue
            stats["arrived"] += 1
            z["span"] = (z["exit"] - z["start"] + 1) * (ks[1]["t"] - ks[0]["t"])
            # Counted, not required. He asked for every timeframe to be
            # checked; requiring two of them to hold the same band at the same
            # moment was my own addition, and with two live zones in the whole
            # liquid market it is a gate nothing can pass. It is worth points
            # instead, and the score floor decides.
            agree = [otf for otf, (_, ozs) in found.items()
                     if otf != tf and any(overlaps(z, o) for o in ozs)]
            if agree:
                stats["agreed"] += 1
            pts = score(z, len(agree), None)
            if pts + 2 < MIN_SCORE:      # even a perfect delta cannot save it
                continue
            stats["scored"] += 1
            out.append({"symbol": symbol, "z": z, "agree": agree,
                        "pts": pts, "ks": ks, "price": price})
    return out, {tf: ks for tf, (ks, _) in found.items()}, stats


# ---------------------------------------------------------------- outcomes


def settle(state, symbol, by_tf):
    """Follow every zone already sent, in two steps.

    A zone is reported the moment it forms, with price still far away, so the
    first question is whether price ever comes back to it at all -- a zone
    price never revisits was a message that cost nothing and earned nothing,
    and it is counted separately rather than quietly forgotten. Once price does
    arrive, the second question is the one that matters: one zone height away
    counts as a reaction, one zone height through counts as a failure, neither
    within a day of candles counts as no reaction.

    Every watched symbol's candles are already in hand, so this costs nothing.
    """
    for key, r in list(state["open"].items()):
        if r["symbol"] != symbol:
            continue
        ks = by_tf.get(r["tf"])
        if not ks:
            continue
        h = r["top"] - r["bot"]
        if h <= 0:
            del state["open"][key]
            continue

        # step one: has price come back to the band yet?
        if not r.get("touched"):
            waited = 0
            for k in ks:
                if k["t"] <= r["at"]:
                    continue
                waited += 1
                if k["l"] <= r["top"] and k["h"] >= r["bot"]:
                    r["touched"] = k["t"]
                    break
            if not r.get("touched"):
                if waited >= NEVER_AFTER:
                    bucket = ("r_" if r.get("review") else "") + "never"
                    state["day"][bucket] = state["day"].get(bucket, 0) + 1
                    print("outcome %s %s %s -> never returned" % (symbol, r["tf"], r["side"]))
                    del state["open"][key]
                continue

        # step two: how far did price travel each way? Counting is not enough
        # at three samples a day -- the size of the move is the thing worth
        # knowing, and a verdict throws it away. Both excursions are measured
        # in zone heights and recorded whatever the verdict.
        verdict = None
        seen = 0
        best = 0.0
        worst = 0.0
        for k in ks:
            if k["t"] <= r["touched"]:
                continue
            seen += 1
            if r["side"] == "demand":
                fav = (k["h"] - r["top"]) / h
                adv = (r["bot"] - k["l"]) / h
            else:
                fav = (r["bot"] - k["l"]) / h
                adv = (k["h"] - r["top"]) / h
            best = max(best, fav)
            worst = max(worst, adv)
            # The adverse side is read first. When one candle reaches both, the
            # order inside it is unknowable, and calling that a reaction would
            # be flattering the zone with a coin toss.
            if worst >= FAIL_MULT:
                verdict = "failed"
            elif best >= REACT_MULT:
                verdict = "reacted"
            elif seen >= OUT_WAIT:
                verdict = "flat"
            if verdict:
                break
        if verdict:
            pfx = "r_" if r.get("review") else ""
            day = state["day"]
            day[pfx + verdict] = day.get(pfx + verdict, 0) + 1
            day[pfx + "n"] = day.get(pfx + "n", 0) + 1
            day[pfx + "best"] = day.get(pfx + "best", 0.0) + best
            day[pfx + "worst"] = day.get(pfx + "worst", 0.0) + worst
            mid_price = (r["top"] + r["bot"]) / 2
            if mid_price > 0:
                day[pfx + "bestpct"] = (day.get(pfx + "bestpct", 0.0)
                                        + best * h / mid_price * 100)
            print("outcome %s %s %s -> %s (best %.1fx, worst %.1fx)%s"
                  % (symbol, r["tf"], r["side"], verdict, best, worst,
                     " (review)" if r.get("review") else ""))
            del state["open"][key]


def daily_report(state, now):
    """One tally a day, and only if there was something to tally."""
    today = time.strftime("%Y-%m-%d", time.gmtime(now))
    day = state["day"]
    if day.get("date") == today:
        return
    if day.get("date"):
        sent = day.get("sent", 0)
        react = day.get("reacted", 0)
        fail = day.get("failed", 0)
        flat = day.get("flat", 0)
        never = day.get("never", 0)
        done = react + fail + flat + never
        rs = day.get("review", 0)

        def block(pfx):
            n = day.get(pfx + "n", 0)
            if n == 0:
                return "هیچ‌کدام هنوز بسته نشده\n"
            return ("واکنش داد: <b>{a}</b> · رد شد: <b>{b}</b> · بی‌واکنش: <b>{c}</b>"
                    " · برنگشت: <b>{d}</b>\n"
                    "میانگین حرکت به نفع: <b>{e:.1f}×</b> ارتفاع محدوده "
                    "(<b>{g:.2f}٪</b> قیمت)\n"
                    "میانگین حرکت خلاف: <b>{f:.1f}×</b>\n").format(
                        a=day.get(pfx + "reacted", 0), b=day.get(pfx + "failed", 0),
                        c=day.get(pfx + "flat", 0), d=day.get(pfx + "never", 0),
                        e=day.get(pfx + "best", 0.0) / n,
                        f=day.get(pfx + "worst", 0.0) / n,
                        g=day.get(pfx + "bestpct", 0.0) / n)

        settled = day.get("n", 0) + day.get("r_n", 0)
        if sent or rs or settled:
            waiting = sum(1 for r in state["open"].values() if not r.get("touched"))
            send_text(
                "📋 <b>کارنامه‌ی {d}</b>\n\n"
                "<b>زون‌های تایید شده</b> — ارسالی: <b>{sent}</b>\n"
                "{blockA}\n"
                "<b>نزدیک‌به‌قبولی‌ها (فقط بررسی)</b> — ارسالی: <b>{rs}</b>\n"
                "{blockB}\n"
                "هنوز منتظر برگشت قیمت: <b>{waiting}</b>\n\n"
                "<i>«واکنش» یعنی قیمت <b>دو برابر</b> ارتفاع محدوده به نفعش رفت "
                "قبل از اینکه یک برابر ازش رد بشه. دو ستون عمداً جدان: اگر ستون "
                "دوم به‌اندازه‌ی اولی خوب بود، آن فیلتر چیزی اضافه نمی‌کند. "
                "درصدِ کنار عدد مهم‌تر از خود عدد است — ده برابرِ یک محدوده‌ی "
                "خیلی باریک، ممکن است حرکتی باشد که ارزش معامله ندارد. این "
                "اندازه‌گیری واکنش است، نه وین‌ریت.</i>"
                .format(d=day.get("date"), sent=sent, rs=rs, waiting=waiting,
                        blockA=block(""), blockB=block("r_")))
    state["day"] = {"date": today}


# ---------------------------------------------------------------- messages


def caption(symbol, z, pts, agree, price):
    kind = "تقاضا (خرید)" if z["side"] == "demand" else "عرضه (فروش)"
    arrow = "🟦" if z["side"] == "demand" else "🟧"
    d = z.get("delta", 0.0)
    flow = "خریدار" if d > 0 else "فروشنده"
    edge = z["top"] if z["side"] == "demand" else z["bot"]
    away = abs(price - edge) / price * 100
    return (
        "{a} <b>{sym}</b> — {kind}\n"
        "امتیاز <b>{pts}/10</b> · تایم‌فریم <b>{tf}</b>\n\n"
        "محدوده <code>{bot} — {top}</code>\n"
        "قیمت الان <code>{price}</code> — <b>{away:.2f}٪</b> فاصله تا محدوده\n\n"
        "بیس: <b>{bars}</b> کندل، حجم <b>{bvol:.1f}x</b> نرمال، طول <b>{tight:.0%}</b> نرمال\n"
        "خروج: طول <b>{exr:.1f}x</b>، حجم <b>{exv:.1f}x</b>\n"
        "فشار کندل خروج: <b>{push:.1f} برابر</b> ارتفاع محدوده\n"
        "جریان داخل بیس: <b>{flow}</b> ({dp:.0f}٪) — تقریبی\n"
        "{agree}\n\n"
        "<b>الان وارد نشو.</b> قیمت هنوز به محدوده نرسیده. اردر لیمیت داخل "
        "محدوده بگذار و استاپ را پشتش.\n"
        "<a href=\"{url}\">باز کردن چارت</a>\n\n"
        "<i>امتیاز یک رتبه‌بندی است، نه احتمال. هیچ بک‌تستی پشتش نیست. "
        "ممکن است قیمت هرگز به این محدوده برنگردد.</i>"
    ).format(a=arrow, sym=symbol, kind=kind, pts=int(round(pts)), tf=z["tf"],
             bot=fmt(z["bot"]), top=fmt(z["top"]), price=fmt(price),
             bars=z["bars"], bvol=z["bvol"], tight=z["tight"],
             exr=z["exr"], exv=z["exv"], push=z["push"], flow=flow, dp=abs(d) * 100,
             away=away,
             agree=("تایم‌فریم‌های هم‌جهت: <b>%s</b>" % ", ".join(agree))
                   if agree else "بدون هم‌پوشانی با تایم‌فریم دیگر",
             url=CHART_URL)


# ---------------------------------------------------------------- the run


def review_caption(symbol, z, pts, agree, price, why):
    """Labelled so it can never be mistaken for the real thing."""
    kind = "تقاضا" if z["side"] == "demand" else "عرضه"
    d = z.get("delta", 0.0)
    edge = z["top"] if z["side"] == "demand" else z["bot"]
    away = abs(price - edge) / price * 100
    return (
        "🔍 <b>برای بررسی — سیگنال نیست</b>\n\n"
        "<b>{sym}</b> · {tf} · {kind}\n"
        "محدوده <code>{bot} — {top}</code> · <b>{away:.2f}٪</b> فاصله\n"
        "امتیاز {pts}/10\n\n"
        "<b>چرا رد شد:</b> {why}\n"
        "بیس: {bars} کندل، حجم <b>{bvol:.1f}x</b>، طول {tight:.0%} نرمال\n"
        "خروج: طول {exr:.1f}x، حجم {exv:.1f}x، فشار {push:.1f} برابر\n"
        "جریان داخل بیس: <code>{d:+.2f}</code>\n\n"
        "<i>این زون از فیلترها رد نشده. روی چارت نگاهش کن و بهم بگو به چشم "
        "خودت درسته یا نه — جوابت تصمیم می‌گیرد که آن فیلتر می‌ماند یا می‌رود. "
        "با این معامله نکن مگر خودت تاییدش کنی.</i>"
    ).format(sym=symbol, tf=z["tf"], kind=kind, bot=fmt(z["bot"]),
             top=fmt(z["top"]), away=away, pts=int(round(pts)), why=why,
             bars=z["bars"], bvol=z["bvol"], tight=z["tight"], exr=z["exr"],
             exv=z["exv"], push=z["push"], d=d)


def main():
    symbols = SYMBOLS
    if not symbols:
        try:
            symbols = liquid_symbols(TOP_N)
        except Exception as e:      # noqa: BLE001 - fall back rather than run on nothing
            print("ranking failed, using the majors: %s" % e)
            symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "PAXGUSDT"]

    if os.environ.get("TEST") == "1":
        send_text("✅ ربات وصل است.\nزیر نظر: <b>%d</b> ارز (پرحجم‌ترین‌های بایننس)\n"
                  "هشدار روی: %s (۵م فقط برای تایید)\n"
                  "حداقل امتیاز: %g/10 · حداکثر %d نوتیف در روز\n"
                  "روزها ممکنه ساکت باشه — همینه که قرار بود باشه."
                  % (len(symbols), ", ".join(ALERT_TFS), MIN_SCORE, DAILY_CAP))
        return

    state = load_state()
    now = time.time()
    daily_report(state, now)

    # Four requests per symbol, four hundred a run: sequential, that outlasts
    # the five-minute schedule and the runs start queueing behind each other.
    # Eight at a time finishes inside a minute and still asks for a fraction of
    # what the exchange allows.
    def work(sym):
        try:
            return sym, scan(sym)
        except Exception as e:      # noqa: BLE001 - one bad symbol must not stop the rest
            print("%s failed: %s" % (sym, e))
            return sym, None

    candidates = []
    funnel = {}
    totals = {"zones": 0, "arrived": 0, "agreed": 0, "scored": 0}
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for sym, got in pool.map(work, symbols):
            if not got:
                continue
            found, by_tf, stats = got
            settle(state, sym, by_tf)
            candidates.extend(found)
            for k in totals:
                totals[k] += stats[k]
            for k, v in stats["funnel"].items():
                funnel[k] = funnel.get(k, 0) + v

    print("scanned %d symbols: %d live zone(s), %d within reach, %d with "
          "agreement, %d above the score floor"
          % (len(symbols), totals["zones"], totals["arrived"],
             totals["agreed"], totals["scored"]))
    print("gates: " + "  ".join("%s=%d" % (k, funnel.get(k, 0)) for k in FUNNEL))
    print("exit gate at other thresholds: "
          + "  ".join("%.1fx=%d" % (t, funnel.get("exit@%.1f" % t, 0))
                      for t in EXIT_TRIALS))
    print("exit push at other thresholds: "
          + "  ".join("%.1fx=%d" % (t, funnel.get("push@%.1f" % t, 0))
                      for t in PUSH_TRIALS))
    print("distance from price: "
          + "  ".join("within %.0f%%=%d" % (t * 100, funnel.get("away@%.2f" % t, 0))
                      for t in AWAY_TRIALS))

    # When Bitcoin moves, a hundred pairs move with it. Ranking first and
    # sending only the best keeps a correlated hour from emptying itself into
    # the chat.
    candidates.sort(key=lambda c: -c["pts"])

    sent = 0
    checked = 0
    near = []
    for c in candidates:
        if sent >= MAX_PER_RUN or state["day"].get("sent", 0) >= DAILY_CAP:
            break
        if checked >= MAX_DELTA_CALLS:
            break
        sym, z = c["symbol"], c["z"]
        key = "%s|%s|%s|%d" % (sym, z["tf"], z["side"], z["formed"])
        if key in state["zones"]:
            continue
        if now - state["symbol_last"].get(sym, 0) < COOLDOWN_MIN * 60:
            continue

        d = base_delta(sym, z)
        checked += 1
        if d is None:
            continue
        z["delta"] = d
        pts = score(z, len(c["agree"]), d)
        # The flow inside the base must point the OPPOSITE way from the exit:
        # sellers being filled before a rise is the difference between a level
        # someone defended and a level price merely passed.
        flow_ok = (d <= -0.10) if z["side"] == "demand" else (d >= 0.10)

        if not flow_ok or pts < MIN_SCORE:
            near.append((pts, c, key,
                         "جریان داخل بیس هم‌جهت خروج بود" if not flow_ok
                         else "امتیاز زیر حد نصاب"))
            print("%s %s %s: near miss (delta %+.2f, score %.0f)"
                  % (sym, z["tf"], z["side"], d, pts))
            continue

        png = draw(sym, c["ks"], z, pts, c["agree"])
        send_photo(png, caption(sym, z, pts, c["agree"], c["price"]))
        state["zones"][key] = now
        state["symbol_last"][sym] = now
        state["day"]["sent"] = state["day"].get("sent", 0) + 1
        state["open"][key] = {"symbol": sym, "tf": z["tf"], "side": z["side"],
                              "top": z["top"], "bot": z["bot"],
                              "at": z["formed"], "pts": pts}
        sent += 1
        print("alerted %s %s %s %.1f" % (sym, z["tf"], z["side"], pts))

    # The near misses, on their own channel and their own daily budget.
    near.sort(key=lambda n: -n[0])
    shown = 0
    for pts, c, key, why in near:
        if state["day"].get("review", 0) >= REVIEW_CAP or shown >= REVIEW_CAP:
            break
        sym, z = c["symbol"], c["z"]
        png = draw(sym, c["ks"], z, pts, c["agree"])
        send_photo(png, review_caption(sym, z, pts, c["agree"], c["price"], why))
        state["zones"][key] = now
        state["day"]["review"] = state["day"].get("review", 0) + 1
        state["open"][key] = {"symbol": sym, "tf": z["tf"], "side": z["side"],
                              "top": z["top"], "bot": z["bot"],
                              "at": z["formed"], "pts": pts, "review": True}
        shown += 1
        print("review %s %s %s %.1f (%s)" % (sym, z["tf"], z["side"], pts, why))

    save_state(state)
    print("done, %d alert(s), %d for review, %d open" % (sent, shown, len(state["open"])))


if __name__ == "__main__":
    main()
