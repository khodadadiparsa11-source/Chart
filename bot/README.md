# Telegram volume watch

Checks a few symbols every five minutes and reports the candles worth looking
at: heavy volume whose aggressor disagrees with the close (absorption), and
plain volume spikes.

## Setup

1. **Create the bot.** Message [@BotFather](https://t.me/BotFather) on Telegram,
   send `/newbot`, follow the prompts. It replies with a token.
2. **Find your chat id.** Message [@userinfobot](https://t.me/userinfobot); it
   replies with your numeric id. Send your bot a `/start` first, or it cannot
   message you.
3. **Store both as repository secrets** — Settings → Secrets and variables →
   Actions → New repository secret:
   - `TELEGRAM_TOKEN`
   - `TELEGRAM_CHAT_ID`

   Secrets, not variables: a token in a variable is a token in plain sight.
4. **Optional settings** under the *Variables* tab of the same page:
   - `SYMBOLS` — default `BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,PAXGUSDT`
   - `INTERVAL` — default `5m`
5. **Test it.** Actions → *volume watch* → Run workflow → tick the test box.

## What it will and will not do

GitHub's shortest schedule is five minutes and runs are often later than that
under load, so alerts arrive minutes after the candle closes. That is fine for
5m and 15m candles and useless for second-by-second work.

The delta is approximated from one-second klines rather than counted from every
trade: a five-minute BTC candle holds thousands of trades and counting them
properly would take dozens of requests per symbol per run. Every message says
so.

A scheduled workflow is disabled automatically after 60 days without repository
activity. Push anything, or press Run workflow, to wake it.
