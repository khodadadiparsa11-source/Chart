# chart

A single-page charting tool for sub-minute timeframes with real traded volume.

Spot gold reports tick volume rather than contracts, and exchange futures data
is paid, so this runs on Binance — which publishes 1-second klines and true
volume for free.

Binance has no native interval between 1 second and 1 minute, so 5s, 15s and
30s candles are folded from the 1s stream in the browser.

Open `index.html`, or visit the published page.
