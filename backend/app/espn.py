"""
ESPN fantasy basketball API: player pool, league import, NBA schedule.

Unofficial endpoints (the same ones fantasy.espn.com and the `espn_api` Python
package use). Private leagues need the `espn_s2` and `SWID` cookies from a
logged-in browser session.

ESPN season ids are the END year: 2026-27 -> 2027.
Stat split ids inside player.stats[]: f"{source}{split}{year}"
    source 0 = actual, 1 = projected
    split  0 = season, 1 = last 7, 2 = last 15, 3 = last 30
"""
from __future__ import annotations

import json
from typing import Any

import httpx
import pandas as pd

BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba"
UA = {"User-Agent": "Mozilla/5.0 (fantasy-rankings)", "Accept": "application/json"}

# ESPN basketball stat ids
STAT = {"pts": "0", "blk": "1", "stl": "2", "ast": "3", "reb": "6", "tov": "11",
        "fgm": "13", "fga": "14", "ftm": "15", "fta": "16", "fg3m": "17",
        "fg_pct": "19", "ft_pct": "20", "min": "40", "gp": "42"}
# scoring item stat id -> our category key
SCORING_CAT = {0: "pts", 1: "blk", 2: "stl", 3: "ast", 6: "reb", 11: "tov",
               17: "fg3m", 19: "fg", 20: "ft"}
SCORING_NAMES = {4: "OREB", 5: "DREB", 13: "FGM", 14: "FGA", 15: "FTM", 16: "FTA",
                 18: "3PA", 21: "3P%", 22: "eFG%", 35: "A/TO", 37: "DD", 38: "TD",
                 9: "PF", 40: "MIN"}

PRO_TEAMS = {0: "FA", 1: "ATL", 2: "BOS", 3: "NOP", 4: "CHI", 5: "CLE", 6: "DAL",
             7: "DEN", 8: "DET", 9: "GSW", 10: "HOU", 11: "IND", 12: "LAC", 13: "LAL",
             14: "MIA", 15: "MIL", 16: "MIN", 17: "BKN", 18: "NYK", 19: "ORL", 20: "PHI",
             21: "PHX", 22: "POR", 23: "SAC", 24: "SAS", 25: "OKC", 26: "UTA", 27: "WAS",
             28: "TOR", 29: "MEM", 30: "CHA"}
POS = {1: "PG", 2: "SG", 3: "SF", 4: "PF", 5: "C"}
SLOT_POS = {0: "PG", 1: "SG", 2: "SF", 3: "PF", 4: "C"}
BENCH_SLOT, IR_SLOT = 12, 13
# lineup slot ids (ESPN basketball POSITION_MAP)
SLOT_NAMES = {0: "PG", 1: "SG", 2: "SF", 3: "PF", 4: "C", 5: "G", 6: "F", 7: "SG/SF",
              8: "G/F", 9: "PF/C", 10: "F/C", 11: "UT", 12: "BE", 13: "IR"}
STARTING_SLOTS = set(range(0, 12))

SPLITS = {  # key -> (label, source, split, year_offset)
    "season": ("This season", 0, 0, 0),
    "last30": ("Last 30 days", 0, 3, 0),
    "last15": ("Last 15 days", 0, 2, 0),
    "last7": ("Last 7 days", 0, 1, 0),
    "proj": ("ESPN projections", 1, 0, 0),
    "prev": ("Last season", 0, 0, -1),
}


class ESPNError(Exception):
    pass


def _cookies(espn_s2: str | None, swid: str | None) -> dict:
    c = {}
    if espn_s2:
        c["espn_s2"] = espn_s2.strip()
    if swid:
        s = swid.strip()
        if not s.startswith("{"):
            s = "{" + s.strip("{}") + "}"
        c["SWID"] = s
    return c


