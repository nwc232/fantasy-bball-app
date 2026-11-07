"""
Demo mode: builds ESPN-shaped JSON (player pool, league, NBA schedule) from the
bundled 2025-26 season so the whole app, including the ESPN parsers, can be
tried without credentials or network access.
"""
from __future__ import annotations

import json
import os
import time
from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import engine as E
from .espn import PRO_TEAMS, STAT

HERE = os.path.join(os.path.dirname(__file__), "data")
YEAR = 2026
ABBR_TO_ID = {v: k for k, v in PRO_TEAMS.items()}
BASE_POS = {"G": {"PG", "SG"}, "F": {"SF", "PF"}, "C": {"C"}, "G-F": {"SG", "SF"},
            "F-G": {"SG", "SF"}, "F-C": {"PF", "C"}, "C-F": {"PF", "C"}}


def slots_for(position: str) -> list[int]:
    """ESPN eligibleSlots from a base position: PG0 SG1 SF2 PF3 C4 G5 F6 SG/SF7 G/F8
    PF/C9 F/C10 UT11 BE12 IR13."""
    pos = BASE_POS.get(position, {"SF"})
    s = {i for i, p in enumerate(["PG", "SG", "SF", "PF", "C"]) if p in pos}
    if pos & {"PG", "SG"}: s.add(5)
    if pos & {"SF", "PF"}: s.add(6)
    if pos & {"SG", "SF"}: s.add(7)
    if pos & {"PG", "SG", "SF", "PF"}: s.add(8)
    if pos & {"PF", "C"}: s.add(9)
    if pos & {"SF", "PF", "C"}: s.add(10)
    return sorted(s) + [11, 12, 13]


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
    rng = np.random.default_rng(7)
    out = []
    for r in df.itertuples():
        tot = {STAT[k]: float(getattr(r, k)) for k in
               ["pts", "fg3m", "reb", "ast", "stl", "blk", "tov", "fgm", "fga", "ftm", "fta", "min"]}
        tot[STAT["gp"]] = float(r.g)
        avg = {k: v / r.g for k, v in tot.items() if k != STAT["gp"]}
        u = rng.random()
        inj = "OUT" if u < 0.03 else "DAY_TO_DAY" if u < 0.06 else "ACTIVE"
        out.append({"id": int(r.id), "onTeamId": 0,
                    "status": "WAIVERS" if rng.random() < 0.08 else "FREEAGENT",
                    "player": {
            "id": int(r.id), "fullName": r.name, "proTeamId": ABBR_TO_ID.get(r.team, 0),
            "eligibleSlots": slots_for(r.position),
            "injuryStatus": inj,
            "ownership": {"percentOwned": 0},
            "stats": [{"id": f"00{YEAR}", "seasonId": YEAR, "statSourceId": 0,
                       "statSplitTypeId": 0, "stats": tot, "averageStats": avg}],
        }})
    return out


CURRENT_PERIOD = 20
DAY_OFFSET = 2   # demo "today" = the 3rd day of the current matchup week


def demo_schedule() -> tuple[dict, dict[int, list[int]], int, int]:
    """ESPN proTeamSchedules shape (with tip-off times), matchup periods
    (Mon-Sun weeks), current period, current day. Times are set relative to now
    so that today's demo games haven't tipped off yet."""
    s = json.load(open(os.path.join(HERE, "schedule_2025_26.json")))
    start = date.fromisoformat(s["start"])
    last = max(max(v) for v in s["days"].values())
    first_monday = start - timedelta(days=start.weekday())
    periods: dict[int, list[int]] = {}
    for day in range(1, last + 1):
        dt = start + timedelta(days=day - 1)
        wk = (dt - first_monday).days // 7 + 1
        periods.setdefault(wk, []).append(day)
    today = periods[CURRENT_PERIOD][DAY_OFFSET]
    now_ms = int(time.time() * 1000)
    tip = lambda d: now_ms + (d - today) * 86_400_000 + 2 * 3_600_000
    pro = {"settings": {"proTeams": [
        {"id": ABBR_TO_ID[t], "abbrev": t,
         "proGamesByScoringPeriod": {str(d): [{"id": d, "date": tip(d)}] for d in days}}
        for t, days in s["days"].items()]}}
    return pro, periods, CURRENT_PERIOD, today


