#!/usr/bin/env python3
"""
durant.py - a reimplementation of Josh Lloyd's DURANT / DURANT H2H fantasy
basketball category rankings (Basketball Monster), next to the standard
9-cat z-score ranking that Yahoo/ESPN/BBM use by default.

DURANT = "Dynamic Unbiased Rankings Applying Normalised Transformations".

What is public about DURANT (Josh Lloyd, "Understanding DURANT and DURANT H2H"):
  * Each category is put through a Yeo-Johnson power transform, THEN standardised,
    instead of z-scoring the raw (heavily skewed) stat. This shrinks the gap an
    extreme outlier (e.g. 3+ blocks/game) gets over everyone else.
  * The reference mean/spread come from the full NBA player sample, not the
    rostered pool of one league.
  * "Minus 1" in both versions: the player's weakest category is dropped,
    because in H2H you can build around one hole (punt FT% with Giannis, etc).
  * DURANT     : all 9 cats at weight 1.00 except turnovers at 0.50; worst
                 one dropped -> judged on best 8.
  * DURANT H2H : turnovers excluded; weights PTS 1.00, REB 0.94, AST 0.75,
                 FG% 0.60, 3PM 0.60, BLK 0.60, STL 0.60, FT% 0.60; worst of
                 the remaining 8 dropped -> judged on best 7.

What is NOT public (and so is a best guess here, all configurable):
  * per-game vs totals  -> per-game by default (BBM's default view), --totals flag
  * how FG%/FT% "impact" is built -> (pct - league pct) * attempts, the
    standard volume-weighted method BBM's normal z-scores use
  * what "full NBA sample" means for low-minute guys -> min games / mpg filter
  * whether Minus 1 drops the lowest weighted or unweighted category
    -> weighted (the "adjusted values" BBM displays), --drop-unweighted flag
  * how the final number is scaled -> weighted sum / number of cats counted,
    which lands on the same rough scale as BBM's "Value" column

Usage:
  python durant.py stats.csv                     # per-game, prints top 50
  python durant.py stats.csv --top 150 -o out.csv
  python durant.py stats.csv --totals            # season totals instead
  python durant.py stats.csv --punt ft --punt to # leave categories out

Input CSV: either the per-player season totals format from
github.com/EasySportsApps/nba_api_25_26_data, the output of fetch_stats.py,
or any CSV with columns:
  name, team, g, mpg, pts, fg3m, reb, ast, stl, blk, tov, fgm, fga, ftm, fta
(per-game numbers).
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd
from sklearn.preprocessing import PowerTransformer

CATS = ["pts", "fg3m", "reb", "ast", "stl", "blk", "fg", "ft", "tov"]
LABELS = {"pts": "PTS", "fg3m": "3PM", "reb": "REB", "ast": "AST", "stl": "STL",
          "blk": "BLK", "fg": "FG%", "ft": "FT%", "tov": "TO"}

STANDARD_WEIGHTS = {c: 1.0 for c in CATS}
DURANT_WEIGHTS = {**{c: 1.0 for c in CATS}, "tov": 0.5}
DURANT_H2H_WEIGHTS = {"pts": 1.00, "reb": 0.94, "ast": 0.75, "fg": 0.60,
                      "fg3m": 0.60, "blk": 0.60, "stl": 0.60, "ft": 0.60,
                      "tov": 0.0}


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def load_stats(path: str) -> pd.DataFrame:
    """Return one row per player with per-game stats in the column names above."""
    raw = pd.read_csv(path)
    cols = set(raw.columns)

    if {"one_point_made", "two_point_made", "three_point_made"} <= cols:
        # EasySportsApps nba_api wide format: season totals
        g = raw["wins"] + raw["losses"]
        df = pd.DataFrame({
            "name": raw["player_name"], "team": raw["team"], "g": g,
            "mpg": raw["minutes_played"] / g,
            "pts": (raw["one_point_made"] + 2 * raw["two_point_made"]
                    + 3 * raw["three_point_made"]) / g,
            "fg3m": raw["three_point_made"] / g,
            "reb": (raw["offensive_rebounds"] + raw["defensive_rebounds"]) / g,
            "ast": raw["assists"] / g, "stl": raw["steals"] / g,
            "blk": raw["blocks"] / g, "tov": raw["turnovers"] / g,
            "fgm": (raw["two_point_made"] + raw["three_point_made"]) / g,
            "fga": (raw["two_point_attempted"] + raw["three_point_attempted"]) / g,
            "ftm": raw["one_point_made"] / g, "fta": raw["one_point_attempted"] / g,
        })
    elif {"PLAYER_NAME", "GP", "FG3M"} <= cols:
        # nba_api LeagueDashPlayerStats(per_mode_detailed="PerGame")
        df = pd.DataFrame({
            "name": raw["PLAYER_NAME"], "team": raw["TEAM_ABBREVIATION"],
            "g": raw["GP"], "mpg": raw["MIN"], "pts": raw["PTS"],
            "fg3m": raw["FG3M"], "reb": raw["REB"], "ast": raw["AST"],
            "stl": raw["STL"], "blk": raw["BLK"], "tov": raw["TOV"],
            "fgm": raw["FGM"], "fga": raw["FGA"], "ftm": raw["FTM"], "fta": raw["FTA"],
        })
    else:
        need = {"name", "g", "mpg", "pts", "fg3m", "reb", "ast", "stl", "blk",
                "tov", "fgm", "fga", "ftm", "fta"}
        missing = need - cols
        if missing:
            sys.exit(f"Unrecognised CSV format; missing columns: {sorted(missing)}")
        df = raw.copy()
        if "team" not in df:
            df["team"] = ""
    df = df[df["g"] > 0].reset_index(drop=True)
    return df


# --------------------------------------------------------------------------- #
# Category inputs
# --------------------------------------------------------------------------- #
def category_inputs(df: pd.DataFrame, ref: pd.Index) -> pd.DataFrame:
    """Raw value per category, higher = better. Percentages become volume-weighted
    'impact' relative to the reference group's aggregate percentage."""
    out = pd.DataFrame(index=df.index)
    for c in ["pts", "fg3m", "reb", "ast", "stl", "blk"]:
        out[c] = df[c]
    out["tov"] = -df["tov"]
    r = df.loc[ref]
    fg_lg = r["fgm"].sum() / r["fga"].sum()
    ft_lg = r["ftm"].sum() / r["fta"].sum()
    out["fg"] = df["fgm"] - fg_lg * df["fga"]   # = (FG% - lg FG%) * FGA
    out["ft"] = df["ftm"] - ft_lg * df["fta"]
    return out


