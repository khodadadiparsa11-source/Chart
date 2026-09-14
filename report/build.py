"""The nightly session report, one album per symbol.

Sent after the New York close: what each session left behind that price has not
come back to. One album of five charts -- 5m, 15m, 1h, 4h, then the week --
lowest timeframe first, with the whole symbol summarised on the first caption.

Telegram shows only the first caption under an album and hides the rest behind
a tap, so that caption is the whole message: a tick or a cross per timeframe
and the session highs and lows. Everything else is on the charts, where each
band carries its own price -- a checklist that cannot be traded from would be a
lighter message and a worse one.
"""

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import draw
import feed
import sessions as S
import structure as ST
import tg

TFS = ["5m", "15m", "1h", "4h"]          # the album runs in this order
TF_FA = {"5m": "۵ دقیقه", "15m": "۱۵ دقیقه", "1h": "۱ ساعته", "4h": "۴ ساعته"}
KINDS = ["FVG", "OB", "PB"]

# Two trends, not four. The higher one is read off the four-hour and the lower
# off the fifteen-minute, each falling back one step if that feed is short. The
# timeframe is printed beside the word so it is never a mystery which candles
# said it.
HIGH_TF = ["4h", "1h"]
LOW_TF = ["15m", "5m"]

WEEK_DRAW = ["1h", "4h"]                 # a 5m gap is a hairline on a week

SYMBOLS = [
    # Gold is XAUT, not the COMEX future. He held the two charts side by side
    # and saw it: GC=F runs about forty dollars above his screen, because a
    # future carries the interest to its delivery date. Forty dollars is fatal
    # for a report whose entire output is levels to leave limit orders at.
    # Measured against the price on his phone: GC=F +41.03, PAXG +6.45,
    # XAUT +2.35. It is a token rather than spot, and it trades at the weekend
    # when spot does not -- but two dollars is a chart he can act on and
    # forty-one is not.
    ("طلا",        "binance", "XAUTUSDT", "GOLD"),
    ("نزدک",       "yahoo",   "NQ=F",     "NASDAQ"),
    ("داوجونز",    "yahoo",   "YM=F",     "DOW"),
    ("یورو/دلار",  "yahoo",   "EURUSD=X", "EURUSD"),
    ("پوند/دلار",  "yahoo",   "GBPUSD=X", "GBPUSD"),
    ("دلار/ین",    "yahoo",   "USDJPY=X", "USDJPY"),
    ("کیوی/دلار",  "yahoo",   "NZDUSD=X", "NZDUSD"),
    ("بیت‌کوین",   "binance", "BTCUSDT",  "BTCUSDT"),
    ("اتریوم",     "binance", "ETHUSDT",  "ETHUSDT"),
]

TICK, CROSS = "✅", "❌"


def digits(sym):
    """Enough decimals to read the instrument, without pretending to more."""
    return 5 if "USD=X" in sym and "JPY" not in sym else (3 if "JPY" in sym else 2)


def fmt(p, d):
    return ("%." + str(d) + "f") % p


def analyse(ks, day_start, day_end):
    """What the day made and price has not traded back into, plus its breaks.

    The breaks are kept because they are what defines an order block and what
    the trend is read from -- they are no longer drawn or named on the chart.
    """
    sw = ST.swings(ks)
    evs = ST.breaks(ks, sw)
    obs = ST.order_blocks(ks, evs)
    pb_at = {p["i"] for p in ST.propulsion(obs, ks)}

    live, gone = [], []

    def sort_it(kind, start_i, t, direction, bot, top):
        j = ST.mitigated_at(ks, start_i, bot, top)
        if j is None:
            live.append({"kind": kind, "t": t, "dir": direction,
                         "bot": bot, "top": top})
        else:
            gone.append({"kind": kind, "t": t, "dir": direction,
                         "bot": bot, "top": top, "hit": ks[j]["t"],
                         "depth": ST.mitigation_depth(ks[j], bot, top, direction)})

    for g in ST.fvgs(ks):
        if day_start <= g["t"] < day_end:
            sort_it("FVG", g["i"], g["t"], g["dir"], g["bot"], g["top"])
    for ob in obs:
        if day_start <= ob["t"] < day_end:
            sort_it("PB" if ob["i"] in pb_at else "OB", ob["break_i"],
                    ob["t"], ob["dir"], ob["bot"], ob["top"])

    # Breaks after the close exist in the feed when the report is rebuilt later,
    # and letting them set the trend would describe a day by what followed it.
    return live, [e for e in evs if e["t"] < day_end], gone


