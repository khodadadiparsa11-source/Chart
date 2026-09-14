"""The nightly session report, one symbol at a time.

Sent after the New York close: what each session did, what it left behind, and
which of those levels price has still not come back to -- today and over the
past week.

Only unmitigated items are listed. A gap that filled the same afternoon and a
block price has already traded back through are history, and printing them
would bury the handful of levels that still matter tomorrow. The counts of what
was made and what was consumed are given as one line each, so nothing is hidden,
only ranked.

Every term here is a judgement rather than a formula, so the rule each one was
found by is printed beside it. A name he and I read differently is worse than
no name at all.
"""

import os
import sys
import traceback
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import draw
import feed
import sessions as S
import structure as ST
import tg

TFS = ["5m", "15m", "1h", "4h"]
TF_FA = {"5m": "۵ دقیقه", "15m": "۱۵ دقیقه", "1h": "۱ ساعته", "4h": "۴ ساعته"}

SYMBOLS = [
    ("طلا",        "yahoo",   "GC=F",     "GOLD"),
    ("نزدک",       "yahoo",   "NQ=F",     "NASDAQ"),
    ("داوجونز",    "yahoo",   "YM=F",     "DOW"),
    ("یورو/دلار",  "yahoo",   "EURUSD=X", "EURUSD"),
    ("پوند/دلار",  "yahoo",   "GBPUSD=X", "GBPUSD"),
    ("دلار/ین",    "yahoo",   "USDJPY=X", "USDJPY"),
    ("کیوی/دلار",  "yahoo",   "NZDUSD=X", "NZDUSD"),
    ("بیت‌کوین",   "binance", "BTCUSDT",  "BTCUSDT"),
    ("اتریوم",     "binance", "ETHUSDT",  "ETHUSDT"),
]

ARROW = {"up": "↑", "down": "↓"}


def digits(sym):
    """Enough decimals to read the instrument, without pretending to more."""
    return 5 if "USD=X" in sym and "JPY" not in sym else (3 if "JPY" in sym else 2)


def fmt(p, d):
    return ("%." + str(d) + "f") % p


def analyse(ks, day_start, day_end, sess):
    """Everything the rules find, split into what is still live and what is not."""
    sw = ST.swings(ks)
    evs = ST.breaks(ks, sw)
    obs = ST.order_blocks(ks, evs)
    pb_at = {p["i"] for p in ST.propulsion(obs, ks)}
    gaps = ST.fvgs(ks)
    pools = ST.pools(sw)

    made = {"FVG": 0, "OB": 0, "PB": 0}
    live = []

    for g in gaps:
        if not (day_start <= g["t"] < day_end):
            continue
        made["FVG"] += 1
        if ST.mitigated_at(ks, g["i"], g["bot"], g["top"]) is None:
            live.append({"kind": "FVG", "t": g["t"], "dir": g["dir"],
                         "bot": g["bot"], "top": g["top"],
                         "sess": S.session_of(g["t"], sess)})

    for ob in obs:
        if not (day_start <= ob["t"] < day_end):
            continue
        kind = "PB" if ob["i"] in pb_at else "OB"
        made[kind] += 1
        if ST.mitigated_at(ks, ob["break_i"], ob["bot"], ob["top"]) is None:
            live.append({"kind": kind, "t": ob["t"], "dir": ob["dir"],
                         "bot": ob["bot"], "top": ob["top"],
                         "sess": S.session_of(ob["t"], sess)})

    lq = []
    for p in pools:
        if not (day_start <= p["t"] < day_end):
            continue
        j = ST.swept_at(ks, p["i"], p["price"], p["kind"])
        lq.append({"kind": "LQ", "price": p["price"], "side": p["kind"],
                   "swept": j is not None, "t": p["t"],
                   "sess": S.session_of(p["t"], sess),
                   "note": ("equal %ss - swept" % p["kind"]) if j
                           else ("equal %ss" % p["kind"])})

    day_evs = [e for e in evs if day_start <= e["t"] < day_end]
    # Only breaks up to the close count. Candles after it exist in the feed when
    # the report is rebuilt later, and letting them set the trend would describe
    # a day by what happened after it.
    upto = [e for e in evs if e["t"] < day_end]
    return made, live, lq, day_evs, upto


