"""Send one test picture so he can check the clock against his own chart.

Not a signal and it must never be mistaken for one: the zone in it is a candle
picked by position, not by any of the five gates. The only thing being tested is
whether the time written on the box is the time he sees on his own chart.

Real Binance candles, because a made-up timestamp would prove nothing.
"""

import datetime
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("watch", os.path.join(HERE, "watch.py"))
watch = importlib.util.module_from_spec(spec)
sys.modules["watch"] = watch
spec.loader.exec_module(watch)

# An unfilled workflow input arrives as an empty string, not as an absent one,
# so the default has to be applied after the lookup rather than inside it.
SYMBOL = os.environ.get("CLOCK_SYMBOL", "").strip() or "BTCUSDT"
TF = os.environ.get("CLOCK_TF", "").strip() or "15m"

ks = watch.klines(SYMBOL, TF, 120)
if len(ks) < 60:
    raise SystemExit("only %d candles came back" % len(ks))

# A candle far enough back that the box has room to sit, chosen by position
# alone. Nothing here judges whether it is a zone -- that is the point.
i = len(ks) - 25
base = ks[i]
z = {"tf": TF, "side": "demand", "top": base["h"], "bot": base["l"],
     "start": i, "exit": i + 1, "bars": 1, "formed": base["t"],
     "bvol": 0.0, "exr": 0.0, "exv": 0.0, "push": 0.0, "ran": 0.0, "tight": 0.0}

png = watch.draw(SYMBOL, ks, z, 0, [])

utc = datetime.datetime.fromtimestamp(base["t"] / 1000, datetime.timezone.utc)
cap = (
    "🧪 <b>تست ساعت — سیگنال نیست</b>\n\n"
    "این کندل از هیچ فیلتری رد نشده. فقط یک کندل است که با شماره انتخاب شده، "
    "تا ساعتش را با چارت خودت مقایسه کنی.\n\n"
    "<b>{sym}</b> · {tf}\n"
    "ساعت روی تصویر: <b>{teh}</b> (ایران)\n"
    "همان لحظه به UTC: <code>{utc}</code>\n"
    "قیمت آن کندل: <code>{o} / {c}</code>\n\n"
    "روی چارت خودت همین لحظه را باز کن. اگر کندلی که می‌بینی همین قیمت‌ها را "
    "دارد، ساعت درست است. اگر نه، بگو چه ساعتی روی چارت تو نوشته."
).format(sym=SYMBOL, tf=TF, teh=watch.stamp(base["t"]),
         utc=utc.strftime("%Y-%m-%d %H:%M"),
         o=watch.fmt(base["o"]), c=watch.fmt(base["c"]))

if png:
    watch.send_photo(png, cap)
    print("sent: %s %s  tehran=%s  utc=%s"
          % (SYMBOL, TF, watch.stamp(base["t"]), utc.strftime("%H:%M")))
else:
    watch.send_text(cap)
    print("no image; text only")