def trend_at(per_tf, prefer):
    """The direction of the last structure break, on the first feed that has one."""
    for tf in prefer:
        if tf in per_tf and per_tf[tf][1][1]:
            return tf, per_tf[tf][1][1][-1]["dir"]
    return None, None


def word(direction):
    return ("صعودی ↑" if direction == "up" else
            "نزولی ↓" if direction == "down" else "نامشخص")


def flags(live):
    return {k: any(x["kind"] == k for x in live) for k in KINDS}


def week_levels(per_tf, week_start):
    """Everything from the past seven days that is still untouched.

    Collected from every timeframe, then collapsed: a gap on the hourly is the
    same gap on the four-hour, because the four-hour is folded from it, and
    printed twice it reads as two levels.
    """
    alive = []
    for tf in TFS:
        if tf not in per_tf:
            continue
        kks = per_tf[tf][0]
        sw = ST.swings(kks)
        evs = ST.breaks(kks, sw)
        obs = ST.order_blocks(kks, evs)
        pb_at = {p["i"] for p in ST.propulsion(obs, kks)}
        for g in ST.fvgs(kks):
            if (g["t"] >= week_start
                    and ST.mitigated_at(kks, g["i"], g["bot"], g["top"]) is None):
                alive.append(("FVG", tf, g["bot"], g["top"], g["dir"], g["t"]))
        for ob in obs:
            if (ob["t"] >= week_start
                    and ST.mitigated_at(kks, ob["break_i"], ob["bot"], ob["top"]) is None):
                alive.append(("PB" if ob["i"] in pb_at else "OB", tf,
                              ob["bot"], ob["top"], ob["dir"], ob["t"]))
    order = {tf: i for i, tf in enumerate(TFS)}
    alive.sort(key=lambda a: (-order[a[1]], a[2]))
    kept = []
    for it in alive:
        if not any(k[0] == it[0] and k[4] == it[4]
                   and k[2] <= it[3] and it[2] <= k[3] for k in kept):
            kept.append(it)
    return kept