def _get(url: str, params: Any = None, headers: dict | None = None,
         cookies: dict | None = None, timeout: float = 30) -> dict:
    h = {**UA, **(headers or {})}
    try:
        r = httpx.get(url, params=params, headers=h, cookies=cookies or {},
                      timeout=timeout, follow_redirects=True)
    except httpx.HTTPError as e:
        raise ESPNError(f"Could not reach ESPN: {e}") from e
    if r.status_code in (401, 403):
        raise ESPNError("ESPN refused access. For a private league, paste your espn_s2 "
                        "and SWID cookies.")
    if r.status_code == 404:
        raise ESPNError("ESPN returned 404: check the league id and season.")
    if r.status_code >= 400:
        raise ESPNError(f"ESPN error {r.status_code}: {r.text[:200]}")
    try:
        return r.json()
    except json.JSONDecodeError as e:
        raise ESPNError("ESPN did not return JSON (often means the league is private "
                        "and the cookies are missing or expired).") from e


# --------------------------------------------------------------------------- #
# Player pool
# --------------------------------------------------------------------------- #
def fetch_player_pool(year: int, league_id: str | None = None,
                      espn_s2: str | None = None, swid: str | None = None,
                      limit: int = 1100) -> list[dict]:
    split_ids = sorted({f"{src}{sp}{year + off}" for _, src, sp, off in SPLITS.values()})
    flt = {"players": {
        "limit": limit,
        "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
        "filterStatsForTopScoringPeriodIds": {"value": 2, "additionalValue": split_ids},
    }}
    if league_id:
        url = f"{BASE}/seasons/{year}/segments/0/leagues/{league_id}"
    else:
        url = f"{BASE}/seasons/{year}/segments/0/leaguedefaults/3"
    data = _get(url, params={"view": "kona_player_info"},
                headers={"X-Fantasy-Filter": json.dumps(flt)},
                cookies=_cookies(espn_s2, swid))
    return data.get("players", [])


def _player_row(p: dict) -> dict:
    return {
        "id": str(p.get("id")),
        "name": p.get("fullName", ""),
        "team": PRO_TEAMS.get(p.get("proTeamId", 0), "FA"),
        "pos": "/".join(sorted({SLOT_POS[s] for s in p.get("eligibleSlots", []) if s in SLOT_POS},
                               key=list(SLOT_POS.values()).index))
               or POS.get(p.get("defaultPositionId"), ""),
        "injury": (p.get("injuryStatus") or "ACTIVE").replace("_", " ").title()
                  if p.get("injuryStatus") not in (None, "ACTIVE") else "",
        "owned": round((p.get("ownership") or {}).get("percentOwned", 0) or 0, 1),
        "slots": tuple(sorted(int(s) for s in p.get("eligibleSlots", []) if int(s) in STARTING_SLOTS)),
        "inj_status": (p.get("injuryStatus") or "ACTIVE").upper(),
    }


def _split_stats(p: dict, stat_id: str) -> dict | None:
    for st in p.get("stats", []) or []:
        if st.get("id") == stat_id:
            avg = st.get("averageStats") or {}
            tot = st.get("stats") or {}
            gp = tot.get(STAT["gp"]) or avg.get(STAT["gp"])
            if not gp:
                return None
            def per_game(k):
                if STAT[k] in avg and k not in ("gp",):
                    return float(avg[STAT[k]])
                return float(tot.get(STAT[k], 0)) / gp
            row = {k: per_game(k) for k in ["pts", "fg3m", "reb", "ast", "stl", "blk",
                                             "tov", "fgm", "fga", "ftm", "fta"]}
            mins = avg.get(STAT["min"])
            row["mpg"] = float(mins) if mins is not None else float(tot.get(STAT["min"], 0)) / gp
            row["g"] = int(round(gp))
            return row
    return None


def players_to_frames(entries: list[dict], year: int) -> dict[str, pd.DataFrame]:
    """entries: kona_player_info 'players' items or roster playerPoolEntry dicts."""
    frames: dict[str, list] = {k: [] for k in SPLITS}
    for e in entries:
        p = e.get("player", e)
        base = _player_row(p)
        base["fantasy_team"] = e.get("onTeamId", 0) or 0
        base["status"] = (e.get("status") or ("ONTEAM" if base["fantasy_team"] else "FREEAGENT")).upper()
        for key, (_, src, sp, off) in SPLITS.items():
            s = _split_stats(p, f"{src}{sp}{year + off}")
            if s:
                frames[key].append({**base, **s})
    return {k: pd.DataFrame(v) for k, v in frames.items()}


