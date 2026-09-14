"""One chart per timeframe, with everything the report names drawn on it.

Labels are in English on purpose: the server has no Persian shaping, so Farsi
would render broken and reversed inside an image. The Persian explanation goes
in the message beside it, where Telegram renders it properly.

Only unmitigated items are drawn. Anything price has already traded back
through is history, and drawing it would bury the levels that still matter.
"""

import bisect
import io

from sessions import iran

# TradingView's light theme, because that is the chart his eye is trained on
# and a report that looks like a different program is one more thing to
# translate at six in the morning.
BG      = "#FFFFFF"
GRID    = "#E0E3EB"
AXIS    = "#131722"
UP      = "#089981"
DOWN    = "#F23645"

SESSION_COLOURS = {"ASIA": "#EDF2FB", "LONDON": "#EDF7F0", "NEW YORK": "#FBEFF3"}
COL = {
    "ob_up":   "#089981", "ob_dn":   "#F23645",
    "fvg_up":  "#2962FF", "fvg_dn":  "#9C27B0",
    "pb":      "#FF9800", "lq":      "#787B86",
    "bos":     "#089981", "choch":   "#F23645",
}


def render(title, ks, sessions, items, width=13.5, height=7.2, dpi=120):
    """Candles, session bands, and one labelled box or line per live item.

    `sessions` is a list of (name, start_ms, end_ms); `items` carries the
    order blocks, gaps, pools and breaks, each already filtered to the ones
    still in play.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    bg = BG
    fig, ax = plt.subplots(figsize=(width, height), dpi=dpi)
    fig.patch.set_facecolor(bg)
    ax.set_facecolor(bg)
    ax.tick_params(colors=AXIS, labelsize=8)
    for side in ("top", "left"):
        ax.spines[side].set_visible(False)
    for side in ("bottom", "right"):
        ax.spines[side].set_color(GRID)
    ax.grid(color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)

    t_index = {k["t"]: i for i, k in enumerate(ks)}
    times = [k["t"] for k in ks]
    n = len(ks)

    # Session bands first, so they sit behind everything else.
    for name, t0, t1 in sessions:
        xs = [i for i, k in enumerate(ks) if t0 <= k["t"] < t1]
        if not xs:
            continue
        ax.axvspan(min(xs) - 0.5, max(xs) + 0.5,
                   color=SESSION_COLOURS.get(name, "#F5F5F5"), zorder=0)
        ax.text((min(xs) + max(xs)) / 2, 1.008, name, transform=ax.get_xaxis_transform(),
                ha="center", va="bottom", color="#787B86", fontsize=8.5,
                fontweight="bold")

    lo = min(k["l"] for k in ks)
    hi = max(k["h"] for k in ks)
    pad = (hi - lo) * 0.08

    for i, k in enumerate(ks):
        up = k["c"] >= k["o"]
        col = UP if up else DOWN
        ax.plot([i, i], [k["l"], k["h"]], color=col, linewidth=0.7, zorder=3)
        body_lo, body_hi = min(k["o"], k["c"]), max(k["o"], k["c"])
        ax.add_patch(Rectangle((i - 0.3, body_lo), 0.6,
                               max(body_hi - body_lo, (hi - lo) * 0.0008),
                               facecolor=col, edgecolor=col, linewidth=0.4, zorder=4))

    def xof(t):
        """The candle that CONTAINS t, not the one stamped exactly t.

        The week's chart is drawn on hourly candles but carries levels found on
        five- and fifteen-minute ones, and a level made at 14:35 matches no
        hourly stamp at all. The old lookup fell back to bar zero when it missed
        -- silently, with no error -- so a zone made yesterday was drawn from the
        left edge of the week, and the price action of four days before it
        looked like it had traded straight through. It had not: the zone did not
        exist yet. Snapping back to the candle the moment falls inside is the
        only placement that can be read.
        """
        i = t_index.get(t)
        if i is not None:
            return i
        j = bisect.bisect_right(times, t) - 1
        return max(0, min(j, n - 1))

    # Zones run from where they formed to the right-hand edge: a level that has
    # not been traded through is still in play, and stopping the box early would
    # suggest otherwise.
    for it in items:
        kind = it["kind"]
        if kind in ("OB", "FVG", "PB"):
            x0 = xof(it["t"])
            key = ({"OB": "ob_up" if it["dir"] == "up" else "ob_dn",
                    "FVG": "fvg_up" if it["dir"] == "up" else "fvg_dn",
                    "PB": "pb"})[kind]
            c = COL[key]
            ax.add_patch(Rectangle((x0 - 0.5, it["bot"]), n - x0 + 0.5,
                                   it["top"] - it["bot"], facecolor=c, alpha=0.13,
                                   edgecolor=c, linewidth=1.1, zorder=5))
            tag = kind + (" " + it["tf"] if it.get("tf") else "")
            ax.text(x0 + 0.3, it["top"], tag, color="#FFFFFF", fontsize=8,
                    fontweight="bold", va="bottom", zorder=7,
                    bbox=dict(boxstyle="round,pad=0.18", fc=c, ec="none"))
        elif kind == "LQ":
            c = COL["lq"]
            ax.axhline(it["price"], color=c, linewidth=0.9,
                       linestyle=(0, (5, 4)), alpha=0.9, zorder=5)
            ax.text(n - 0.5, it["price"], " LQ " + it.get("note", ""),
                    color=AXIS, fontsize=8, va="center", ha="right", zorder=7,
                    bbox=dict(boxstyle="round,pad=0.18", fc="#FFFFFF", ec=c, lw=0.8))
        elif kind in ("BOS", "CHoCH"):
            x0 = xof(it["t"])
            c = COL["bos" if kind == "BOS" else "choch"]
            arrow = "▲" if it["dir"] == "up" else "▼"
            y = it["price"]
            ax.annotate("%s %s" % (kind, arrow), xy=(x0, y),
                        xytext=(0, 14 if it["dir"] == "up" else -20),
                        textcoords="offset points", ha="center",
                        color="#FFFFFF", fontsize=7.5, fontweight="bold", zorder=8,
                        bbox=dict(boxstyle="round,pad=0.2", fc=c, ec="none"))

    ax.set_xlim(-1, n + 0.5)
    ax.set_ylim(lo - pad, hi + pad)
    ax.set_title(title, color=AXIS, fontsize=12.5, fontweight="bold",
                 loc="left", pad=18)
    ax.yaxis.tick_right()

    # Iran time on the axis, because that is the clock he reads the report on.
    step = max(1, n // 10)
    ax.set_xticks(range(0, n, step))
    ax.set_xticklabels([iran(ks[i]["t"]) for i in range(0, n, step)], fontsize=7.5)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=bg, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()
