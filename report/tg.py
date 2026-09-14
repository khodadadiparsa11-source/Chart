"""Telegram, with its own token so the nightly report and the live zone alerts
never bury each other in one chat."""

import io
import json
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


def album(shots, caption):
    """One album per symbol, with the whole symbol's summary on the first image.

    Telegram shows only the FIRST caption under an album; the rest appear only
    if you open each photo. So the summary of every timeframe goes on image one
    and the others carry none -- otherwise reading a symbol means four taps,
    which is the thing this shape exists to avoid. One album is also one
    notification instead of six.
    """
    shots = [p for p in shots if p]
    if not shots:
        return
    chat = os.environ.get("REPORT_CHAT_ID")
    if not os.environ.get("REPORT_TOKEN") or not chat:
        print("[no credentials] would send %d images with caption:\n%s\n"
              % (len(shots), caption))
        return

    b = "----rep%d" % int(time.time() * 1000)
    out = io.BytesIO()

    def field(name, value):
        out.write(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                   % (b, name, value)).encode())

    media = []
    for i, _ in enumerate(shots):
        item = {"type": "photo", "media": "attach://file%d" % i}
        if i == 0:
            item["caption"] = caption
            item["parse_mode"] = "HTML"
        media.append(item)

    field("chat_id", chat)
    field("media", json.dumps(media, ensure_ascii=False))
    for i, png in enumerate(shots):
        out.write(("--%s\r\nContent-Disposition: form-data; name=\"file%d\"; "
                   "filename=\"chart%d.png\"\r\nContent-Type: image/png\r\n\r\n"
                   % (b, i, i)).encode())
        out.write(png)
        out.write(b"\r\n")
    out.write(("--%s--\r\n" % b).encode())
    _post("sendMediaGroup", out.getvalue(),
          {"Content-Type": "multipart/form-data; boundary=%s" % b})