def trend_of(evs):
    """The direction of the last structure break, and nothing more than that."""
    return evs[-1]["dir"] if evs else None


def lines_for(live, lq, d):
    """The four lists, each item carrying the session it was made in."""
    def rows(kind):
        out = []
        for it in sorted([x for x in live if x["kind"] == kind],
                         key=lambda x: -x["t"]):
            out.append("   <code>%s–%s</code> %s %s"
                       % (fmt(it["bot"], d), fmt(it["top"], d),
                          ARROW[it["dir"]], S.FA.get(it["sess"], "")))
        return out

    parts = []
    for kind, label in (("FVG", "FVG"), ("OB", "OB"),
                        ("PB", "پروپالشن بلاک")):
        r = rows(kind)
        parts.append("<b>%s:</b> %s" % (label, ("%d باز" % len(r)) if r else "ندارد"))
        parts.extend(r)

    if lq:
        parts.append("<b>لیکویدیتی:</b>")
        for it in sorted(lq, key=lambda x: -x["t"]):
            parts.append("   <code>%s</code> %s — %s %s"
                         % (fmt(it["price"], d),
                            "سقف مساوی" if it["side"] == "high" else "کف مساوی",
                            "زده شد" if it["swept"] else "دست‌نخورده",
                            S.FA.get(it["sess"], "")))
    else:
        parts.append("<b>لیکویدیتی:</b> ندارد")
    return parts


