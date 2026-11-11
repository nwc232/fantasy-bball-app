"""
Extra player data from ESPN's public site APIs (same player ids as fantasy):
game log, career stats by season, and news.

These endpoints are unofficial and their shapes drift, so every parser is
defensive: on any problem a section comes back as {"error": "..."} and the rest
of the player card still renders. Responses are cached for an hour.
"""
from __future__ import annotations

import html
import re
import time

import httpx

WEB = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes"
UA = {"User-Agent": "Mozilla/5.0 (category-lab)", "Accept": "application/json"}
TTL = 3600
_cache: dict[tuple, tuple[float, object]] = {}


def _get(url: str, params: dict | None = None) -> dict:
    key = (url, tuple(sorted((params or {}).items())))
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < TTL:
        return hit[1]
    r = httpx.get(url, params=params, headers=UA, timeout=15, follow_redirects=True)
    r.raise_for_status()
    data = r.json()
    _cache[key] = (time.time(), data)
    return data


def _num(x):
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return x


# --------------------------------------------------------------------------- #
def game_log(pid: str, limit: int = 12) -> dict:
    """Most recent games: date, opponent, result and the box-score line."""
    try:
        d = _get(f"{WEB}/{pid}/gamelog")
        labels = d.get("labels") or d.get("names") or []
        meta = d.get("events") or {}
        rows = []
        for st in d.get("seasonTypes") or []:
            name = str(st.get("displayName") or st.get("name") or "")
            if "pre" in name.lower():                 # skip preseason
                continue
            for cat in st.get("categories") or []:
                for ev in cat.get("events") or []:
                    eid = str(ev.get("eventId") or ev.get("id") or "")
                    stats = ev.get("stats") or []
                    m = meta.get(eid) or {}
                    opp = m.get("opponent") or {}
                    rows.append({
                        "id": eid,
                        "date": m.get("gameDate") or "",
                        "opp": opp.get("abbreviation") or opp.get("displayName") or "",
                        "at": m.get("atVs") or "",
                        "result": m.get("gameResult") or "",
                        "score": m.get("score") or "",
                        "stats": dict(zip(labels, stats)),
                    })
        seen, out = set(), []
        for r in sorted(rows, key=lambda r: r["date"], reverse=True):
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            out.append(r)
        if not out:
            return {"error": "No games found for this season."}
        return {"labels": labels, "games": out[:limit]}
    except Exception as e:                           # noqa: BLE001 - never break the card
        return {"error": f"Game log unavailable ({type(e).__name__})."}


def career(pid: str) -> dict:
    """Per-game averages for every season (regular season)."""
    try:
        d = _get(f"{WEB}/{pid}/stats")
        cats = d.get("categories") or d.get("statCategories") or []
        avg = next((c for c in cats if "average" in str(c.get("name", "")).lower()
                    or "average" in str(c.get("displayName", "")).lower()), None)
        if avg is None and cats:
            avg = cats[0]
        if not avg:
            return {"error": "No career stats found."}
        labels = avg.get("labels") or avg.get("names") or []
        rows = []
        for s in avg.get("statistics") or []:
            season = s.get("season") or {}
            team = s.get("teamSlug") or s.get("teamAbbreviation") or ""
            if not team and isinstance(s.get("team"), dict):
                team = s["team"].get("abbreviation", "")
            rows.append({"season": season.get("displayName") or season.get("year") or "",
                         "team": str(team).upper().replace("-", " ")[:12],
                         "stats": dict(zip(labels, s.get("stats") or []))})
        totals = avg.get("totals")
        if not rows:
            return {"error": "No career stats found."}
        return {"labels": labels, "seasons": rows,
                "career": dict(zip(labels, totals)) if isinstance(totals, list) else None}
    except Exception as e:                           # noqa: BLE001
        return {"error": f"Career stats unavailable ({type(e).__name__})."}


def _clean_text(s: str, n: int = 320) -> str:
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + "…"


def news(pid: str, limit: int = 6) -> dict:
    """ESPN fantasy news blurbs, falling back to general NBA news for the player."""
    sources = [
        ("https://site.api.espn.com/apis/fantasy/v2/games/fba/news/players",
         {"playerId": pid, "limit": limit}),
        ("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/news",
         {"athlete": pid, "limit": limit}),
    ]
    last_err = None
    for url, params in sources:
        try:
            d = _get(url, params)
            items = d.get("feed") or d.get("articles") or d.get("items") or []
            out = []
            for it in items:
                links = it.get("links") or {}
                web = links.get("web") if isinstance(links, dict) else None
                href = web.get("href") if isinstance(web, dict) else None
                out.append({
                    "headline": _clean_text(it.get("headline") or it.get("title") or "", 140),
                    "text": _clean_text(it.get("story") or it.get("description") or ""),
                    "published": it.get("published") or it.get("lastModified") or "",
                    "link": href,
                })
            out = [x for x in out if x["headline"] or x["text"]]
            if out:
                return {"items": out[:limit]}
        except Exception as e:                       # noqa: BLE001
            last_err = e
    return {"error": "No recent news." if last_err is None
            else f"News unavailable ({type(last_err).__name__})."}
