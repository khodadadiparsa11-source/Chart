"""Can a GitHub runner reach OANDA, and does it answer for his instruments?

His gold is XAUUSD from OANDA -- a CFD, not the COMEX future and not a token.
OANDA publishes a REST API, so the report can print the exact prices on his
own chart instead of something two dollars away from them. That needs a token,
which only he can create, so this asks the cheaper question first: is the host
reachable from the runner at all, and does it fail the way an endpoint that
merely wants a token fails?

401 is the good answer. Anything else means do not send him off to sign up.
"""

import json
import os
import urllib.error
import urllib.request

PRACTICE = "https://api-fxpractice.oanda.com"
LIVE = "https://api-fxtrade.oanda.com"
INSTRUMENTS = ["XAU_USD", "EUR_USD", "GBP_USD", "USD_JPY", "NZD_USD",
               "NAS100_USD", "US30_USD"]

TOKEN = os.environ.get("OANDA_TOKEN", "")


def ask(host, instrument, granularity="M15", count=5):
    url = ("%s/v3/instruments/%s/candles?granularity=%s&count=%d&price=M"
           % (host, instrument, granularity, count))
    head = {"Accept-Datetime-Format": "UNIX"}
    if TOKEN:
        head["Authorization"] = "Bearer " + TOKEN
    req = urllib.request.Request(url, headers=head)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read())


for host, name in ((PRACTICE, "practice"), (LIVE, "live")):
    try:
        ask(host, "XAU_USD")
        print("%-9s REACHABLE and answering" % name)
    except urllib.error.HTTPError as e:
        verdict = ("reachable -- it only wants a token" if e.code == 401
                   else "reachable, but says %d" % e.code)
        print("%-9s %s" % (name, verdict))
    except Exception as e:                      # noqa: BLE001 - blocked is the answer
        print("%-9s UNREACHABLE: %s" % (name, e))

if not TOKEN:
    print("\nNo OANDA_TOKEN set, so only reachability was tested. With a token "
          "this prints the last candle of each instrument for him to check "
          "against his own chart.")
else:
    print("\nlast 15m close, to hold against his screen:")
    for ins in INSTRUMENTS:
        try:
            c = ask(PRACTICE, ins)["candles"][-1]
            print("  %-12s %s" % (ins, c["mid"]["c"]))
        except Exception as e:                  # noqa: BLE001
            print("  %-12s FAILED: %s" % (ins, e))
