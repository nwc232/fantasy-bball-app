"""
Build advisor: what should this team build around?

1. Every realistic punt set is tried: 0-3 punted categories in a 9-cat league
   (with 4 you'd have to sweep the other 5). Players are re-valued for each
   build with the selected ranking system (same transform/weights/Minus 1),
   leaving the punted categories out. The team's roster value under each build
   is compared with every other team's: builds the roster already leans toward
   rank highest. A small penalty per punt prefers keeping categories alive
   when two builds are close.
2. For the chosen build, each of your players gets a build rank next to his
   normal rank. Much worse in the build than normally = doesn't fit (a trade
   chip: others value him more than your build does).
3. For each misfit: players with a similar normal rank (similar trade price)
   but a much better build rank.

The category profile (weekly win % vs the league) uses the same typical-week
model as power rankings.
"""
from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd
from scipy.stats import norm

from . import engine as E
from . import league as L

IR_SLOT = 13
# Cost of punting a category (team-sd units): a flat cost per punt (you now have
# to win the majority from fewer categories) plus a cost for giving up a category
# you currently win. Punting something you lose most weeks is nearly free.
PUNT_BASE = 0.15
PUNT_STRONG = 1.5            # x (weekly win chance - 35%), when above 35%
MAX_BUILDS = 8


def _combine(vals: pd.DataFrame, system: E.System, cats: list[str]) -> pd.Series:
    """Overall value from per-category values, for a given category set."""
    w = E.category_weights(system, cats)
    used = list(w.index)
    if not used:
        return pd.Series(0.0, index=vals.index)
    weighted = vals[[f"v_{c}" for c in used]].to_numpy() * w.to_numpy()
    n = len(used)
    if system.minus_one and n > 1:
        weighted = weighted.copy()
        weighted[np.arange(len(weighted)), weighted.argmin(1)] = 0.0
        n -= 1
    return pd.Series(weighted.sum(1) / n, index=vals.index)


def _profile(league: dict, pool: pd.DataFrame, team_id: int, cats: list[str]) -> list[dict]:
    rows = {t["id"]: L.roster_rows(t, pool) for t in league["teams"]}
    mus, vars_ = {}, {}
    for tid, r in rows.items():
        g = L.games_in_period(r, None, None, league["starters"])
        mus[tid], vars_[tid] = L.project(r, g, cats)
    me_m, me_v = mus[team_id], vars_[team_id]
    others = [t for t in mus if t != team_id]
    sign = np.array([-1.0 if c == "tov" else 1.0 for c in cats])
    p = np.array([norm.cdf(sign * (me_m - mus[o]) / np.sqrt(me_v + vars_[o] + 1e-12)) for o in others])
    allm = np.array([mus[t] for t in mus]) * sign
    rank = (allm > (me_m * sign)).sum(0) + 1
    return [{"cat": c, "win_pct": round(float(p[:, k].mean()) * 100, 1), "rank": int(rank[k]),
             "of": len(mus)} for k, c in enumerate(cats)]