def _combine(vals: pd.DataFrame, weights: dict, cats: list[str], minus_one: bool,
             drop_unweighted: bool) -> tuple[pd.Series, pd.Series]:
    w = pd.Series({c: weights[c] for c in cats})
    w = w[w > 0]
    used = list(w.index)
    weighted = vals[used] * w
    dropped = pd.Series("", index=vals.index)
    if minus_one:
        basis = vals[used] if drop_unweighted else weighted
        worst = basis.idxmin(axis=1)
        dropped = worst.map(LABELS)
        mask = pd.DataFrame({c: worst != c for c in used})
        weighted = weighted.where(mask, 0.0)
        n = len(used) - 1
    else:
        n = len(used)
    return weighted.sum(axis=1) / n, dropped


# --------------------------------------------------------------------------- #
# Standard 9-cat z-scores (what Yahoo / ESPN / BBM "Value" do)
# --------------------------------------------------------------------------- #
def standard_rankings(df: pd.DataFrame, pool_size: int = 156,
                      cats: list[str] = CATS, max_iter: int = 50) -> pd.DataFrame:
    """Z-score each category against the top `pool_size` players (12 teams x 13
    by default), iterating until the pool is stable, then average."""
    pool = df["mpg"].nlargest(pool_size).index
    for _ in range(max_iter):
        x = category_inputs(df, pool)
        q = x.loc[pool]
        z = (x - q.mean()) / q.std(ddof=0)
        val = z[cats].mean(axis=1)
        new_pool = val.nlargest(pool_size).index
        if set(new_pool) == set(pool):
            break
        pool = new_pool
    z.columns = [f"z_{c}" for c in z.columns]
    z["value"] = val
    return z


# --------------------------------------------------------------------------- #
# DURANT
# --------------------------------------------------------------------------- #
def durant_category_values(df: pd.DataFrame, fit_min_games: int = 10,
                           fit_min_mpg: float = 0.0) -> pd.DataFrame:
    """Yeo-Johnson transform each category (fit on the NBA-wide sample), then
    standardise against that same sample."""
    fit = df.index[(df["g"] >= fit_min_games) & (df["mpg"] >= fit_min_mpg)]
    x = category_inputs(df, fit)
    out = pd.DataFrame(index=df.index)
    for c in CATS:
        pt = PowerTransformer(method="yeo-johnson", standardize=True)
        pt.fit(x.loc[fit, [c]].values)
        out[c] = pt.transform(x[[c]].values).ravel()
    return out


