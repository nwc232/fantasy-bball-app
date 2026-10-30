"""
Demo mode: builds ESPN-shaped JSON (player pool, league, NBA schedule) from the
bundled 2025-26 season so the whole app, including the ESPN parsers, can be
tried without credentials or network access.
"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import engine as E
from .espn import PRO_TEAMS, STAT

HERE = os.path.join(os.path.dirname(__file__), "data")
YEAR = 2026
ABBR_TO_ID = {v: k for k, v in PRO_TEAMS.items()}
POS_SLOTS = {"G": [0, 1], "F": [2, 3], "C": [4], "G-F": [1, 2], "F-G": [1, 2],
             "F-C": [3, 4], "C-F": [3, 4]}


def _season_frame() -> pd.DataFrame:
    raw = pd.read_csv(os.path.join(HERE, "season_2025_26.csv"))
    g = raw["wins"] + raw["losses"]
    df = pd.DataFrame({
        "id": raw["player_id"].astype(str), "name": raw["player_name"], "team": raw["team"],
        "position": raw["position"], "g": g, "min": raw["minutes_played"],
        "pts": raw["one_point_made"] + 2 * raw["two_point_made"] + 3 * raw["three_point_made"],
        "fg3m": raw["three_point_made"],
        "reb": raw["offensive_rebounds"] + raw["defensive_rebounds"],
        "ast": raw["assists"], "stl": raw["steals"], "blk": raw["blocks"],
        "tov": raw["turnovers"],
        "fgm": raw["two_point_made"] + raw["three_point_made"],
        "fga": raw["two_point_attempted"] + raw["three_point_attempted"],
        "ftm": raw["one_point_made"], "fta": raw["one_point_attempted"],
    })
    return df[df["g"] > 0].reset_index(drop=True)


def demo_players() -> list[dict]:
    df = _season_frame()
    out = []
    for r in df.itertuples():
        tot = {STAT[k]: float(getattr(r, k)) for k in
               ["pts", "fg3m", "reb", "ast", "stl", "blk", "tov", "fgm", "fga", "ftm", "fta", "min"]}
        tot[STAT["gp"]] = float(r.g)
        avg = {k: v / r.g for k, v in tot.items() if k != STAT["gp"]}
        out.append({"id": int(r.id), "onTeamId": 0, "player": {
            "id": int(r.id), "fullName": r.name, "proTeamId": ABBR_TO_ID.get(r.team, 0),
            "eligibleSlots": POS_SLOTS.get(r.position, []) + [11, 12, 13],
            "injuryStatus": "ACTIVE",
            "ownership": {"percentOwned": 0},
            "stats": [{"id": f"00{YEAR}", "seasonId": YEAR, "statSourceId": 0,
                       "statSplitTypeId": 0, "stats": tot, "averageStats": avg}],
        }})
    return out


def demo_schedule() -> tuple[dict, dict[int, list[int]], int]:
    """ESPN proTeamSchedules shape, matchup periods (Mon-Sun weeks), current period."""
    s = json.load(open(os.path.join(HERE, "schedule_2025_26.json")))
    start = date.fromisoformat(s["start"])
    pro = {"settings": {"proTeams": [
        {"id": ABBR_TO_ID[t], "abbrev": t,
         "proGamesByScoringPeriod": {str(d): [{"id": d}] for d in days}}
        for t, days in s["days"].items()]}}
    last = max(max(v) for v in s["days"].values())
    first_monday = start - timedelta(days=start.weekday())
    periods: dict[int, list[int]] = {}
    for day in range(1, last + 1):
        dt = start + timedelta(days=day - 1)
        wk = (dt - first_monday).days // 7 + 1
        periods.setdefault(wk, []).append(day)
    return pro, periods, 20


def demo_league(players: list[dict]) -> dict:
    rng = np.random.default_rng(42)
    df = pd.DataFrame([{**{"id": str(p["id"])}, **{"name": p["player"]["fullName"]}} for p in players])
    season = _season_frame()
    per = season.copy()
    for c in ["pts", "fg3m", "reb", "ast", "stl", "blk", "tov", "fgm", "fga", "ftm", "fta"]:
        per[c] = per[c] / per["g"]
    per["mpg"] = per["min"] / per["g"]
    val = E.score(per, "z")["value"]
    eligible = per.index[per["g"] >= 25]
    rank = val.rank(ascending=False)
    teams_n, rounds = 12, 13
    rosters = [[] for _ in range(teams_n)]
    avail = set(eligible)
    for r in range(rounds):
        order = range(teams_n) if r % 2 == 0 else reversed(range(teams_n))
        for t in order:
            cand = list(avail)
            key = rank[cand].values * np.exp(rng.normal(0, 0.3, len(cand)))
            pick = cand[int(np.argmin(key))]
            rosters[t].append(pick)
            avail.remove(pick)

    by_id = {str(p["id"]): p for p in players}
    pro, periods, current = demo_schedule()
    names = ["Demo Ballers", "Pick and Pop", "Punt City", "Box Score Bandits", "Stat Stuffers",
             "Glass Cleaners", "Swat Team", "Splash Bros Inc", "Triple Doubles", "Free Throw Fails",
             "Bench Mob", "Waiver Wire Warriors"]
    teams = []
    for t, r in enumerate(rosters):
        entries = []
        for j, idx in enumerate(r):
            pid = per.loc[idx, "id"]
            p = json.loads(json.dumps(by_id[pid]))
            entries.append({"playerId": int(pid), "lineupSlotId": 11 if j < 10 else 12,
                            "playerPoolEntry": {"id": int(pid), "player": p["player"]}})
        teams.append({"id": t + 1, "name": names[t], "abbrev": f"T{t+1}", "owners": [],
                      "record": {"overall": {"wins": int(rng.integers(60, 120)),
                                             "losses": int(rng.integers(60, 120)), "ties": 0}},
                      "roster": {"entries": entries}})
    # round-robin schedule
    ids = list(range(1, teams_n + 1))
    schedule = []
    for period in sorted(periods):
        k = (period - 1) % (teams_n - 1)
        rot = [ids[0]] + ids[1:][k:] + ids[1:][:k]
        for i in range(teams_n // 2):
            schedule.append({"matchupPeriodId": period, "home": {"teamId": rot[i]},
                             "away": {"teamId": rot[-1 - i]}})
    league = {
        "id": "demo", "scoringPeriodId": periods[current][0],
        "status": {"currentMatchupPeriod": current},
        "settings": {
            "name": "Demo League (2025-26 stats)",
            "scoringSettings": {"scoringType": "H2H_CATEGORY", "scoringItems": [
                {"statId": i} for i in [0, 17, 6, 3, 2, 1, 19, 20, 11]]},
            "rosterSettings": {"lineupSlotCounts": {"0": 1, "1": 1, "2": 1, "3": 1, "4": 1,
                                                    "5": 1, "6": 1, "11": 3, "12": 3, "13": 1}},
            "scheduleSettings": {"matchupPeriods": {str(k): v for k, v in periods.items()}},
        },
        "teams": teams, "schedule": schedule, "members": [],
    }
    return {"league": league, "pro_schedule": pro}
