"""
"Fits my team": how much each player would change YOUR weekly odds.

* Players not on your team: the gain from adding him in place of whichever of
  your players he'd best replace (his best 1-for-1 swap).
* Your players: how much better your team is with him than with the best free
  agent you could replace him with. Negative = the free agent fits better.

Odds are typical-week, against every other team in the league, using the same
weekly model as power rankings, and scored the way your league is: "most
categories" leagues use matchup win chance, "each category" leagues use
expected categories won. Because the real scoring is used, a punt build is
handled naturally: categories you can't win anyway add little.

Everything is vectorised: all (candidate, drop) swaps are evaluated at once.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm

from . import engine as E
from . import league as L

STATS = ["pts", "fg3m", "reb", "ast", "stl", "blk", "tov", "fgm", "fga", "ftm", "fta"]
SI = {s: i for i, s in enumerate(STATS)}
IR_SLOT = 13


def _moments(tot: np.ndarray, cats: list[str]):
    """tot: (..., STATS) weekly sums -> mu, var (..., cats)."""
    mu, var = [], []
    for c in cats:
        if c in ("fg", "ft"):
            m, a = (SI["fgm"], SI["fga"]) if c == "fg" else (SI["ftm"], SI["fta"])
            att = np.maximum(tot[..., a], 1e-9)
            p = tot[..., m] / att
            mu.append(p)
            var.append(E.DISPERSION[c] * p * (1 - p) / att)
        else:
            x = tot[..., SI[c]]
            mu.append(x)
            var.append(np.maximum(E.DISPERSION[c] * x, 1e-6))
    return np.stack(mu, -1), np.stack(var, -1)


def _score(mu, var, opp_mu, opp_var, cats, objective):
    """mu/var: (..., K); opp: (O, K) -> mean over opponents of the objective."""
    sign = np.array([-1.0 if c == "tov" else 1.0 for c in cats])
    p = norm.cdf(sign * (mu[..., None, :] - opp_mu) / np.sqrt(var[..., None, :] + opp_var + 1e-12))
    if objective == "cats":
        return p.sum(-1).mean(-1)
    K = p.shape[-1]
    dist = np.zeros(p.shape[:-1] + (K + 1,))
    dist[..., 0] = 1.0
    for k in range(K):
        q = p[..., k:k + 1]
        dist = np.concatenate([dist[..., :1] * (1 - q), dist[..., 1:] * (1 - q) + dist[..., :-1] * q], -1)
    j = np.arange(K + 1)
    win = dist[..., j * 2 > K].sum(-1) + 0.5 * dist[..., j * 2 == K].sum(-1)
    return win.mean(-1)


def team_fit(league: dict, pool: pd.DataFrame, team_id: int) -> dict:
    cats = league["cats"]
    objective = "win" if "MOST" in (league.get("scoring_type") or "") else "cats"
    unit = 100.0 if objective == "win" else 1.0
    pool = pool.drop_duplicates("id").set_index("id", drop=False)
    S = pool[STATS].to_numpy(float)
    idx = {pid: i for i, pid in enumerate(pool.index)}

    teams = {t["id"]: t for t in league["teams"]}
    rows = {tid: L.roster_rows(t, pool.reset_index(drop=True)) for tid, t in teams.items()}

    # opponents' typical weeks
    om, ov = [], []
    for tid, r in rows.items():
        if tid == team_id:
            continue
        g = L.games_in_period(r, None, None, league["starters"])
        m, v = L.project(r, g, cats)
        om.append(m); ov.append(v)
    om, ov = np.array(om), np.array(ov)

    mine = rows[team_id]
    active = mine[(mine["slot"] != IR_SLOT) & mine["id"].isin(pool.index)]
    gpp = float(L.games_in_period(active.assign(slot=0), None, None, league["starters"]).iloc[0]) \
        if len(active) else 3.5
    base_tot = gpp * S[[idx[p] for p in active["id"]]].sum(0)
    base_mu, base_var = _moments(base_tot, cats)
    base = float(_score(base_mu, base_var, om, ov, cats, objective))

    # who can be swapped out: your active players who are actually playing
    drops = [p for p in active["id"] if pool.at[p, "g"] > 0]
    D = np.array([idx[p] for p in drops])

    # candidates: everyone else with a real sample
    gmin = max(1, int(np.ceil(E.ELIG_FRAC * pool["g"].max())))
    mine_ids = set(mine["id"])
    cand = [p for p in pool.index if p not in mine_ids and pool.at[p, "g"] >= gmin]
    C = np.array([idx[p] for p in cand])

    out: dict[str, dict] = {}
    if len(C) and len(D):
        tot = base_tot[None, None, :] + gpp * (S[C][:, None, :] - S[D][None, :, :])   # C x D x STATS
        mu, var = _moments(tot, cats)
        sc = _score(mu, var, om, ov, cats, objective)                                   # C x D
        best_d = sc.argmax(1)
        gains = sc[np.arange(len(C)), best_d] - base
        for i, pid in enumerate(cand):
            out[pid] = {"fit": round(float(gains[i]) * unit, 2), "kind": "add",
                        "swap": pool.at[drops[best_d[i]], "name"]}

        # your players: value over the best free agent who could replace him
        fa_mask = np.array([pool.at[p, "fantasy_team"] == 0 and
                            str(pool.at[p, "status"]) in ("FREEAGENT", "WAIVERS") for p in cand])
        if fa_mask.any():
            fa_sc = sc[fa_mask]                                                        # FA x D
            best_fa = fa_sc.argmax(0)
            fa_ids = [cand[i] for i in np.where(fa_mask)[0]]
            for j, pid in enumerate(drops):
                out[pid] = {"fit": round(float(base - fa_sc[best_fa[j], j]) * unit, 2), "kind": "keep",
                            "swap": pool.at[fa_ids[best_fa[j]], "name"]}
    for pid in mine_ids - set(out):
        out[pid] = {"fit": None, "kind": "keep", "swap": None}       # IR / no stats

    return {"team_id": team_id, "objective": objective, "base": round(base * unit, 2),
            "unit": "pts" if objective == "win" else "cats", "players": out}