# --------------------------------------------------------------------------- #
# League
# --------------------------------------------------------------------------- #
def fetch_league(league_id: str, year: int, espn_s2: str | None = None,
                 swid: str | None = None) -> dict:
    url = f"{BASE}/seasons/{year}/segments/0/leagues/{league_id}"
    views = ["mTeam", "mRoster", "mSettings", "mMatchup", "mMatchupScore", "mStatus"]
    return _get(url, params=[("view", v) for v in views], cookies=_cookies(espn_s2, swid))


def fetch_pro_schedule(year: int) -> dict:
    return _get(f"{BASE}/seasons/{year}", params={"view": "proTeamSchedules_wl"})


def parse_pro_schedule(data: dict) -> dict[str, dict[int, int | None]]:
    """NBA team abbrev -> {scoring period id (day): tip-off time in epoch ms (or None)}.
    Membership tests (`day in sched[team]`) work as before."""
    out = {}
    for t in (data.get("settings") or {}).get("proTeams", []):
        abbr = PRO_TEAMS.get(t.get("id"), None)
        if not abbr or abbr == "FA":
            continue
        days = {}
        for k, games in (t.get("proGamesByScoringPeriod") or {}).items():
            if games:
                days[int(k)] = (games[0] or {}).get("date")
        out[abbr] = days
    return out


def fetch_week_box(league_id: str, year: int, period: int, day: int,
                   espn_s2: str | None = None, swid: str | None = None) -> dict:
    """Current matchup's box scores (players' stats for the matchup period so far)."""
    url = f"{BASE}/seasons/{year}/segments/0/leagues/{league_id}"
    flt = {"schedule": {"filterMatchupPeriodIds": {"value": [period]}}}
    return _get(url, params=[("view", "mMatchupScore"), ("view", "mScoreboard"),
                             ("scoringPeriodId", day)],
                headers={"X-Fantasy-Filter": json.dumps(flt)},
                cookies=_cookies(espn_s2, swid))


def parse_week_box(data: dict, period: int) -> dict[int, dict]:
    """team id -> summed FGM/FGA/FTM/FTA this matchup period, from
    rosterForMatchupPeriod (best effort: empty if ESPN doesn't include it)."""
    out: dict[int, dict] = {}
    for m in data.get("schedule", []) or []:
        if m.get("matchupPeriodId") != period:
            continue
        for side in ("home", "away"):
            s = m.get(side) or {}
            tid = s.get("teamId")
            entries = ((s.get("rosterForMatchupPeriod") or {}).get("entries") or [])
            if not tid or not entries:
                continue
            tot = {"fgm": 0.0, "fga": 0.0, "ftm": 0.0, "fta": 0.0}
            for e in entries:
                p = ((e.get("playerPoolEntry") or {}).get("player") or {})
                for st in p.get("stats", []) or []:
                    vals = st.get("stats") or {}
                    if STAT["fga"] in vals or STAT["fta"] in vals:
                        for k in tot:
                            tot[k] += float(vals.get(STAT[k], 0) or 0)
                        break
            out[tid] = tot
    return out


def _int_or_none(x):
    """ESPN sometimes sends counts as floats (7.0); normalise to int."""
    try:
        return None if x is None else int(round(float(x)))
    except (TypeError, ValueError):
        return None


