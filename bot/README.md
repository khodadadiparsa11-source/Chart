# Telegram zone watch

Every five minutes it scans the **hundred busiest USDT pairs on Binance** on
**5m, 15m, 1h and 4h**, and sends a message only when price has **come back** to
a zone worth an order — with a picture of the chart, a box around the zone, a
score out of ten, and the symbol name.

The list is ranked by real 24h turnover, not chosen at random: on a thin pair
one participant can draw a heavy base in a tight range with nothing behind it —
the same footprint, none of the meaning. Leveraged tokens and stablecoin pairs
are excluded.

It is built to stay quiet. Every gate below is required, not scored: a
candidate failing any one of them is dropped, never softened into a weaker
alert. Silent days are the design working.

## What it calls a zone

Three things together, never one on its own:

1. **A base** — one to five candles whose range is under 60% of the recent
   normal while their volume is at least double it. Money moved, price did not.
2. **An exit** — the next candle leaves the base with half again the normal
   range and half again the normal volume, closing a full base height clear of
   it.
3. **A run** — price then travelled at least three base heights away. A zone
   that never moved price has nothing behind it.
4. **Silence since** — price has not traded back through. A zone that has
   already been revisited is spent and is dropped, not alerted.
5. **Flow against the exit** — the aggressor split inside the base points the
   OPPOSITE way from where price left. Sellers were being filled and price rose
   anyway. This is the difference between a level someone defended and a level
   price merely passed through.

A zone another timeframe also holds, in the same direction at the same prices,
**scores higher** — it is not required. Requiring it was measured against the
live market and turned out to be a gate nothing could pass: the whole liquid
market holds only a handful of live zones at any moment, and demanding two
timeframes hold the same band simultaneously meant no alert would ever fire.

Alerts are raised on **15m, 1h and 4h** only. 5m is read for agreement and
never raises an alert of its own: on crypto a 5m zone is noise more often than
it is a level.

## Reading a quiet run

Every run prints its funnel, so silence can be read instead of guessed at:

```
gates: base=45990  volume=393  exit=38  clear=32  fresh=6  impulse=6
exit gate at other thresholds: 1.2x=55  1.5x=38  1.8x=30  2.0x=25  2.5x=17
```

`volume` is the heart of it — of forty-six thousand quiet stretches, under four
hundred carried heavy volume while going nowhere. That ratio is the idea the
whole bot rests on. The second line says how many candidates sit just outside
the exit threshold, so it can be set from measurement rather than by feel.

Candidates from every symbol are collected, **ranked**, and only the best few
are sent — at most 3 a run and 12 a day. When Bitcoin moves, a hundred pairs
move with it, and an unranked run would empty the whole correlated batch into
the chat at once.

## Outcomes

Every alert is followed afterwards using candles the next runs already fetch.
From the moment price arrived: leaving the band by one zone height counts as a
**reaction**, trading one zone height through it counts as a **failure**, and
neither within 24 candles counts as **no reaction**. One tally a day reports
the count.

It is a measurement of whether price reacted, not a win rate — no stop, no
target, no spread. More alerts prove nothing on their own; what happened after
them is the only thing that can.

The alert is sent when price **returns** to the band, because that is the moment
an order would be placed, not when the zone was formed.

## The score

A 0–10 ranking built from: base volume against normal, how tight the base was,
how hard the exit left, which timeframe it sits on, how many other timeframes
hold a zone in the same direction at the same prices, and whether the aggressor
flow inside the base pointed the opposite way from the exit.

It ranks candidates against each other. It is not a probability, and none of it
has been backtested.

## Setup

1. **Create the bot.** Message [@BotFather](https://t.me/BotFather) on Telegram,
   send `/newbot`, follow the prompts. It replies with a token.
2. **Find your chat id.** Message [@userinfobot](https://t.me/userinfobot); it
   replies with your numeric id. Send your own bot a `/start` first, or it
   cannot message you.
3. **Store both as repository secrets** — Settings → Secrets and variables →
   Actions → New repository secret:
   - `TELEGRAM_TOKEN`
   - `TELEGRAM_CHAT_ID`

   Secrets, not variables: a token in a variable is a token in plain sight.
4. **Optional settings** under the *Variables* tab of the same page:
   - `SYMBOLS` — leave unset to watch the busiest pairs automatically; set a
     comma-separated list to watch exactly those instead.
   - `TOP_N` — default `100`, how many of the busiest pairs to watch.
   - `DAILY_CAP` — default `12`, the most alerts that can be sent in a day.
   - `MIN_SCORE` — default `8`. Raise it to `9` for stricter still. Lowering it
     does not find more of the same setup; it starts admitting a looser one.
   - `COOLDOWN_MIN` — default `180`; at most one alert per symbol in that window.
5. **Test it.** Actions → *zone watch* → Run workflow → tick the test box.

## What it will and will not do

GitHub's shortest schedule is five minutes and runs are often later than that
under load. A zone lives for hours, so lateness costs little — but 1m zones are
gone before a run could report them, and they are deliberately not scanned.

The buy/sell split inside a base is **approximated** from finer candles rather
than counted from every trade: counting properly would take dozens of requests
per zone. Every message says so.

A scheduled workflow is disabled automatically after 60 days without repository
activity. Push anything, or press Run workflow, to wake it.

The alerted zones are remembered in the Actions cache. If that cache is evicted,
one zone may be reported twice — nothing worse.