def run_symbol(fa, source, sym, en, day):
    sess = S.day_sessions(day)
    day_start, day_end = sess[0][1], sess[-1][2]
    d = digits(sym)
    money = lambda p: fmt(p, d)                     # noqa: E731 - read as a format

    per_tf = {}
    for tf in TFS:
        # Nothing past the close is looked at, by anything. The charts end at
        # the close, so the judgement has to end there too: a level that
        # survived the whole day was being retired by candles from days after
        # it -- three days, for a coin that trades at the weekend -- and he was
        # reading a chart where nothing had gone near it. The picture and the
        # words have to be looking at the same window or one of them is lying.
        ks = [k for k in feed.candles(source, sym, tf) if k["t"] < day_end]
        if len(ks) < 60:
            print("%s %s: only %d candles, skipped" % (en, tf, len(ks)))
            continue
        per_tf[tf] = (ks, analyse(ks, day_start, day_end))
    if not per_tf:
        print("%s: no data at all" % en)
        return

    ks_ref = (per_tf.get("5m") or per_tf.get("15m") or list(per_tf.values())[0])[0]
    inday = [k for k in ks_ref if day_start <= k["t"] < day_end]
    if not inday:
        print("%s: no candles inside the trading day" % en)
        return

    # ---- one chart per timeframe, lowest first
    shots, rows = [], []
    for tf in TFS:
        if tf not in per_tf:
            continue
        ks, (live, _, gone) = per_tf[tf]
        view = [k for k in ks if day_start <= k["t"] < day_end]
        if not view:
            continue
        items = [dict(x, fmt=money) for x in live]
        shots.append(draw.render("%s   %s   %s   Iran time"
                                 % (en, tf, S.iran(day_start, "%d %b %Y")),
                                 view, sess, items))
        rows.append((tf, flags(live)))

        # What was dropped and how deeply, to the log. "Mitigated" currently
        # means a single touch anywhere in the band, which is a choice and not
        # a fact -- these depths are the only way to see whether it is throwing
        # away levels price merely grazed. Shallow numbers here mean the rule
        # is too strict; numbers near 1.0 mean the levels really were eaten.
        for g in gone:
            print("  %s %s dropped %s %s-%s made %s hit %s depth %.0f%%"
                  % (en, tf, g["kind"], money(g["bot"]), money(g["top"]),
                     S.iran(g["t"], "%m-%d %H:%M"),
                     S.iran(g["hit"], "%m-%d %H:%M"), g["depth"] * 100))

    # ---- and the week behind it, last in the album
    if "1h" in per_tf:
        ks = per_tf["1h"][0]
        week_start = day_start - 7 * 86400 * 1000
        price = ks[-1]["c"]
        alive = week_levels(per_tf, week_start)
        drawn = sorted([a for a in alive if a[1] in WEEK_DRAW],
                       key=lambda a: abs((a[2] + a[3]) / 2 - price))[:16]
        # The row is read off what is DRAWN, never off the wider list it was
        # chosen from. The week's chart carries hourly and four-hourly levels
        # only, so a tick taken from the full list promised a propulsion block
        # that was found on the five-minute chart and deliberately not drawn --
        # he looked for it and it was not there. Whatever the picture shows is
        # what the checklist may claim, including anything the cap trims.
        rows.append(("7d", {k: any(a[0] == k for a in drawn) for k in KINDS}))
        view = [k for k in ks if k["t"] >= week_start]
        if view:
            items = [{"kind": k, "t": t, "dir": dr, "bot": b, "top": tp,
                      "tf": tf, "fmt": money}
                     for k, tf, b, tp, dr, t in drawn]
            shots.append(draw.render("%s   1h   last 7 days   Iran time" % en,
                                     view, S.day_sessions(day), items))

    # ---- the one caption the album will show
    htf, hd = trend_at(per_tf, HIGH_TF)
    ltf, ld = trend_at(per_tf, LOW_TF)
    cap = ["📊 <b>%s</b> — %s" % (fa, S.iran(day_start, "%Y-%m-%d")), ""]
    # The close, on its own line, so a feed drifting from the chart he reads is
    # visible the same night instead of months later. The whole report was
    # built on a gold future forty dollars above his screen and nothing in it
    # said so; one number he can glance at is the guard against that happening
    # again on any of the nine.
    cap.append("بسته شدن روز: <code>%s</code>" % money(inday[-1]["c"]))
    cap.append("روند تایم بالا (%s): <b>%s</b>" % (htf or "—", word(hd)))
    cap.append("روند تایم پایین (%s): <b>%s</b>" % (ltf or "—", word(ld)))
    cap.append("")
    cap.append("<pre>" + "\n".join(
        "%-4s FVG %s  OB %s  PB %s"
        % (tf, TICK if f["FVG"] else CROSS,
           TICK if f["OB"] else CROSS, TICK if f["PB"] else CROSS)
        for tf, f in rows) + "</pre>")
    cap.append("سقف/کف روز: <code>%s / %s</code>"
               % (money(max(k["h"] for k in inday)),
                  money(min(k["l"] for k in inday))))
    for name, a, b in sess:
        part = [k for k in ks_ref if a <= k["t"] < b]
        if part:
            cap.append("%s: <code>%s / %s</code>"
                       % (S.FA[name], money(max(k["h"] for k in part)),
                          money(min(k["l"] for k in part))))

    tg.album(shots, "\n".join(cap))


def main():
    day = S.last_closed_day()
    only = os.environ.get("ONLY", "").strip()
    tg.text("🌙 <b>گزارش پایان روز</b> — %s" % S.iran(
        S.day_sessions(day)[0][1], "%Y-%m-%d"))
    for fa, source, sym, en in SYMBOLS:
        if only and only.upper() not in (sym.upper(), en.upper()):
            continue
        try:
            run_symbol(fa, source, sym, en, day)
        except Exception as e:          # noqa: BLE001 - one symbol must not stop the rest
            print("%s failed: %s" % (en, e))
            traceback.print_exc()
    print("done")


if __name__ == "__main__":
    main()
