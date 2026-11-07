"""
League analysis: weekly team projections, H2H matchup odds, power rankings,
trade analysis.

Model
-----
* A player's weekly line = per-game stats x games he plays that week.
  With an NBA schedule, games are counted day by day and capped at the
  league's number of starting slots (best players by value start); otherwise
  3.5 games each.
* Weekly randomness: counting stats have variance = dispersion x mean
  (estimated from 2025-26 game logs); FG%/FT% are binomial on the week's
  attempts (x a small overdispersion factor).
* Categories are treated as independent normals; matchup win probability is
  Monte Carlo (4,000 draws).
Positional slot eligibility is ignored (any player can fill any start).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm

from . import engine as E

LABELS = E.LABELS
SIGN = {c: (-1.0 if c == "tov" else 1.0) for c in E.CATS}
IR_SLOT, BENCH_SLOT = 13, 12
DRAWS = 4000


def value_pool(df: pd.DataFrame, system: "E.System | str", cats: list[str], punts: list[str],
               pool_size: int) -> pd.DataFrame:
    use = [c for c in cats if c not in punts] or cats
    sc = E.score(df, system, cats=use, pool_size=pool_size)
    out = pd.concat([df, sc], axis=1)
    out["rank"] = out["value"].rank(ascending=False, method="min").astype(int)
    return out


# --------------------------------------------------------------------------- #
# Games and projections
# --------------------------------------------------------------------------- #
def games_in_period(rows: pd.DataFrame, sched: dict | None, days: list[int] | None,
                    starters: int, from_day: int | None = None) -> pd.Series:
    active = rows[rows["slot"] != IR_SLOT]
    g = pd.Series(0.0, index=rows.index)
    if not sched or not days:
        n = len(active)
        cap = min(1.0, starters / max(n * 0.5, 1e-9))
        g.loc[active.index] = 3.5 * cap
        return g
    order = active.sort_values("value", ascending=False)
    for d in days:
        if from_day and d < from_day:
            continue
        playing = [i for i, t in zip(order.index, order["team"]) if d in sched.get(t, ())]
        for i in playing[:starters]:
            g.loc[i] += 1
    return g


def project(rows: pd.DataFrame, games: pd.Series, cats: list[str]) -> tuple[np.ndarray, np.ndarray]:
    mu, var = [], []
    for c in cats:
        if c in ("fg", "ft"):
            m, a = ("fgm", "fga") if c == "fg" else ("ftm", "fta")
            made, att = (rows[m] * games).sum(), (rows[a] * games).sum()
            p = made / att if att > 0 else 0.0
            mu.append(p)
            var.append(E.DISPERSION[c] * p * (1 - p) / att if att > 0 else 1e-6)
        else:
            tot = (rows[c] * games).sum()
            mu.append(tot)
            var.append(max(E.DISPERSION[c] * tot, 1e-6))
    return np.array(mu), np.array(var)


def simulate(mu: np.ndarray, var: np.ndarray, cats: list[str], seed: int = 0):
    """mu, var: teams x cats. Returns pairwise cat-win probs, matchup win/tie probs."""
    sign = np.array([SIGN[c] for c in cats])
    sd = np.sqrt(var)
    T = mu.shape[0]
    rng = np.random.default_rng(seed)
    X = (mu[:, None, :] + sd[:, None, :] * rng.standard_normal((T, DRAWS, len(cats)))) * sign
    cat_p = norm.cdf(((mu[:, None, :] - mu[None, :, :]) * sign)
                     / np.sqrt(var[:, None, :] + var[None, :, :] + 1e-12))
    win = np.zeros((T, T)); tie = np.zeros((T, T)); exp_cats = np.zeros((T, T))
    for i in range(T):
        gt = (X[i][None] > X).sum(-1)
        lt = (X[i][None] < X).sum(-1)
        win[i] = (gt > lt).mean(-1)
        tie[i] = (gt == lt).mean(-1)
        exp_cats[i] = gt.mean(-1)
    return cat_p, win, tie, exp_cats


# --------------------------------------------------------------------------- #
# League-level
# --------------------------------------------------------------------------- #
def roster_rows(team: dict, pool: pd.DataFrame) -> pd.DataFrame:
    ids = [r["id"] for r in team["roster"]]
    slots = {r["id"]: r.get("slot") for r in team["roster"]}
    rows = pool.set_index("id").reindex(ids)
    rows["missing"] = rows["name"].isna()
    stat_cols = ["pts", "fg3m", "reb", "ast", "stl", "blk", "tov", "fgm", "fga",
                 "ftm", "fta", "g", "mpg", "value"]
    rows[stat_cols] = rows[stat_cols].fillna(0)
    rows["slot"] = [slots[i] for i in rows.index]
    rows = rows.reset_index().rename(columns={"index": "id"})
    return rows


def team_matrix(league: dict, rosters: dict[int, pd.DataFrame], cats: list[str],
                sched=None, days=None, from_day=None):
    ids = [t["id"] for t in league["teams"]]
    mus, vars_ = [], []
    for tid in ids:
        rows = rosters[tid]
        g = games_in_period(rows, sched, days, league["starters"], from_day)
        m, v = project(rows, g, cats)
        mus.append(m); vars_.append(v)
    return ids, np.array(mus), np.array(vars_)


def power_table(league: dict, rosters: dict[int, pd.DataFrame], cats: list[str]) -> list[dict]:
    ids, mu, var = team_matrix(league, rosters, cats)
    cat_p, win, tie, exp_cats = simulate(mu, var, cats, seed=1)
    T = len(ids)
    off = ~np.eye(T, dtype=bool)
    allplay = np.array([(win[i][off[i]] + 0.5 * tie[i][off[i]]).mean() for i in range(T)])
    xcats = np.array([exp_cats[i][off[i]].mean() for i in range(T)])
    catwin = np.array([[cat_p[i, off[i], k].mean() for k in range(len(cats))] for i in range(T)])
    signed = mu * np.array([SIGN[c] for c in cats])
    cat_rank = (-signed).argsort(0).argsort(0) + 1
    order = (-allplay).argsort()
    power_rank = np.empty(T, int); power_rank[order] = np.arange(1, T + 1)
    names = {t["id"]: t for t in league["teams"]}
    out = []
    for i, tid in enumerate(ids):
        out.append({
            "team_id": tid, "name": names[tid]["name"], "record": names[tid]["record"],
            "allplay": round(float(allplay[i]) * 100, 1),
            "exp_cats": round(float(xcats[i]), 2),
            "power_rank": int(power_rank[i]),
            "value_sum": round(float(rosters[tid].loc[rosters[tid]["slot"] != IR_SLOT, "value"].sum()), 2),
            "cats": {c: {"weekly": _fmt(c, mu[i, k]), "win_pct": round(float(catwin[i, k]) * 100, 1),
                         "rank": int(cat_rank[i, k])} for k, c in enumerate(cats)},
        })
    return sorted(out, key=lambda r: r["power_rank"])


def _fmt(c: str, x: float) -> float:
    return round(float(x), 3) if c in ("fg", "ft") else round(float(x), 1)


def matchups(league: dict, rosters: dict[int, pd.DataFrame], cats: list[str], period: int,
             sched: dict | None) -> list[dict]:
    days = league["matchup_periods"].get(period)
    ids, mu, var = team_matrix(league, rosters, cats, sched, days)
    cat_p, win, tie, exp_cats = simulate(mu, var, cats, seed=2)
    idx = {t: i for i, t in enumerate(ids)}
    names = {t["id"]: t["name"] for t in league["teams"]}
    games = {}
    for tid in ids:
        g = games_in_period(rosters[tid], sched, days, league["starters"])
        games[tid] = int(round(g.sum()))
    out = []
    for m in league["schedule"]:
        if m["period"] != period:
            continue
        a, b = idx.get(m["home"]), idx.get(m["away"])
        if a is None or b is None:
            continue
        out.append({
            "home": {"id": m["home"], "name": names[m["home"]], "games": games[m["home"]],
                     "live": m.get("home_live") or {}},
            "away": {"id": m["away"], "name": names[m["away"]], "games": games[m["away"]],
                     "live": m.get("away_live") or {}},
            "home_win": round(float(win[a, b]) * 100, 1),
            "tie": round(float(tie[a, b]) * 100, 1),
            "away_win": round(float(win[b, a]) * 100, 1),
            "home_exp_cats": round(float(exp_cats[a, b]), 2),
            "away_exp_cats": round(float(exp_cats[b, a]), 2),
            "cats": [{"cat": c, "home": _fmt(c, mu[a, k]), "away": _fmt(c, mu[b, k]),
                      "home_p": round(float(cat_p[a, b, k]) * 100, 1)} for k, c in enumerate(cats)],
        })
    return out


# --------------------------------------------------------------------------- #
# Trades
# --------------------------------------------------------------------------- #
def apply_trade(league: dict, team_a: int, team_b: int, a_gives: list[str], b_gives: list[str],
                a_drops: list[str], b_drops: list[str]) -> dict:
    """Return a new league dict with rosters changed. team_b == 0 means free agents."""
    new = {**league, "teams": []}
    for t in league["teams"]:
        roster = list(t["roster"])
        if t["id"] == team_a:
            roster = [r for r in roster if r["id"] not in set(a_gives) | set(a_drops)]
            roster += [{"id": pid, "slot": BENCH_SLOT} for pid in b_gives]
        elif t["id"] == team_b:
            roster = [r for r in roster if r["id"] not in set(b_gives) | set(b_drops)]
            roster += [{"id": pid, "slot": BENCH_SLOT} for pid in a_gives]
        new["teams"].append({**t, "roster": roster})
    return new


# --------------------------------------------------------------------------- #
# Roster balancing: uneven trades leave one team over the limit and one short
# --------------------------------------------------------------------------- #
def _team_odds(rows: pd.DataFrame, starters: int, cats: list[str], opp_mu: np.ndarray,
               opp_var: np.ndarray, objective: str) -> float:
    """Typical-week odds vs every other team, analytic (fast enough to try many FAs)."""
    g = games_in_period(rows, None, None, starters)
    mu, var = project(rows, g, cats)
    sign = np.array([SIGN[c] for c in cats])
    p = norm.cdf(sign * (mu - opp_mu) / np.sqrt(var + opp_var + 1e-12))     # opp x cats
    if objective == "cats":
        return float(p.sum(axis=1).mean())
    n = len(cats)
    k = np.arange(n + 1)
    wins = []
    for row in p:
        dist = np.array([1.0])
        for q in row:
            dist = np.convolve(dist, [1 - q, q])
        wins.append(dist[k * 2 > n].sum() + 0.5 * dist[k * 2 == n].sum())
    return float(np.mean(wins))


def balance_rosters(league: dict, pool: pd.DataFrame, cats: list[str], team_ids: list[int],
                    protect: dict[int, set] | None = None, max_fa: int = 30) -> tuple[dict, dict]:
    """Make each listed team's active (non-IR) roster exactly the league size:
    over -> drop the lowest-valued player (never one in `protect`);
    under -> add the free agent (incl. waivers) who most improves that team's
    typical-week odds against the rest of the league."""
    protect = protect or {}
    limit = league["roster_size"]
    objective = "win" if "MOST" in (league.get("scoring_type") or "") else "cats"
    teams = {t["id"]: {**t, "roster": list(t["roster"])} for t in league["teams"]}
    auto = {tid: {"drops": [], "adds": []} for tid in team_ids}
    pv = pool.drop_duplicates("id").set_index("id")
    val = pv["value"]

    def active(tid):
        return [r for r in teams[tid]["roster"] if r.get("slot") != IR_SLOT]

    for tid in team_ids:                       # drops first
        while len(active(tid)) > limit:
            cand = [r["id"] for r in active(tid) if r["id"] not in protect.get(tid, set())]
            if not cand:
                break
            worst = min(cand, key=lambda pid: float(val.get(pid, -99)))
            teams[tid]["roster"] = [r for r in teams[tid]["roster"] if r["id"] != worst]
            auto[tid]["drops"].append(worst)

    rostered = {r["id"] for t in teams.values() for r in t["roster"]}
    status = pv["status"] if "status" in pv else pd.Series("FREEAGENT", index=pv.index)
    inj = pv["inj_status"] if "inj_status" in pv else pd.Series("ACTIVE", index=pv.index)
    gmin = max(1, int(np.ceil(E.ELIG_FRAC * pv["g"].max()))) if len(pv) else 1   # no tiny samples
    fa = pv[(pv["fantasy_team"] == 0) & status.isin(["FREEAGENT", "WAIVERS"]) & (inj != "OUT")
            & (pv["g"] >= gmin)]
    fa_ids = [pid for pid in fa.sort_values("value", ascending=False).index if pid not in rostered]

    for tid in team_ids:                       # then fill open spots
        while len(active(tid)) < limit and fa_ids:
            others = [t for t in teams if t != tid]
            om, ov = [], []
            for o in others:
                rows = roster_rows(teams[o], pool)
                g = games_in_period(rows, None, None, league["starters"])
                m, v = project(rows, g, cats)
                om.append(m); ov.append(v)
            om, ov = np.array(om), np.array(ov)
            best, best_s = None, -1e9
            for pid in fa_ids[:max_fa]:
                trial = {**teams[tid], "roster": teams[tid]["roster"] + [{"id": pid, "slot": BENCH_SLOT}]}
                s = _team_odds(roster_rows(trial, pool), league["starters"], cats, om, ov, objective)
                if s > best_s:
                    best, best_s = pid, s
            teams[tid]["roster"].append({"id": best, "slot": BENCH_SLOT})
            auto[tid]["adds"].append(best)
            fa_ids.remove(best)

    return {**league, "teams": [teams[t["id"]] for t in league["teams"]]}, auto


def trade_report(league: dict, pool: pd.DataFrame, cats: list[str], team_a: int, team_b: int,
                 a_gives, b_gives, a_drops, b_drops, fill: bool = True) -> dict:
    involved = [team_a] + ([team_b] if team_b else [])
    after_league = apply_trade(league, team_a, team_b, a_gives, b_gives, a_drops, b_drops)
    auto_before = {tid: {"drops": [], "adds": []} for tid in involved}
    auto_after = {tid: {"drops": [], "adds": []} for tid in involved}
    if fill:
        # same treatment before and after, so a team that already had an empty
        # spot doesn't make the trade look better than it is
        league, auto_before = balance_rosters(league, pool, cats, involved)
        protect = {team_a: set(b_gives)}
        if team_b:
            protect[team_b] = set(a_gives)
        after_league, auto_after = balance_rosters(after_league, pool, cats, involved, protect)
    before_r = {t["id"]: roster_rows(t, pool) for t in league["teams"]}
    after_r = {t["id"]: roster_rows(t, pool) for t in after_league["teams"]}
    before = {r["team_id"]: r for r in power_table(league, before_r, cats)}
    after = {r["team_id"]: r for r in power_table(after_league, after_r, cats)}
    pmap = pool.set_index("id")

    def side(tid, gives, gets, drops):
        b, a = before[tid], after[tid]
        roster_n = len([r for r in [x for x in after_league["teams"] if x["id"] == tid][0]["roster"]
                        if r.get("slot") != IR_SLOT])
        return {
            "auto_drops": [_pinfo(pmap, p) for p in auto_after[tid]["drops"]],
            "auto_adds": [_pinfo(pmap, p) for p in auto_after[tid]["adds"]],
            "auto_before_adds": [_pinfo(pmap, p) for p in auto_before[tid]["adds"]],
            "auto_before_drops": [_pinfo(pmap, p) for p in auto_before[tid]["drops"]],
            "team_id": tid, "name": b["name"],
            "gives": [_pinfo(pmap, p) for p in gives], "gets": [_pinfo(pmap, p) for p in gets],
            "drops": [_pinfo(pmap, p) for p in drops],
            "roster_size_after": roster_n, "roster_limit": league["roster_size"],
            "allplay": [b["allplay"], a["allplay"]],
            "exp_cats": [b["exp_cats"], a["exp_cats"]],
            "power_rank": [b["power_rank"], a["power_rank"]],
            "value_sum": [b["value_sum"], a["value_sum"]],
            "cats": {c: {"weekly": [b["cats"][c]["weekly"], a["cats"][c]["weekly"]],
                         "win_pct": [b["cats"][c]["win_pct"], a["cats"][c]["win_pct"]],
                         "rank": [b["cats"][c]["rank"], a["cats"][c]["rank"]]} for c in cats},
        }

    sides = [side(team_a, a_gives, b_gives, a_drops)]
    if team_b:
        sides.append(side(team_b, b_gives, a_gives, b_drops))
    league_table = [{"team_id": tid, "name": before[tid]["name"],
                     "rank": [before[tid]["power_rank"], after[tid]["power_rank"]],
                     "allplay": [before[tid]["allplay"], after[tid]["allplay"]]}
                    for tid in before]
    league_table.sort(key=lambda r: r["rank"][1])
    return {"sides": sides, "league": league_table}


def _pinfo(pmap: pd.DataFrame, pid: str) -> dict:
    if pid in pmap.index:
        r = pmap.loc[pid]
        return {"id": pid, "name": r["name"], "team": r["team"], "value": round(float(r["value"]), 2),
                "rank": int(r["rank"])}
    return {"id": pid, "name": f"Player {pid}", "team": "", "value": 0.0, "rank": None}
