"""
Category valuation engine.

A ranking "system" is a preset of five switches:

  reference  who sets the scale (mean / spread) of each category
             'rostered' -> top N players, N = teams x roster (Yahoo/ESPN/BBM style)
             'waivers'  -> top N x 1.5: rostered players plus the realistic waiver /
                           streaming pool
             'nba'      -> every eligible NBA player (DURANT)
  transform  Yeo-Johnson power transform before standardising (DURANT)
  weights    'equal' | 'durant_h2h' (Josh Lloyd's H2H weights) |
             'variance' (G-score: shrink categories that are noisy week to week,
             Rosenof, "Static quantification of player value for fantasy basketball")
  tov        turnover weight multiplier (1, 0.5, 0)
  minus_one  drop each player's weakest category (DURANT)

Eligibility scales with the season: a player is in the reference / transform
sample if he has played at least 25% of the max games anyone has played and
averages 10+ minutes. (Day 5 of the season: 2 games. End of season: 21 games.)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd
from sklearn.preprocessing import PowerTransformer

CATS = ["fg", "ft", "fg3m", "pts", "reb", "ast", "stl", "blk", "tov"]   # display order used across the app
LABELS = {"pts": "PTS", "fg3m": "3PM", "reb": "REB", "ast": "AST", "stl": "STL",
          "blk": "BLK", "fg": "FG%", "ft": "FT%", "tov": "TO"}
COUNT_STATS = ["pts", "fg3m", "reb", "ast", "stl", "blk", "tov",
               "fgm", "fga", "ftm", "fta"]

# Week-to-week noise relative to between-player spread, per category:
# tau^2 / sigma^2 where tau = within-player per-game std (top-156 pool average)
# and sigma = between-player std of per-game means (top-156 pool).
# Estimated from 2025-26 game logs by analysis/estimate_noise.py.
NOISE_RATIO = {"pts": 1.47, "fg3m": 1.95, "reb": 1.37, "ast": 1.13, "stl": 7.71,
               "blk": 3.23, "fg": 6.51, "ft": 6.00, "tov": 3.02}

# Per-game variance / mean for counting stats, and overdispersion vs binomial
# for FG/FT (weekly). From 2025-26 logs, analysis/estimate_dispersion.py.
DISPERSION = {"pts": 2.95, "fg3m": 1.14, "reb": 1.33, "ast": 1.22, "stl": 1.07,
              "blk": 1.13, "tov": 0.99, "fg": 0.85, "ft": 1.01}

GAMES_PER_WEEK = 3.5
_g = {c: 1 / math.sqrt(1 + r / GAMES_PER_WEEK) for c, r in NOISE_RATIO.items()}
WEIGHT_SETS = {
    "equal": {c: 1.0 for c in CATS},
    "durant_h2h": {"pts": 1.00, "reb": 0.94, "ast": 0.75, "fg": 0.60, "fg3m": 0.60,
                   "blk": 0.60, "stl": 0.60, "ft": 0.60, "tov": 1.0},
    "variance": {c: round(v / max(_g.values()), 3) for c, v in _g.items()},
}
WEIGHT_LABELS = {"equal": "Equal", "durant_h2h": "DURANT H2H",
                 "variance": "By weekly noise (G-score)"}
REFERENCES = {"rostered": "Rostered players", "waivers": "Rostered + waiver pool",
              "nba": "Whole NBA"}
WAIVER_DEPTH = 1.5
ELIG_FRAC, ELIG_MPG = 0.25, 10.0


@dataclass
class System:
    key: str
    label: str
    reference: str = "rostered"
    transform: bool = False
    weights: str = "equal"
    tov: float = 1.0
    minus_one: bool = False
    center: str = "pool"
    blurb: str = ""

    def spec(self) -> dict:
        return {"reference": self.reference, "transform": self.transform,
                "weights": self.weights, "tov": self.tov, "minus_one": self.minus_one,
                "center": self.center}


ALL_SYSTEMS = {
    "durant_h2h": System("durant_h2h", "DURANT H2H (Josh Lloyd)", reference="nba", transform=True,
                         weights="durant_h2h", tov=0.0, minus_one=True,
                         blurb="Josh Lloyd: transform vs the whole NBA, H2H weights, no TO, "
                               "worst category dropped."),
    "tz": System("tz", "Category Lab", transform=True, tov=0.5,
                 blurb="DURANT's transform and half-weight turnovers, scaled against rostered "
                       "players, equal weights, no Minus 1. Did best in the 2025-26 draft simulations."),
    "z": System("z", "Standard 9-cat",
                blurb="Z-score vs the top rostered players, averaged. What Yahoo/ESPN/BBM show."),
    "g": System("g", "G-score (H2H)", weights="variance",
                blurb="Z-score with each category shrunk by how noisy it is week to week."),
    "durant": System("durant", "DURANT", reference="nba", transform=True, tov=0.5,
                     minus_one=True,
                     blurb="Josh Lloyd: transform vs the whole NBA, TO at half weight, "
                           "worst category dropped."),
}

# The presets offered in the app. The rest stay available to the API and the
# analysis scripts (and can be shown again by listing them here).
SHOWN = ["durant_h2h", "z"]
SYSTEMS = {k: ALL_SYSTEMS[k] for k in SHOWN}

DEFAULT_SYSTEM = "durant_h2h"


def make_system(base: str | System = "durant_h2h", **overrides) -> System:
    sy = ALL_SYSTEMS[base] if isinstance(base, str) else base
    ov = {k: v for k, v in overrides.items() if v is not None}
    if not ov:
        return sy
    out = replace(sy, **ov)
    if out.spec() != sy.spec():
        out = replace(out, key="custom", label="Custom")
    return out


def eligible(df: pd.DataFrame) -> pd.Index:
    if df.empty:
        return df.index
    gmin = max(1, math.ceil(ELIG_FRAC * df["g"].max()))
    e = df.index[(df["g"] >= gmin) & (df["mpg"] >= ELIG_MPG)]
    if len(e) < 100:
        e = df.index[df["g"] >= gmin]
    return e if len(e) >= 30 else df.index


def pool_candidates(df: pd.DataFrame) -> pd.Index:
    """Who may be in the rostered / waiver pool: looser than eligible(), because
    injured stars with few games are still rostered. 10% of max games (1 game in
    week one, 9 by season's end)."""
    if df.empty:
        return df.index
    gmin = max(1, math.ceil(0.10 * df["g"].max()))
    return df.index[df["g"] >= gmin]


def category_weights(system: System, cats: list[str]) -> pd.Series:
    base = WEIGHT_SETS[system.weights]
    w = pd.Series({c: base.get(c, 1.0) for c in cats}, dtype=float)
    if "tov" in w:
        w["tov"] *= system.tov
    return w[w > 0]


# --------------------------------------------------------------------------- #
def category_inputs(df: pd.DataFrame, ref: pd.Index) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    for c in ["pts", "fg3m", "reb", "ast", "stl", "blk"]:
        out[c] = df[c]
    out["tov"] = -df["tov"]
    r = df.loc[ref]
    fg_lg = r["fgm"].sum() / max(r["fga"].sum(), 1e-9)
    ft_lg = r["ftm"].sum() / max(r["fta"].sum(), 1e-9)
    out["fg"] = df["fgm"] - fg_lg * df["fga"]
    out["ft"] = df["ftm"] - ft_lg * df["fta"]
    return out


def _standardise(x: pd.DataFrame, ref: pd.Index, transform: bool, fit: pd.Index,
                 center: pd.Index | None = None) -> pd.DataFrame:
    center = ref if center is None or len(center) == 0 else center
    out = pd.DataFrame(index=x.index)
    for c in x.columns:
        col = x[[c]].values.astype(float)
        if transform:
            pt = PowerTransformer(method="yeo-johnson", standardize=False)
            pt.fit(col[x.index.get_indexer(fit)])
            col = pt.transform(col)
        s = pd.Series(col.ravel(), index=x.index)
        sd = s.loc[ref].std(ddof=0)
        out[c] = (s - s.loc[center].mean()) / (sd if sd > 0 else 1.0)
    return out


def score(df: pd.DataFrame, system: System | str, cats: list[str] | None = None,
          pool_size: int = 156, minus_one: bool | None = None) -> pd.DataFrame:
    """Per-category values (v_<cat>), overall `value`, and `dropped`.
    minus_one: None = the system's setting, True/False = force."""
    if isinstance(system, str):
        system = ALL_SYSTEMS[system]
    cats = list(cats or CATS)
    w = category_weights(system, cats)
    used = list(w.index)
    m1 = system.minus_one if minus_one is None else minus_one
    elig = eligible(df)

    def combine(vals: pd.DataFrame):
        weighted = vals[used] * w
        dropped = pd.Series("", index=vals.index)
        n = len(used)
        if m1 and n > 1:
            worst = weighted.idxmin(axis=1)
            dropped = worst.map(LABELS)
            weighted = weighted.mask(pd.DataFrame({c: worst == c for c in used}), 0.0)
            n -= 1
        return weighted.sum(axis=1) / n, dropped

    if system.reference == "nba":
        x = category_inputs(df, elig)
        vals = _standardise(x, elig, system.transform, elig)
        value, dropped = combine(vals)
    else:
        size = pool_size if system.reference == "rostered" else round(pool_size * WAIVER_DEPTH)
        cand = pool_candidates(df)
        size = min(size, len(cand))
        order = df.loc[cand, "mpg"].sort_values(ascending=False).index
        for _ in range(40):
            pool = order[:size]
            # replacement level: the next tier down (the realistic waiver pool)
            repl = order[size:size + max(round(size * (WAIVER_DEPTH - 1)), 10)] \
                if system.center == "replacement" else None
            x = category_inputs(df, pool)
            vals = _standardise(x, pool, system.transform, elig, repl)
            value, dropped = combine(vals)
            new_order = value.loc[cand].sort_values(ascending=False).index
            if set(new_order[:size]) == set(pool) and (
                    repl is None or set(new_order[size:size + len(repl)]) == set(repl)):
                break
            order = new_order

    out = vals[CATS].add_prefix("v_")
    out["value"] = value
    out["dropped"] = dropped
    return out


def per_game_to_totals(df: pd.DataFrame) -> pd.DataFrame:
    t = df.copy()
    for c in COUNT_STATS:
        t[c] = t[c] * t["g"]
    return t