def parse_league(data: dict, year: int) -> dict:
    settings = data.get("settings", {}) or {}
    scoring = settings.get("scoringSettings", {}) or {}
    cats, unsupported = [], []
    for item in scoring.get("scoringItems", []) or []:
        sid = item.get("statId")
        if sid in SCORING_CAT:
            cats.append(SCORING_CAT[sid])
        else:
            unsupported.append(SCORING_NAMES.get(sid, f"stat {sid}"))
    order = ["fg", "ft", "fg3m", "pts", "reb", "ast", "stl", "blk", "tov"]
    cats = [c for c in order if c in cats] or order

    slot_counts = {int(k): v for k, v in
                   ((settings.get("rosterSettings") or {}).get("lineupSlotCounts") or {}).items()}
    starters = sum(v for k, v in slot_counts.items() if k not in (BENCH_SLOT, IR_SLOT)) or 10
    start_slots = {k: v for k, v in slot_counts.items() if k in STARTING_SLOTS and v} or {11: starters}
    acq = settings.get("acquisitionSettings") or {}
    status = data.get("status", {}) or {}
    cur_period = status.get("currentMatchupPeriod") or 1

    matchup_periods = {int(k): [int(x) for x in v] for k, v in
                       ((settings.get("scheduleSettings") or {}).get("matchupPeriods") or {}).items()}

    members = {m.get("id"): m for m in data.get("members", []) or []}
    teams, roster_entries = [], []
    for t in data.get("teams", []) or []:
        name = t.get("name") or f"{t.get('location', '')} {t.get('nickname', '')}".strip()
        owner_ids = t.get("owners") or []
        owner = ""
        if owner_ids and owner_ids[0] in members:
            m = members[owner_ids[0]]
            owner = f"{m.get('firstName', '')} {m.get('lastName', '')}".strip() or m.get("displayName", "")
        rec = ((t.get("record") or {}).get("overall") or {})
        tc = t.get("transactionCounter") or {}
        adds_period = (tc.get("matchupAcquisitionTotals") or {}).get(str(cur_period))
        roster = []
        for e in ((t.get("roster") or {}).get("entries") or []):
            pe = e.get("playerPoolEntry") or {}
            pid = str(e.get("playerId") or pe.get("id"))
            roster.append({"id": pid, "slot": e.get("lineupSlotId")})
            if pe:
                roster_entries.append({**pe, "onTeamId": t.get("id")})
        teams.append({"id": t.get("id"), "name": name or f"Team {t.get('id')}",
                      "abbrev": t.get("abbrev", ""), "owner": owner,
                      "record": {"w": rec.get("wins", 0), "l": rec.get("losses", 0),
                                 "t": rec.get("ties", 0)},
                      "adds_this_period": _int_or_none(adds_period),
                      "adds_season": _int_or_none(tc.get("acquisitions")),
                      "roster": roster})

    schedule = []
    observed: dict[int, set] = {}
    for m in data.get("schedule", []) or []:
        home, away = m.get("home") or {}, m.get("away") or {}
        for side in (home, away):
            for k in (side.get("pointsByScoringPeriod") or {}):
                observed.setdefault(m.get("matchupPeriodId"), set()).add(int(k))
        if not home.get("teamId") or not away.get("teamId"):
            continue
        def live(side):
            sbs = ((side.get("cumulativeScore") or {}).get("scoreByStat") or {})
            return {SCORING_CAT[int(k)]: v.get("score") for k, v in sbs.items()
                    if int(k) in SCORING_CAT and v.get("score") is not None}
        def live_raw(side):
            sbs = ((side.get("cumulativeScore") or {}).get("scoreByStat") or {})
            return {int(k): v.get("score") for k, v in sbs.items() if v.get("score") is not None}
        schedule.append({"period": m.get("matchupPeriodId"),
                         "home": home["teamId"], "away": away["teamId"],
                         "home_live": live(home), "away_live": live(away),
                         "home_raw": live_raw(home), "away_raw": live_raw(away),
                         "winner": m.get("winner")})

    return {
        "id": str(data.get("id")),
        "year": year,
        "name": (settings.get("name") or f"League {data.get('id')}"),
        "scoring_type": scoring.get("scoringType", ""),
        "cats": cats,
        "unsupported_cats": unsupported,
        "starters": starters,
        "roster_size": sum(v for k, v in slot_counts.items() if k != IR_SLOT) or 13,
        "teams": teams,
        "schedule": schedule,
        "matchup_periods": matchup_periods,          # replaced by weeks.build() in the store
        "matchup_periods_raw": matchup_periods,
        "observed_days": {k: sorted(v) for k, v in observed.items() if k is not None},
        "first_day": status.get("firstScoringPeriod") or 1,
        "last_day": status.get("finalScoringPeriod"),
        "current_period": cur_period,
        "slot_counts": start_slots,
        "adds_limit_period": _int_or_none(acq.get("matchupAcquisitionLimit")),
        "adds_limit_season": _int_or_none(acq.get("acquisitionLimit")),
        "current_day": data.get("scoringPeriodId"),
        "roster_entries": roster_entries,
    }
