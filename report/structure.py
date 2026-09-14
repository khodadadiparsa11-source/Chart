"""The shapes a trader looks for, each with its rule written down.

Every term here means slightly different things to different traders, so the
rule is stated rather than implied, and the report repeats it beside each item.
A name both of us read differently is worse than no name at all.
"""

SWING_RIGHT = 2          # candles that must print before a swing is confirmed
SWING_LEFT = 2


def swings(ks, left=SWING_LEFT, right=SWING_RIGHT):
    """Highs with nothing higher either side, and the mirror for lows.

    Confirmed `right` candles after the fact, which is not a flaw to work
    around: a high is only a high once the candles after it have failed to beat
    it. Everything downstream waits for that confirmation rather than using a
    level the market had not yet finished making.
    """
    out = []
    for i in range(left, len(ks) - right):
        h, l = ks[i]["h"], ks[i]["l"]
        if (all(ks[j]["h"] <= h for j in range(i - left, i))
                and all(ks[j]["h"] < h for j in range(i + 1, i + right + 1))):
            out.append({"i": i, "t": ks[i]["t"], "price": h, "kind": "high"})
        if (all(ks[j]["l"] >= l for j in range(i - left, i))
                and all(ks[j]["l"] > l for j in range(i + 1, i + right + 1))):
            out.append({"i": i, "t": ks[i]["t"], "price": l, "kind": "low"})
    out.sort(key=lambda s: s["i"])
    return out


def breaks(ks, sw, right=SWING_RIGHT):
    """BOS and CHoCH: a candle CLOSING beyond the last confirmed swing.

    Closing, not wicking. A wick through a level is the market trying; a close
    beyond it is the market succeeding, and the difference is most of what
    separates a break from a sweep.

    The same event is a BOS when it continues the direction already in force and
    a CHoCH when it reverses it -- one test, two names, decided by what came
    before.
    """
    events = []
    trend = 0
    hi = lo = None
    si = 0
    for i in range(len(ks)):
        # A swing enters play only once the candles confirming it have printed,
        # so nothing here knows a level before the chart did.
        while si < len(sw) and sw[si]["i"] + right <= i:
            s = sw[si]
            if s["kind"] == "high":
                hi = s
            else:
                lo = s
            si += 1
        c = ks[i]["c"]
        if hi is not None and c > hi["price"]:
            events.append({"i": i, "t": ks[i]["t"], "dir": "up",
                           "kind": "CHoCH" if trend == -1 else "BOS",
                           "level": hi["price"]})
            trend = 1
            hi = None
        elif lo is not None and c < lo["price"]:
            events.append({"i": i, "t": ks[i]["t"], "dir": "down",
                           "kind": "CHoCH" if trend == 1 else "BOS",
                           "level": lo["price"]})
            trend = -1
            lo = None
    return events


def fvgs(ks):
    """Three candles with a hole in the middle that nothing traded through.

    The one term in this file every trader agrees on: candle one's high below
    candle three's low, or the mirror. No judgement in it at all.
    """
    out = []
    for i in range(2, len(ks)):
        a, c = ks[i - 2], ks[i]
        if c["l"] > a["h"]:
            out.append({"i": i, "t": c["t"], "dir": "up",
                        "bot": a["h"], "top": c["l"]})
        elif c["h"] < a["l"]:
            out.append({"i": i, "t": c["t"], "dir": "down",
                        "bot": c["h"], "top": a["l"]})
    return out


def order_blocks(ks, evs, max_back=60):
    """The last opposite candle before the move that broke structure.

    The break is what makes it an order block. Without it every candle before
    every rally qualifies, and the list becomes noise with a name on it. The
    zone is the whole candle, wick included.
    """
    out = []
    for e in evs:
        j = e["i"]
        stop = max(0, e["i"] - max_back)
        found = None
        while j > stop:
            k = ks[j]
            if e["dir"] == "up" and k["c"] < k["o"]:
                found = j
                break
            if e["dir"] == "down" and k["c"] > k["o"]:
                found = j
                break
            j -= 1
        if found is None:
            continue
        k = ks[found]
        out.append({"i": found, "t": k["t"], "dir": e["dir"],
                    "bot": k["l"], "top": k["h"], "vol": k["v"],
                    "break_i": e["i"], "break_kind": e["kind"]})
    return out


def propulsion(obs, ks=None, within=120):
    """An order block landing on a RECENT one facing the same way.

    "Recent" is the whole point and was missing at first: with weeks of candles
    in hand, almost every block eventually overlaps some older block somewhere,
    and the term collapses into meaning nothing -- one run reported no order
    blocks at all and three propulsion blocks, which is the tell. The older
    block has to be close enough behind to still be the same piece of business,
    and must not have been traded through before this one formed.

    The least agreed term of the set, and it is flagged as such wherever it is
    printed.
    """
    out = []
    for n, ob in enumerate(obs):
        for older in reversed(obs[:n]):
            if ob["i"] - older["i"] > within:
                break
            if older["dir"] != ob["dir"]:
                continue
            if not (older["bot"] <= ob["top"] and ob["bot"] <= older["top"]):
                continue
            if ks is not None:
                spent = mitigated_at(ks[:ob["i"]], older["break_i"],
                                     older["bot"], older["top"])
                if spent is not None:
                    continue
            marked = dict(ob)
            marked["over"] = older["t"]
            out.append(marked)
            break
    return out


def pools(sw, tol_frac=0.0004):
    """Equal highs and equal lows -- where stops sit in a heap.

    Two swings of the same kind at the same price, within a tolerance, because
    "equal" on a chart has never meant equal to the tick.
    """
    out = []
    for kind in ("high", "low"):
        same = [s for s in sw if s["kind"] == kind]
        for a, b in zip(same, same[1:]):
            if abs(a["price"] - b["price"]) <= b["price"] * tol_frac:
                out.append({"kind": kind, "price": (a["price"] + b["price"]) / 2,
                            "t": b["t"], "i": b["i"], "first_t": a["t"]})
    return out


def mitigated_at(ks, start_i, bot, top):
    """The first candle after `start_i` to trade anywhere inside the band."""
    for j in range(start_i + 1, len(ks)):
        if ks[j]["l"] <= top and ks[j]["h"] >= bot:
            return j
    return None


def swept_at(ks, start_i, price, kind):
    """The first candle to take the level and close back the other side of it.

    Taking it and holding is a break, and belongs in the other list. A sweep is
    the wick through and the close back -- price reaching for what was resting
    there and not staying.
    """
    for j in range(start_i + 1, len(ks)):
        k = ks[j]
        if kind == "high" and k["h"] > price and k["c"] < price:
            return j
        if kind == "low" and k["l"] < price and k["c"] > price:
            return j
    return None