def durant_rankings(df: pd.DataFrame, cats: list[str] = CATS, h2h: bool = False,
                    fit_min_games: int = 10, fit_min_mpg: float = 0.0,
                    drop_unweighted: bool = False,
                    minus_one: bool = True) -> pd.DataFrame:
    vals = durant_category_values(df, fit_min_games, fit_min_mpg)
    weights = DURANT_H2H_WEIGHTS if h2h else DURANT_WEIGHTS
    score, dropped = _combine(vals, weights, cats, minus_one=minus_one,
                              drop_unweighted=drop_unweighted)
    tag = "dh2h" if h2h else "d"
    out = vals.add_prefix(f"{tag}_")
    out[f"{tag}_value"] = score
    out[f"{tag}_dropped"] = dropped
    return out


# --------------------------------------------------------------------------- #
# Auction dollars (rough: value over replacement, scaled to the league budget)
# --------------------------------------------------------------------------- #
def dollars(value: pd.Series, teams: int = 12, roster: int = 13,
            budget: int = 200, min_bid: int = 1) -> pd.Series:
    n = teams * roster
    order = value.sort_values(ascending=False)
    repl = order.iloc[n] if len(order) > n else order.iloc[-1]
    above = (value - repl).clip(lower=0)
    spend = teams * budget - n * min_bid
    d = above / above.loc[order.index[:n]].sum() * spend + min_bid
    d[value.rank(ascending=False, method="first") > n] = 0
    return d.round(1)


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
def build(df: pd.DataFrame, totals: bool = False, punt: list[str] | None = None,
          teams: int = 12, roster: int = 13, fit_min_games: int = 10,
          drop_unweighted: bool = False) -> pd.DataFrame:
    punt = punt or []
    cats = [c for c in CATS if c not in punt]
    work = df.copy()
    if totals:
        for c in ["pts", "fg3m", "reb", "ast", "stl", "blk", "tov",
                  "fgm", "fga", "ftm", "fta"]:
            work[c] = work[c] * work["g"]

    std = standard_rankings(work, pool_size=teams * roster, cats=cats)
    d = durant_rankings(work, cats=cats, h2h=False, fit_min_games=fit_min_games,
                        drop_unweighted=drop_unweighted)
    h = durant_rankings(work, cats=cats, h2h=True, fit_min_games=fit_min_games,
                        drop_unweighted=drop_unweighted)

    res = pd.concat([df, std, d, h], axis=1)
    res["rank_9cat"] = res["value"].rank(ascending=False, method="min").astype(int)
    res["rank_durant"] = res["d_value"].rank(ascending=False, method="min").astype(int)
    res["rank_h2h"] = res["dh2h_value"].rank(ascending=False, method="min").astype(int)
    res["durant_$"] = dollars(res["d_value"], teams, roster)
    res["h2h_$"] = dollars(res["dh2h_value"], teams, roster)
    res["h2h_vs_9cat"] = res["rank_9cat"] - res["rank_h2h"]
    return res.sort_values("dh2h_value", ascending=False)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv")
    ap.add_argument("-o", "--out", help="write full results to this CSV")
    ap.add_argument("--top", type=int, default=50)
    ap.add_argument("--totals", action="store_true",
                    help="rank on season totals instead of per-game")
    ap.add_argument("--punt", action="append", default=[], choices=CATS,
                    help="leave a category out (repeatable)")
    ap.add_argument("--teams", type=int, default=12)
    ap.add_argument("--roster", type=int, default=13)
    ap.add_argument("--min-games", type=int, default=0,
                    help="hide players with fewer games from the printout")
    ap.add_argument("--fit-min-games", type=int, default=10,
                    help="min games to be in the NBA-wide DURANT reference sample")
    ap.add_argument("--drop-unweighted", action="store_true",
                    help="Minus 1 drops the lowest unweighted category")
    a = ap.parse_args()

    res = build(load_stats(a.csv), totals=a.totals, punt=a.punt, teams=a.teams,
                roster=a.roster, fit_min_games=a.fit_min_games,
                drop_unweighted=a.drop_unweighted)
    if a.out:
        res.round(3).to_csv(a.out, index=False)
        print(f"wrote {len(res)} players to {a.out}")

    show = res[res["g"] >= a.min_games].head(a.top)
    cols = ["rank_h2h", "rank_durant", "rank_9cat", "name", "team", "g", "mpg",
            "dh2h_value", "d_value", "value", "dh2h_dropped", "d_dropped", "h2h_$"]
    with pd.option_context("display.max_rows", None, "display.width", 200):
        print(show[cols].round(2).to_string(index=False))


if __name__ == "__main__":
    main()
