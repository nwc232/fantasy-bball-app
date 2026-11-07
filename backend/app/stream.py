"""
Weekly streaming planner.

For your current (or a future) matchup, find the add/drop moves that most raise
your odds against this week's opponent.

Model
-----
* Week total = what has already happened this matchup (ESPN live scores) +
  the projection for every remaining game.
* A remaining game counts only if the player is on your roster that day, the
  game hasn't tipped off yet, and he actually gets a starting slot: lineups are
  filled day by day with ESPN's position slots (PG/SG/SF/PF/C/G/F/UT...),
  maximising the number of starts, then player value.
* Injuries: OUT = no games, day-to-day / questionable = 70% of a game.
* Per-category odds use the same weekly noise model as the matchup tab.
  The objective follows your league: "most categories" leagues maximise the
  chance of winning the matchup; "each category" leagues maximise expected
  categories won.
* The opponent is projected from their current roster (no guess at their adds).

Search: greedy. Each round tries every (day, drop, add) combination, where the
add day is one of the free agent's game days, and keeps the best one, up to
your remaining adds. Players you stream in can be dropped again later in the
week, so plans like "Mon-Tue guy, then a Wed-Sun guy" come out naturally.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from scipy.stats import norm

from . import engine as E

STATS = ["pts", "fg3m", "reb", "ast", "stl", "blk", "tov", "fgm", "fga", "ftm", "fta"]
SI = {s: i for i, s in enumerate(STATS)}
ESPN_ID = {"pts": 0, "blk": 1, "stl": 2, "ast": 3, "reb": 6, "tov": 11, "fgm": 13,
           "fga": 14, "ftm": 15, "fta": 16, "fg3m": 17}
IR_SLOT = 13
AVAIL = {"OUT": 0.0, "INJURY_RESERVE": 0.0, "SUSPENSION": 0.0, "DOUBTFUL": 0.25,
         "DAY_TO_DAY": 0.7, "QUESTIONABLE": 0.7}
DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


@dataclass
class Move:
    day: int
    drop: str
    add: str
    gain: float = 0.0


@dataclass
class Ctx:
    pool: pd.DataFrame                 # indexed by player id
    sched: dict                        # team -> {day: tip ms}
    days: list[int]                    # remaining countable days
    today: int | None
    mode: str                          # auto | today | tomorrow
    slot_list: list[int]               # one entry per starting slot instance
    cats: list[str]
    objective: str                     # win | cats
    now_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    _lineup_cache: dict = field(default_factory=dict)
    _plays: dict = field(default_factory=dict)
    vec: dict = field(default_factory=dict)        # pid -> per-game stats x availability
    slots: dict = field(default_factory=dict)
    val: dict = field(default_factory=dict)

    def __post_init__(self):
        mat = self.pool[STATS].to_numpy(float) * self.pool["avail"].to_numpy(float)[:, None]
        for i, pid in enumerate(self.pool.index):
            self.vec[pid] = mat[i]
        self.slots = {pid: (set(s) or {11}) for pid, s in self.pool["slots"].items()}
        self.val = {pid: float(v) for pid, v in self.pool["value"].items()}

    # ---- schedule --------------------------------------------------------- #
    def plays(self, pid: str, day: int) -> bool:
        k = (pid, day)
        hit = self._plays.get(k)
        if hit is None:
            hit = self._plays[k] = self._plays_uncached(pid, day)
        return hit

    def _plays_uncached(self, pid: str, day: int) -> bool:
        team = self.pool.at[pid, "team"]
        games = self.sched.get(team) or {}
        if day not in games:
            return False
        if self.today is not None and day == self.today:
            if self.mode == "tomorrow":
                return False
            if self.mode == "auto":
                tip = games.get(day) if isinstance(games, dict) else None
                return tip is None or tip > self.now_ms
        return True

    def game_days(self, pid: str) -> list[int]:
        return [d for d in self.days if self.plays(pid, d)]

    # ---- daily lineup ----------------------------------------------------- #
    def starters(self, players: tuple[str, ...]) -> tuple[str, ...]:
        """Best legal lineup from players who have a game: most starts, then value."""
        key = players
        hit = self._lineup_cache.get(key)
        if hit is not None:
            return hit
        n, m = len(players), len(self.slot_list)
        if n == 0:
            res: tuple = ()
        else:
            W = np.full((n, m), -1e6)
            for i, pid in enumerate(players):
                elig = self.slots[pid]
                w = 100.0 + self.val[pid]
                for j, s in enumerate(self.slot_list):
                    if s in elig:
                        W[i, j] = w
            r, c = linear_sum_assignment(W, maximize=True)
            res = tuple(players[i] for i, j in zip(r, c) if W[i, j] > -1e5)
        self._lineup_cache[key] = res
        return res


def roster_by_day(ctx: Ctx, base: list[str], moves: list[Move]) -> dict[int, list[str]] | None:
    """Roster on each remaining day after applying moves in day order.
    None if the plan is impossible (a drop of someone not on the roster that day,
    or the same player added twice)."""
    order = sorted(moves, key=lambda m: m.day)
    adds = [m.add for m in order]
    if len(set(adds)) != len(adds):
        return None
    r = list(base)
    applied = 0
    out = {}
    for d in ctx.days:
        while applied < len(order) and order[applied].day <= d:
            mv = order[applied]
            if mv.drop not in r or mv.add in r:
                return None
            r.remove(mv.drop)
            r.append(mv.add)
            applied += 1
        out[d] = list(r)
    return out


def project(ctx: Ctx, base: list[str], moves: list[Move] | None = None):
    """Remaining projected totals (STATS vector), starts per player per day."""
    moves = moves or []
    tot = np.zeros(len(STATS))
    starts: dict[str, list[int]] = {}
    benched: dict[str, list[int]] = {}
    rosters = roster_by_day(ctx, base, moves)
    if rosters is None:
        return None
    for d, roster in rosters.items():
        playing = tuple(sorted(p for p in roster if ctx.plays(p, d)))
        st = ctx.starters(playing)
        for p in playing:
            (starts if p in st else benched).setdefault(p, []).append(d)
        for p in st:
            tot += ctx.vec[p]
    return tot, starts, benched, rosters


def cat_moments(cats: list[str], so_far: np.ndarray, rem: np.ndarray):
    mu, var = [], []
    for c in cats:
        if c in ("fg", "ft"):
            m, a = ("fgm", "fga") if c == "fg" else ("ftm", "fta")
            made = so_far[SI[m]] + rem[SI[m]]
            att = so_far[SI[a]] + rem[SI[a]]
            p = made / att if att > 0 else 0.0
            mu.append(p)
            ra = rem[SI[a]]
            var.append(E.DISPERSION[c] * p * (1 - p) * ra / att ** 2 if att > 0 else 1e-6)
        else:
            mu.append(so_far[SI[c]] + rem[SI[c]])
            var.append(max(E.DISPERSION[c] * rem[SI[c]], 1e-6))
    return np.array(mu), np.array(var)


def cat_probs(cats, me, opp):
    sign = np.array([-1.0 if c == "tov" else 1.0 for c in cats])
    return norm.cdf(sign * (me[0] - opp[0]) / np.sqrt(me[1] + opp[1] + 1e-12))


def win_prob(p: np.ndarray) -> float:
    """P(win more categories than you lose), cats independent (Poisson-binomial)."""
    dist = np.array([1.0])
    for q in p:
        dist = np.convolve(dist, [1 - q, q])
    n = len(p)
    k = np.arange(n + 1)
    return float(dist[k * 2 > n].sum() + 0.5 * dist[k * 2 == n].sum())


@dataclass
class Eval:
    probs: np.ndarray
    win: float
    exp_cats: float
    score: float
    rem: np.ndarray
    starts: dict
    benched: dict
    rosters: dict


def evaluate(ctx: Ctx, base, moves, so_far_me, opp_m) -> Eval | None:
    res = project(ctx, base, moves)
    if res is None:
        return None
    rem, starts, benched, rosters = res
    me = cat_moments(ctx.cats, so_far_me, rem)
    p = cat_probs(ctx.cats, me, opp_m)
    w, x = win_prob(p), float(p.sum())
    return Eval(p, w, x, w if ctx.objective == "win" else x, rem, starts, benched, rosters)


# --------------------------------------------------------------------------- #
def so_far_vector(raw: dict, box: dict | None, roster_rows: pd.DataFrame) -> np.ndarray:
    """This matchup's actual totals from ESPN live scores. FGM/FGA/FTM/FTA come
    from the live scores if present, else the week's box score, else they're
    estimated from points scored and the roster's shooting profile."""
    v = np.zeros(len(STATS))
    for s, sid in ESPN_ID.items():
        if sid in raw and raw[sid] is not None:
            v[SI[s]] = float(raw[sid])
    for m, a, pct_id, base in [("fgm", "fga", 19, "pts"), ("ftm", "fta", 20, "pts")]:
        if v[SI[a]] > 0:
            continue
        att = (box or {}).get(a)
        if not att:
            per = roster_rows[[a, base]].sum()
            att = v[SI[base]] * (per[a] / per[base]) if per[base] > 0 else 0.0
        pct = raw.get(pct_id)
        if pct is None:
            per = roster_rows[[m, a]].sum()
            pct = per[m] / per[a] if per[a] > 0 else 0.0
        v[SI[a]] = att
        v[SI[m]] = float(pct) * att
    return v