def advise(league: dict, df: pd.DataFrame, system: E.System, team_id: int,
           build_punts: list[str] | None = None) -> dict:
    cats = league["cats"]
    n = len(cats)
    need = n // 2 + 1
    max_punts = max(0, n - need - 1)
    size = len(league["teams"]) * league["roster_size"]

    base = E.score(df, system, cats=cats, pool_size=size)        # per-category values, all cats
    pool = pd.concat([df, base], axis=1)
    pool["rank"] = pool["value"].rank(ascending=False, method="min").astype(int)
    vals = base[[f"v_{c}" for c in E.CATS]]

    teams = {t["id"]: t for t in league["teams"]}
    names = {t["id"]: t["name"] for t in league["teams"]}

    def roster_ids(tid):
        return [r["id"] for r in teams[tid]["roster"] if r.get("slot") != IR_SLOT]

    idx = {pid: i for i, pid in enumerate(pool["id"])}
    playing = pool["g"].to_numpy() > 0
    members = {tid: [idx[p] for p in roster_ids(tid) if p in idx and playing[idx[p]]] for tid in teams}

    profile = _profile(league, pool, team_id, cats)
    win = {x["cat"]: x["win_pct"] / 100 for x in profile}

    def punt_cost(punts):
        return sum(PUNT_BASE + PUNT_STRONG * max(0.0, win[c] - 0.35) for c in punts)

    # ---- evaluate every build -------------------------------------------- #
    builds, seen = [], {}
    for k in range(max_punts + 1):
        for punts in combinations(cats, k):
            keep = [c for c in cats if c not in punts]
            w = E.category_weights(system, keep)
            sig = tuple(sorted(w.index))
            if sig in seen:            # e.g. punting TO when the system ignores TO already
                continue
            seen[sig] = True
            v = _combine(vals, system, keep).to_numpy()
            team_val = {tid: float(v[m].sum()) for tid, m in members.items()}
            arr = np.array(list(team_val.values()))
            sd = arr.std() or 1.0
            z = (team_val[team_id] - arr.mean()) / sd
            rank = int((arr > team_val[team_id]).sum() + 1)
            builds.append({"punts": list(punts), "targets": keep, "team_rank": rank,
                           "of": len(arr), "z": round(float(z), 2),
                           "cost": round(punt_cost(punts), 2),
                           "score": round(float(z) - punt_cost(punts), 3),
                           "winning": sum(1 for c in keep if win[c] >= 0.5),
                           "_v": v})
    builds.sort(key=lambda b: -b["score"])
    no_punt = next(b for b in builds if not b["punts"])

    if build_punts is not None:
        chosen = next((b for b in builds if sorted(b["punts"]) == sorted(build_punts)), None)
        if chosen is None:          # a punt the system already ignores, or >max: build it ad hoc
            keep = [c for c in cats if c not in build_punts]
            v = _combine(vals, system, keep).to_numpy()
            chosen = {"punts": list(build_punts), "targets": keep, "_v": v}
    else:
        chosen = builds[0]

    pool["build_value"] = chosen["_v"]
    pool["build_rank"] = pool["build_value"].rank(ascending=False, method="min").astype(int)
    pv = pool.set_index("id")

    # ---- your players ------------------------------------------------------ #
    mine = []
    for pid in roster_ids(team_id):
        if pid not in pv.index:
            continue
        r = pv.loc[pid]
        if r["g"] <= 0:
            mine.append({"id": pid, "name": r["name"], "team": r["team"], "pos": r.get("pos", ""),
                         "injury": r.get("injury", ""), "std_rank": None, "build_rank": None,
                         "delta": None, "label": "no stats"})
            continue
        d = int(r["build_rank"]) - int(r["rank"])
        lim = max(10, 0.25 * r["rank"])
        label = "doesn't fit" if d > lim else "core" if d < -lim else "fits"
        mine.append({"id": pid, "name": r["name"], "team": r["team"], "pos": r.get("pos", ""),
                     "injury": r.get("injury", ""), "std_rank": int(r["rank"]),
                     "build_rank": int(r["build_rank"]), "delta": d, "label": label,
                     "v": {c: round(float(r[f"v_{c}"]), 2) for c in cats}})
    mine.sort(key=lambda x: (x["delta"] is None, -(x["delta"] or 0)))

    # ---- swap ideas for each misfit ----------------------------------------- #
    gmin = max(1, int(np.ceil(E.ELIG_FRAC * pool["g"].max())))
    mine_ids = set(r["id"] for r in teams[team_id]["roster"])
    others = pv[(~pv.index.isin(mine_ids)) & (pv["g"] >= gmin)]
    if "inj_status" in others:
        others = others[others["inj_status"] != "OUT"]
    targets = {}
    for m in mine:
        if m["label"] != "doesn't fit":
            continue
        lo = max(1, int(m["std_rank"] * 0.7) - 8)
        hi = int(m["std_rank"] * 1.3) + 8
        cand = others[(others["rank"] >= lo) & (others["rank"] <= hi) &
                      (others["build_rank"] < m["build_rank"])]
        cand = cand.assign(gain=cand["rank"] - cand["build_rank"]).sort_values("build_rank").head(6)
        targets[m["id"]] = [{
            "id": pid, "name": r["name"], "team": r["team"], "pos": r.get("pos", ""),
            "injury": r.get("injury", ""),
            "owner": names.get(int(r["fantasy_team"]), "Free agent") if r["fantasy_team"] else "Free agent",
            "owner_id": int(r["fantasy_team"]),
            "std_rank": int(r["rank"]), "build_rank": int(r["build_rank"]),
            "v": {c: round(float(r[f"v_{c}"]), 2) for c in cats},
        } for pid, r in cand.iterrows()]

    clean = lambda b: {k: v for k, v in b.items() if k != "_v"}
    return {
        "_pool": pv,                       # internal: every player's rank / build rank
        "_drops": [m for m in mine if m["build_rank"] is not None],
        "team": {"id": team_id, "name": names[team_id]},
        "cats": cats, "need": need,
        "profile": profile,
        "winning_now": sum(1 for c in cats if win[c] >= 0.5),
        "builds": [clean(b) for b in builds[:MAX_BUILDS]],
        "no_punt": clean(no_punt),
        "build": clean(chosen) | {"recommended": chosen is builds[0]},
        "players": mine,
        "targets": targets,
    }