def run_symbol(fa, source, sym, en, day):
    sess = S.day_sessions(day)
    day_start, day_end = sess[0][1], sess[-1][2]
    d = digits(sym)

    per_tf = {}
    for tf in TFS:
        ks = feed.candles(source, sym, tf)
        if len(ks) < 60:
            print("%s %s: only %d candles, skipped" % (en, tf, len(ks)))
            continue
        per_tf[tf] = (ks, analyse(ks, day_start, day_end, sess))

    if not per_tf:
        print("%s: no data at all" % en)
        return

    # ---- the header: what the day and each session actually did
    ref = per_tf.get("5m") or per_tf.get("15m") or list(per_tf.values())[0]
    ks_ref = ref[0]
    inday = [k for k in ks_ref if day_start <= k["t"] < day_end]
    if not inday:
        print("%s: no candles inside the trading day" % en)
        return

    head = ["📊 <b>%s</b> — %s" % (fa, S.iran(day_start, "%Y-%m-%d")), ""]
    head.append("سقف/کف روز: <code>%s / %s</code>"
                % (fmt(max(k["h"] for k in inday), d),
                   fmt(min(k["l"] for k in inday), d)))
    for name, a, b in sess:
        part = [k for k in ks_ref if a <= k["t"] < b]
        if part:
            head.append("%s (%s–%s): <code>%s / %s</code>"
                        % (S.FA[name], S.iran(a), S.iran(b),
                           fmt(max(k["h"] for k in part), d),
                           fmt(min(k["l"] for k in part), d)))
    trends = {tf: trend_of(v[1][4]) for tf, v in per_tf.items()}
    big = trends.get("4h") or trends.get("1h")
    head.append("")
    head.append("<b>روند: %s</b>" % ("صعودی ↑" if big == "up" else
                                     "نزولی ↓" if big == "down" else "نامشخص"))
    head.append(" · ".join("%s %s" % (TF_FA[tf], ARROW.get(trends.get(tf), "—"))
                           for tf in TFS if tf in per_tf))
    tg.text("\n".join(head))

    # ---- one message per timeframe
    for tf in TFS:
        if tf not in per_tf:
            continue
        ks, (made, live, lq, day_evs, evs) = per_tf[tf]
        view = [k for k in ks if day_start <= k["t"] < day_end]
        if not view:
            continue
        items = [dict(x) for x in live] + [dict(x) for x in lq]
        for e in day_evs[-6:]:
            items.append({"kind": e["kind"], "t": e["t"], "dir": e["dir"],
                          "price": e["level"]})
        png = draw.render("%s   %s   %s   Iran time"
                          % (en, tf, S.iran(day_start, "%d %b %Y")),
                          view, sess, items)

        last = evs[-1] if evs else None
        cap = ["<b>%s — %s</b>" % (fa, TF_FA[tf]), ""]
        cap.append("<b>روند:</b> %s%s"
                   % ("صعودی ↑" if trends.get(tf) == "up" else
                      "نزولی ↓" if trends.get(tf) == "down" else "نامشخص",
                      ("  (آخرین شکست: %s %s — %s)"
                       % (last["kind"], ARROW[last["dir"]],
                          S.FA.get(S.session_of(last["t"], sess), ""))) if last else ""))
        cap.extend(lines_for(live, lq, d))
        cap.append("")
        cap.append("<i>امروز ساخته شد: %d FVG · %d OB · %d PB — "
                   "بقیه همان روز مصرف شدند.</i>"
                   % (made["FVG"], made["OB"], made["PB"]))
        tg.photo(png, "\n".join(cap))

    # ---- the week: still untouched, nearest to price first
    if "1h" in per_tf:
        ks, _ = per_tf["1h"]
        week_start = day_start - 7 * 86400 * 1000
        price = ks[-1]["c"]
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
                if g["t"] >= week_start and ST.mitigated_at(kks, g["i"], g["bot"], g["top"]) is None:
                    alive.append(("FVG", tf, g["bot"], g["top"], g["dir"], g["t"]))
            for ob in obs:
                if ob["t"] >= week_start and ST.mitigated_at(kks, ob["break_i"], ob["bot"], ob["top"]) is None:
                    alive.append(("PB" if ob["i"] in pb_at else "OB", tf,
                                  ob["bot"], ob["top"], ob["dir"], ob["t"]))
        # A gap on the hourly is the same gap on the four-hour, because the
        # four-hour is folded from it. Printed twice it looks like two levels.
        order = {tf: i for i, tf in enumerate(TFS)}
        alive.sort(key=lambda a: (-order[a[1]], a[2]))
        kept = []
        for it in alive:
            dup = any(k[0] == it[0] and k[4] == it[4]
                      and k[2] <= it[3] and it[2] <= k[3] for k in kept)
            if not dup:
                kept.append(it)
        alive = kept
        alive.sort(key=lambda a: abs((a[2] + a[3]) / 2 - price))
        body = ["🗓 <b>%s — هفت روز گذشته</b>" % fa, "",
                "سطح‌هایی که هنوز دست‌نخورده‌اند، نزدیک‌ترین به قیمت اول:", ""]
        for kind, tf, bot, top, dr, t in alive[:20]:
            body.append("<code>%s–%s</code> %s %s · %s · %s"
                        % (fmt(bot, d), fmt(top, d), ARROW[dr], kind,
                           TF_FA[tf], S.iran(t, "%m-%d")))
        if not alive:
            body.append("هیچ سطح دست‌نخورده‌ای نمانده.")
        view = [k for k in ks if k["t"] >= week_start]
        items = [{"kind": k, "t": t, "dir": dr, "bot": b, "top": tp}
                 for k, tf, b, tp, dr, t in alive[:12]]
        png = draw.render("%s   1h   last 7 days   Iran time" % en, view,
                          S.day_sessions(day), items) if view else None
        if png:
            tg.photo(png, "\n".join(body))
        else:
            tg.text("\n".join(body))


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
