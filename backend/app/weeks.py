"""
Map ESPN matchup periods (fantasy "weeks") to scoring periods (days).

ESPN basketball's settings.scheduleSettings.matchupPeriods does NOT list days:
it lists which base calendar weeks make up each matchup, e.g.
{"1": [1], "2": [2], ..., "17": [17, 18]} (a two-week All-Star matchup).
Days are numbered from the season's first scoring period, and base weeks run
Monday-Sunday (week 1 is whatever is left of the opening week).

Calendar dates come from NBA tip-off times (US Eastern). Where a matchup already
has scored days (pointsByScoringPeriod), those are used to check the mapping.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def anchor_from_schedule(sched: dict) -> tuple[int, date] | None:
    """(day id, calendar date) for the earliest day with a known tip-off."""
    best = None
    for days in sched.values():
        if not isinstance(days, dict):
            continue
        for d, tip in days.items():
            if tip:
                if best is None or d < best[0]:
                    best = (d, datetime.fromtimestamp(tip / 1000, ET).date())
    return best


def date_of(day: int, anchor: tuple[int, date]) -> date:
    return anchor[1] + timedelta(days=day - anchor[0])


def label(day: int, anchor: tuple[int, date] | None, fallback_index: int = 0) -> dict:
    if anchor is None:
        return {"dow": DOW[fallback_index % 7], "date": ""}
    dt = date_of(day, anchor)
    return {"dow": DOW[dt.weekday()], "date": f"{dt.month}/{dt.day}"}


def _looks_like_days(raw: dict[int, list[int]]) -> bool:
    return bool(raw) and sum(len(v) for v in raw.values()) > 2 * len(raw)


def build(raw: dict[int, list[int]], observed: dict[int, list[int]], first: int, last: int,
          anchor: tuple[int, date] | None, n_periods_hint: int | None = None) -> tuple[dict, str]:
    """Return ({matchup period: [day ids]}, how it was derived)."""
    if _looks_like_days(raw):
        return {int(k): sorted(int(x) for x in v) for k, v in raw.items()}, "settings"
    if not raw:
        n = n_periods_hint or max(observed or {0: []}, default=0) or 25
        raw = {k: [k] for k in range(1, n + 1)}
    if anchor is None:
        # no dates: 7-day blocks from the first day
        base = {}
        for d in range(first, last + 1):
            base.setdefault((d - first) // 7 + 1, []).append(d)
    else:
        base, wk = {}, 1
        for d in range(first, last + 1):
            if d > first and date_of(d, anchor).weekday() == 0:
                wk += 1
            base.setdefault(wk, []).append(d)
    out = {int(m): sorted({d for b in inner for d in base.get(int(b), [])}) for m, inner in raw.items()}

    bad = [m for m, obs in observed.items() if obs and not set(obs) <= set(out.get(m, []))]
    if not bad:
        return out, "calendar"

    # Fallback: trust the scored days, extend to the end of each calendar week,
    # then continue Monday-Sunday weeks for future matchups.
    fixed: dict[int, list[int]] = {}
    periods = sorted(int(m) for m in raw)
    seen = {m: sorted(set(v)) for m, v in observed.items() if v}
    nxt_start = None
    for m in periods:
        if m in seen:
            start = seen[m][0]
        elif nxt_start is not None:
            start = nxt_start
        else:
            continue
        span = max(1, len(raw.get(m, [1])))
        end = start
        weeks_left = span
        while end + 1 <= last:
            dt = date_of(end + 1, anchor) if anchor else None
            if dt is not None and dt.weekday() == 0:
                weeks_left -= 1
                if weeks_left == 0:
                    break
            elif dt is None and (end + 1 - start) % 7 == 0:
                weeks_left -= 1
                if weeks_left == 0:
                    break
            end += 1
        days = list(range(start, end + 1))
        if m in seen:
            days = sorted(set(days) | set(seen[m]))
        fixed[m] = days
        nxt_start = days[-1] + 1
    return fixed, "scored days"