def plan(league: dict, pool: pd.DataFrame, sched: dict, team_id: int, period: int,
         droppable: list[str] | None = None, adds_left: int | None = None,
         mode: str = "auto", max_candidates: int = 80) -> dict:
    p = league
    cats = p["cats"]
    match = next((m for m in p["schedule"] if m["period"] == period
                  and team_id in (m["home"], m["away"])), None)
    if not match:
        raise ValueError("No matchup for this team in that week.")
    home = match["home"] == team_id
    opp_id = match["away"] if home else match["home"]
    week = p["matchup_periods"].get(period) or []
    cur_day = p.get("current_day")
    is_current = period == p["current_period"]
    today = cur_day if is_current else None
    days = [d for d in week if (today is None or d >= today)]

    slot_list = [s for s, n in sorted(p["slot_counts"].items()) for _ in range(int(n))]
    objective = "win" if "MOST" in (p.get("scoring_type") or "") else "cats"

    pool = pool.drop_duplicates("id").set_index("id", drop=False)
    pool["avail"] = pool["inj_status"].map(AVAIL).fillna(1.0) if "inj_status" in pool else 1.0
    if "slots" not in pool:
        pool["slots"] = [()] * len(pool)

    ctx = Ctx(pool=pool, sched=sched, days=days, today=today, mode=mode,
              slot_list=slot_list, cats=cats, objective=objective)

    teams = {t["id"]: t for t in p["teams"]}

    def active(tid):
        return [r["id"] for r in teams[tid]["roster"] if r.get("slot") != IR_SLOT and r["id"] in pool.index]

    my_base, opp_base = active(team_id), active(opp_id)
    my_rows, opp_rows = pool.loc[my_base], pool.loc[opp_base]
    raw_me = (match["home_raw"] if home else match["away_raw"]) if is_current else {}
    raw_op = (match["away_raw"] if home else match["home_raw"]) if is_current else {}
    box = p.get("week_box") or {}
    sf_me = so_far_vector(raw_me or {}, box.get(team_id), my_rows) if is_current else np.zeros(len(STATS))
    sf_op = so_far_vector(raw_op or {}, box.get(opp_id), opp_rows) if is_current else np.zeros(len(STATS))

    opp_rem, opp_starts, opp_benched, _ = project(ctx, opp_base)
    opp_m = cat_moments(cats, sf_op, opp_rem)

    # droppable: user's choice, else the 3 lowest-valued active players
    if droppable is None:
        droppable = list(my_rows.sort_values("value").index[:3])
    droppable = [d for d in droppable if d in my_base]

    # adds left
    used = (teams[team_id].get("adds_this_period") or 0) if is_current else 0
    limit = p.get("adds_limit_period")
    if adds_left is None:
        adds_left = 7 if (limit is None or limit < 0) else max(0, limit - used)

    # free agent candidates with at least one countable game
    fa = pool[(pool["fantasy_team"] == 0) & (pool["status"] == "FREEAGENT") & (pool["avail"] > 0)]
    fa = fa.assign(gdays=[len(ctx.game_days(pid)) for pid in fa.index])
    fa = fa[fa["gdays"] > 0]
    by_val = fa.sort_values("value", ascending=False).index[: max_candidates // 2]
    by_vol = fa.assign(k=fa["value"] + 0.35 * fa["gdays"]).sort_values("k", ascending=False).index[: max_candidates]
    cands = list(dict.fromkeys(list(by_val) + list(by_vol)))[:max_candidates]

    base_eval = evaluate(ctx, my_base, [], sf_me, opp_m)
    moves: list[Move] = []
    cur = base_eval
    board: dict[str, dict] = {}
    # minimum improvement worth spending an add on: +0.5 pts of win chance, or +0.03 cats
    thresh = 0.005 if objective == "win" else 0.03

    for it in range(adds_left):
        best, best_eval = None, None
        rosters = roster_by_day(ctx, my_base, moves)
        added = {m.add for m in moves}
        for y in cands:
            if y in added:
                continue
            for d in ctx.game_days(y):
                for x in [x for x in rosters[d] if x in droppable or x in added]:
                    mv = Move(d, x, y)
                    ev = evaluate(ctx, my_base, moves + [mv], sf_me, opp_m)
                    if ev is None:
                        continue
                    gain = ev.score - cur.score
                    if it == 0:
                        b = board.get(y)
                        if b is None or gain > b["gain"]:
                            board[y] = {"gain": gain, "drop": x, "day": d,
                                        "starts": len(ev.starts.get(y, [])),
                                        "win": ev.win, "exp_cats": ev.exp_cats}
                    if best is None or gain > best.gain:
                        mv.gain = gain
                        best, best_eval = mv, ev
        if best is None or best.gain < thresh:
            break
        moves.append(best)
        cur = best_eval

    # ---------------------------------------------------------------------- #
    def name(pid):
        return pool.at[pid, "name"] if pid in pool.index else pid

    def day_label(d):
        i = week.index(d) if d in week else 0
        return DOW[i % 7]

    def pinfo(pid):
        r = pool.loc[pid]
        return {"id": pid, "name": r["name"], "team": r["team"], "pos": r.get("pos", ""),
                "injury": r.get("injury", ""), "value": round(float(r["value"]), 2)}

    def grid(base, ev_starts, ev_benched, rosters, extra=()):
        ids = list(dict.fromkeys(list(base) + list(extra)))
        rows = []
        for pid in ids:
            cells = []
            for d in week:
                if today is not None and d < today:
                    cells.append("past")
                elif d not in rosters or pid not in rosters[d]:
                    cells.append("off")
                elif d in ev_starts.get(pid, []):
                    cells.append("start")
                elif d in ev_benched.get(pid, []):
                    cells.append("bench")
                else:
                    cells.append("none")
            rows.append({**pinfo(pid), "cells": cells,
                         "starts": len(ev_starts.get(pid, []))})
        per_day = []
        for d in week:
            if d not in rosters:
                per_day.append(None)
                continue
            n_st = sum(1 for pid in ids if d in ev_starts.get(pid, []))
            n_b = sum(1 for pid in ids if d in ev_benched.get(pid, []))
            per_day.append({"starts": n_st, "benched": n_b, "slots": len(slot_list)})
        return {"rows": rows, "per_day": per_day}

    final = cur
    my_rows_final = list(dict.fromkeys(my_base + [m.add for m in moves]))
    stat_out = lambda sf, rem: {c: (float((sf[SI[{"fg": "fgm", "ft": "ftm"}[c]]] + rem[SI[{"fg": "fgm", "ft": "ftm"}[c]]]) /
                                          max(sf[SI[{"fg": "fga", "ft": "fta"}[c]]] + rem[SI[{"fg": "fga", "ft": "fta"}[c]]], 1e-9))
                                    if c in ("fg", "ft") else float(sf[SI[c]] + rem[SI[c]])) for c in cats}

    board_rows = []
    for y, b in sorted(board.items(), key=lambda kv: -kv[1]["gain"])[:40]:
        gd = ctx.game_days(y)
        board_rows.append({**pinfo(y), "days": [day_label(d) for d in gd],
                           "games": len(gd), "starts": b["starts"],
                           "gain": round(b["gain"] * (100 if objective == "win" else 1), 2),
                           "win": round(b["win"] * 100, 1), "exp_cats": round(b["exp_cats"], 2),
                           "drop": name(b["drop"]), "add_day": day_label(b["day"])})

    return {
        "team": {"id": team_id, "name": teams[team_id]["name"]},
        "opponent": {"id": opp_id, "name": teams[opp_id]["name"]},
        "period": period, "is_current": is_current, "objective": objective,
        "week_days": [day_label(d) for d in week],
        "today_index": week.index(today) if today in week else None,
        "mode": mode, "adds_left": adds_left, "adds_used": used, "adds_limit": limit,
        "droppable": droppable,
        "cats": cats,
        "before": {"win": round(base_eval.win * 100, 1), "exp_cats": round(base_eval.exp_cats, 2),
                   "probs": {c: round(float(q) * 100, 1) for c, q in zip(cats, base_eval.probs)},
                   "starts": sum(len(v) for v in base_eval.starts.values()),
                   "benched": sum(len(v) for v in base_eval.benched.values()),
                   "proj": stat_out(sf_me, base_eval.rem)},
        "after": {"win": round(final.win * 100, 1), "exp_cats": round(final.exp_cats, 2),
                  "probs": {c: round(float(q) * 100, 1) for c, q in zip(cats, final.probs)},
                  "starts": sum(len(v) for v in final.starts.values()),
                  "benched": sum(len(v) for v in final.benched.values()),
                  "proj": stat_out(sf_me, final.rem)},
        "opp_proj": stat_out(sf_op, opp_rem),
        "so_far": {"me": stat_out(sf_me, np.zeros(len(STATS))), "opp": stat_out(sf_op, np.zeros(len(STATS)))},
        "moves": [{"day": day_label(m.day), "drop": pinfo(m.drop), "add": pinfo(m.add),
                   "add_starts": [day_label(d) for d in final.starts.get(m.add, [])],
                   "gain": round(m.gain * (100 if objective == "win" else 1), 2)}
                  for m in sorted(moves, key=lambda m: m.day)],
        "grid_before": grid(my_base, base_eval.starts, base_eval.benched, base_eval.rosters),
        "grid_after": grid(my_base, final.starts, final.benched, final.rosters,
                           extra=[m.add for m in moves]),
        "grid_opp": grid(opp_base, opp_starts, opp_benched, roster_by_day(ctx, opp_base, [])),
        "board": board_rows,
        "roster": [pinfo(pid) for pid in my_rows.sort_values("value").index],
    }