def demo_league(players: list[dict]) -> dict:
    rng = np.random.default_rng(42)
    df = pd.DataFrame([{**{"id": str(p["id"])}, **{"name": p["player"]["fullName"]}} for p in players])
    season = _season_frame()
    per = season.copy()
    for c in ["pts", "fg3m", "reb", "ast", "stl", "blk", "tov", "fgm", "fga", "ftm", "fta"]:
        per[c] = per[c] / per["g"]
    per["mpg"] = per["min"] / per["g"]
    val = E.score(per, "z")["value"]
    eligible = per.index[per["g"] >= 10]
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
    pro, periods, current, today = demo_schedule()
    sched_days = {t["abbrev"]: {int(k) for k in t["proGamesByScoringPeriod"]}
                  for t in pro["settings"]["proTeams"]}
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
                      "transactionCounter": {"acquisitions": 9,
                                             "matchupAcquisitionTotals": {str(current): 1}},
                      "record": {"overall": {"wins": int(rng.integers(60, 120)),
                                             "losses": int(rng.integers(60, 120)), "ties": 0}},
                      "roster": {"entries": entries}})
    # this week so far: each rostered player's per-game line x his games before today
    past = [d for d in periods[current] if d < today]

    def so_far(t: int) -> dict:
        tot = {k: 0.0 for k in ["pts", "fg3m", "reb", "ast", "stl", "blk", "tov",
                                "fgm", "fga", "ftm", "fta"]}
        for idx in rosters[t]:
            g = sum(1 for d in past if d in sched_days.get(per.loc[idx, "team"], ()))
            for k in tot:
                tot[k] += per.loc[idx, k] * g
        sid = {"pts": 0, "blk": 1, "stl": 2, "ast": 3, "reb": 6, "tov": 11, "fgm": 13,
               "fga": 14, "ftm": 15, "fta": 16, "fg3m": 17}
        out = {str(sid[k]): {"score": float(round(v, 3))} for k, v in tot.items()}
        out["19"] = {"score": float(tot["fgm"] / tot["fga"]) if tot["fga"] else 0.0}
        out["20"] = {"score": float(tot["ftm"] / tot["fta"]) if tot["fta"] else 0.0}
        return {"scoreByStat": out}

    # round-robin schedule
    ids = list(range(1, teams_n + 1))
    schedule = []
    for period in sorted(periods):
        k = (period - 1) % (teams_n - 1)
        rot = [ids[0]] + ids[1:][k:] + ids[1:][:k]
        for i in range(teams_n // 2):
            h, a = rot[i], rot[-1 - i]
            m = {"matchupPeriodId": period, "home": {"teamId": h}, "away": {"teamId": a}}
            if period == current:
                m["home"]["cumulativeScore"] = so_far(h - 1)
                m["away"]["cumulativeScore"] = so_far(a - 1)
            schedule.append(m)
    league = {
        "id": "demo", "scoringPeriodId": today,
        "status": {"currentMatchupPeriod": current},
        "settings": {
            "name": "Demo League (2025-26 stats)",
            "scoringSettings": {"scoringType": "H2H_CATEGORY", "scoringItems": [
                {"statId": i} for i in [0, 17, 6, 3, 2, 1, 19, 20, 11]]},
            "rosterSettings": {"lineupSlotCounts": {"0": 1, "1": 1, "2": 1, "3": 1, "4": 1,
                                                    "5": 1, "6": 1, "11": 3, "12": 3, "13": 1}},
            "scheduleSettings": {"matchupPeriods": {str(k): v for k, v in periods.items()}},
            "acquisitionSettings": {"matchupAcquisitionLimit": 4, "acquisitionLimit": -1,
                                    "isUsingAcquisitionBudget": False},
        },
        "teams": teams, "schedule": schedule, "members": [],
    }
    # calendar labels: make demo "today" the Wednesday of the current real week
    t = date.today()
    anchor = (today, t - timedelta(days=t.weekday() - DAY_OFFSET))
    return {"league": league, "pro_schedule": pro, "anchor": anchor}
