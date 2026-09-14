"""Session boundaries, defined where they actually happen.

Each boundary is a local time at its own financial centre, not a fixed hour of
UTC and not a fixed hour of Tehran. London and New York move their clocks twice
a year; Tokyo and Iran never do. Writing the boundaries in Tehran time would be
right for half the year and an hour wrong for the other half -- discovered weeks
later, by which point the reports have been trusted.

Asked in local time, every boundary moves itself.
"""

from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

IRAN = ZoneInfo("Asia/Tehran")
UTC = ZoneInfo("UTC")

# Each session starts when its centre opens and ends when the next one does.
# No overlap: a candle belongs to exactly one session, which is what a report
# split by session needs. London and New York really do overlap for a few
# hours; that overlap lives inside the New York band here.
BOUNDS = [
    ("ASIA",     ZoneInfo("Asia/Tokyo"),       dtime(9, 0)),
    ("LONDON",   ZoneInfo("Europe/London"),    dtime(8, 0)),
    ("NEW YORK", ZoneInfo("America/New_York"), dtime(8, 0)),
]
CLOSE = (ZoneInfo("America/New_York"), dtime(17, 0))

FA = {"ASIA": "آسیا", "LONDON": "لندن", "NEW YORK": "نیویورک"}


def day_sessions(d):
    """(name, start_ms, end_ms) for the trading day of the given UTC date."""
    marks = [(name, datetime.combine(d, t, tzinfo=tz)) for name, tz, t in BOUNDS]
    end = datetime.combine(d, CLOSE[1], tzinfo=CLOSE[0])
    out = []
    for i, (name, start) in enumerate(marks):
        stop = marks[i + 1][1] if i + 1 < len(marks) else end
        out.append((name, int(start.timestamp() * 1000), int(stop.timestamp() * 1000)))
    return out


def session_of(ms, sess):
    """Which of the day's sessions a candle belongs to, if any."""
    for name, a, b in sess:
        if a <= ms < b:
            return name
    return None


def iran(ms, fmt="%H:%M"):
    return datetime.fromtimestamp(ms / 1000, UTC).astimezone(IRAN).strftime(fmt)


def iran_date(ms):
    return datetime.fromtimestamp(ms / 1000, UTC).astimezone(IRAN).date()


def last_closed_day(now=None):
    """The trading day whose New York close has already happened."""
    now = now or datetime.now(UTC)
    d = now.date()
    for _ in range(5):
        close = datetime.combine(d, CLOSE[1], tzinfo=CLOSE[0])
        if close < now and d.weekday() < 5:
            return d
        d -= timedelta(days=1)
    return d
