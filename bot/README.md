# Telegram zone watch

Every five minutes it scans five symbols on **5m, 15m, 1h and 4h**, and sends a
message only when price has **come back** to a zone worth an order — with a
picture of the chart, a box around the zone, a score out of ten, and the symbol
name.

## What it calls a zone

Three things together, never one on its own:

1. **A base** — one to five candles whose range is small against the recent
   normal while their volume is well above it. Money moved, price did not.
2. **An exit** — the next candle leaves the base with a wide range and volume of
   its own, closing clear of it.
3. **Silence since** — price has not traded back through. A zone that has
   already been revisited is spent and is dropped, not alerted.

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
   - `SYMBOLS` — default `BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,PAXGUSDT`
   - `MIN_SCORE` — default `7`. Lower it for more messages, raise it for fewer.
   - `COOLDOWN_MIN` — default `60`; at most one alert per symbol in that window.
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
