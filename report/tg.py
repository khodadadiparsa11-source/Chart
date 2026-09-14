"""Telegram, with its own token so the nightly report and the live zone alerts
never bury each other in one chat."""

import io
import os
import time
import urllib.parse
import urllib.request

API = "https://api.telegram.org/bot%s/%s"


def _post(method, body, headers):
    token = os.environ.get("REPORT_TOKEN")
    if not token:
        return False
    try:
        req = urllib.request.Request(API % (token, method), data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as r:
            r.read()
        return True
    except Exception as e:              # noqa: BLE001 - one failed send, not the run
        print("telegram %s failed: %s" % (method, e))
        return False


def text(msg):
    chat = os.environ.get("REPORT_CHAT_ID")
    if not os.environ.get("REPORT_TOKEN") or not chat:
        print("[no credentials] would send:\n%s\n" % msg)
        return
    body = urllib.parse.urlencode({"chat_id": chat, "text": msg,
                                   "parse_mode": "HTML",
                                   "disable_web_page_preview": "true"}).encode()
    _post("sendMessage", body, {"Content-Type": "application/x-www-form-urlencoded"})


def photo(png, caption):
    chat = os.environ.get("REPORT_CHAT_ID")
    if not os.environ.get("REPORT_TOKEN") or not chat or not png:
        print("[no credentials] would send photo with caption:\n%s\n" % caption)
        return
    b = "----rep%d" % int(time.time() * 1000)
    out = io.BytesIO()

    def field(name, value):
        out.write(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                   % (b, name, value)).encode())

    field("chat_id", chat)
    field("caption", caption)
    field("parse_mode", "HTML")
    out.write(("--%s\r\nContent-Disposition: form-data; name=\"photo\"; "
               "filename=\"chart.png\"\r\nContent-Type: image/png\r\n\r\n" % b).encode())
    out.write(png)
    out.write(("\r\n--%s--\r\n" % b).encode())
    _post("sendPhoto", out.getvalue(),
          {"Content-Type": "multipart/form-data; boundary=%s" % b})
