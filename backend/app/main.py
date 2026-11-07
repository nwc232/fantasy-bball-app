from __future__ import annotations

import os
import time

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import engine as E
from . import espn
from . import league as L
from .store import STORE, current_year

app = FastAPI(title="Fantasy Category Rankings")
FRONTEND = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")

STAT_COLS = ["pts", "fg3m", "reb", "ast", "stl", "blk", "tov"]


def _system(system: str, ref=None, center=None, transform=None, weights=None, tov=None,
            m1=None) -> E.System:
    if system not in E.SYSTEMS:
        raise HTTPException(400, "unknown system")
    if ref is not None and ref not in E.REFERENCES:
        raise HTTPException(400, "unknown ref")
    if weights is not None and weights not in E.WEIGHT_SETS:
        raise HTTPException(400, "unknown weights")
    return E.make_system(system, reference=ref, center=center,
                         transform=None if transform is None else bool(transform),
                         weights=weights, tov=tov,
                         minus_one=None if m1 is None else bool(m1))


def _punts(p: str | None) -> list[str]:
    return [x for x in (p or "").split(",") if x in E.CATS]


def _pick_split(frames: dict, split: str) -> tuple[str, pd.DataFrame]:
    if split in frames:
        return split, frames[split]
    for k in ["season", "proj", "last30", "prev"]:
        if k in frames:
            return k, frames[k]
    raise HTTPException(503, "No player stats available.")


def _player_json(df: pd.DataFrame, cats: list[str], team_names: dict | None = None) -> list[dict]:
    out = []
    fg = np.where(df["fga"] > 0, df["fgm"] / df["fga"].replace(0, np.nan), np.nan)
    ft = np.where(df["fta"] > 0, df["ftm"] / df["fta"].replace(0, np.nan), np.nan)
    for i, r in enumerate(df.itertuples(index=False)):
        d = r._asdict()
        row = {"id": d["id"], "name": d["name"], "team": d["team"], "pos": d.get("pos", ""),
               "injury": d.get("injury", ""), "g": int(d["g"]), "mpg": round(float(d["mpg"]), 1),
               "rank": int(d["rank"]), "value": round(float(d["value"]), 3),
               "dropped": d.get("dropped", ""),
               "stats": {**{c: round(float(d[c]), 1) for c in STAT_COLS},
                         "fg": None if np.isnan(fg[i]) else round(float(fg[i]), 3),
                         "ft": None if np.isnan(ft[i]) else round(float(ft[i]), 3),
                         "fga": round(float(d["fga"]), 1), "fta": round(float(d["fta"]), 1)},
               "v": {c: round(float(d[f"v_{c}"]), 2) for c in cats}}
        if "rank_z" in d:
            row["rank_z"] = int(d["rank_z"])
        if team_names is not None:
            ft_id = int(d.get("fantasy_team", 0) or 0)
            row["fantasy_team"] = ft_id
            row["fantasy_team_name"] = team_names.get(ft_id, "FA")
        if "slot" in d:
            row["slot"] = d["slot"]
        out.append(row)
    return out


# --------------------------------------------------------------------------- #
@app.get("/api/meta")
def meta():
    return {
        "year": current_year(),
        "systems": [{"key": s.key, "label": s.label, "blurb": s.blurb, "spec": s.spec()}
                    for s in E.SYSTEMS.values()],
        "options": {"reference": E.REFERENCES, "weights": E.WEIGHT_LABELS,
                    "center": {"pool": "Pool average", "replacement": "Waiver level"},
                    "tov": {"1.0": "Full", "0.5": "Half", "0.0": "Ignore"}},
        "splits": {k: v[0] for k, v in espn.SPLITS.items()},
        "cats": [{"key": c, "label": E.LABELS[c]} for c in E.CATS],
    }


@app.get("/api/rankings")
def rankings(year: int = 0, split: str = "season", system: str = "tz", punt: str = "",
             teams: int = 12, roster: int = 13, league: str | None = None,
             refresh: bool = False, m1: int | None = None, ref: str | None = None,
             center: str | None = None, transform: int | None = None,
             weights: str | None = None, tov: float | None = None):
    sy = _system(system, ref, center, transform, weights, tov, m1)
    year = year or current_year()
    team_names = None
    cats = E.CATS
    if league:
        lg = STORE.league(league)
        if not lg:
            raise HTTPException(404, "League not loaded; import it again.")
        frames, source = lg["frames"], lg["source"]
        cats = lg["parsed"]["cats"]
        teams = len(lg["parsed"]["teams"])
        roster = lg["parsed"]["roster_size"]
        team_names = {t["id"]: t["name"] for t in lg["parsed"]["teams"]}
    else:
        frames, source = STORE.pool(year, force=refresh)
    used, df = _pick_split(frames, split)
    punts = _punts(punt)
    valued = L.value_pool(df, sy, cats, punts, teams * roster)
    use = [c for c in cats if c not in punts] or cats
    valued["rank_z"] = E.score(df, "z", cats=use, pool_size=teams * roster)["value"] \
        .rank(ascending=False, method="min").astype(int)
    valued = valued.sort_values("value", ascending=False)
    return {"source": source, "split": used, "available_splits": list(frames),
            "cats": cats, "punts": punts, "system": sy.key, "spec": sy.spec(),
            "minus_one": sy.minus_one,
            "players": _player_json(valued, cats, team_names)}


class ImportBody(BaseModel):
    league_id: str
    year: int = 0
    espn_s2: str | None = None
    swid: str | None = None


@app.post("/api/league/import")
def league_import(body: ImportBody):
    try:
        key = STORE.import_league(body.league_id.strip(), body.year or current_year(),
                                  body.espn_s2, body.swid)
    except espn.ESPNError as e:
        raise HTTPException(400, str(e))
    return {"key": key}


@app.post("/api/league/demo")
def league_demo():
    return {"key": STORE.demo_league()}


def _league_ctx(key: str, split: str, sy: E.System, punt: str):
    lg = STORE.league(key)
    if not lg:
        raise HTTPException(404, "League not loaded; import it again.")
    p = lg["parsed"]
    used, df = _pick_split(lg["frames"], split)
    punts = _punts(punt)
    pool = L.value_pool(df, sy, p["cats"], punts, len(p["teams"]) * p["roster_size"])
    rosters = {t["id"]: L.roster_rows(t, pool) for t in p["teams"]}
    return lg, p, used, pool, punts, rosters


@app.get("/api/league/{key}")
def league_view(key: str, split: str = "season", system: str = "tz", punt: str = "",
                period: int = 0, m1: int | None = None, ref: str | None = None,
                center: str | None = None, transform: int | None = None,
                weights: str | None = None, tov: float | None = None):
    sy = _system(system, ref, center, transform, weights, tov, m1)
    lg, p, used, pool, punts, rosters = _league_ctx(key, split, sy, punt)
    cats = p["cats"]
    period = period or p["current_period"]
    team_names = {t["id"]: t["name"] for t in p["teams"]}
    teams = []
    for t in p["teams"]:
        r = rosters[t["id"]].copy()
        r["rank"] = r["rank"].fillna(0)
        for c in [f"v_{c}" for c in E.CATS]:
            if c in r:
                r[c] = r[c].fillna(0)
        r["dropped"] = r.get("dropped", "").fillna("") if "dropped" in r else ""
        for col in ["name", "team", "pos", "injury"]:
            r[col] = r[col].fillna("" if col != "name" else "Unknown player")
        r = r.sort_values("value", ascending=False)
        teams.append({"id": t["id"], "name": t["name"], "owner": t["owner"], "record": t["record"],
                      "players": _player_json(r, cats)})
    return {
        "key": key, "name": p["name"], "year": p["year"], "source": lg["source"],
        "scoring_type": p["scoring_type"], "cats": cats, "unsupported_cats": p["unsupported_cats"],
        "punts": punts, "split": used, "available_splits": list(lg["frames"]),
        "starters": p["starters"], "roster_size": p["roster_size"],
        "periods": sorted(p["matchup_periods"]), "period": period,
        "updated": lg["ts"],
        "current_period": p["current_period"], "has_schedule": bool(lg["sched"]),
        "teams": teams,
        "power": L.power_table(p, rosters, cats),
        "matchups": L.matchups(p, rosters, cats, period, lg["sched"]),
        "free_agents": _player_json(pool[pool["fantasy_team"] == 0].sort_values("value", ascending=False)
                                    .head(60), cats, team_names),
    }


@app.post("/api/league/{key}/refresh")
def league_refresh(key: str):
    try:
        lg = STORE.refresh_league(key)
    except KeyError:
        raise HTTPException(404, "League not loaded; import it again.")
    except espn.ESPNError as e:
        raise HTTPException(400, str(e))
    return {"updated": lg["ts"]}


# --------------------------------------------------------------------------- #
# Explain: why is a player ranked where he is, setting by setting
# --------------------------------------------------------------------------- #
SWITCH_ORDER = ["reference", "transform", "center", "weights", "tov", "minus_one"]


def _switch_label(k: str, v) -> str:
    if k == "reference":
        return {"rostered": "Scale against rostered players",
                "waivers": "Scale against rostered + waiver pool",
                "nba": "Scale against the whole NBA"}[v]
    if k == "transform":
        return "Transform on" if v else "Transform off"
    if k == "center":
        return "Zero at waiver level" if v == "replacement" else "Zero at pool average"
    if k == "weights":
        return f"{E.WEIGHT_LABELS[v]} weights"
    if k == "tov":
        return {1.0: "Turnovers full weight", 0.5: "Turnovers half weight",
                0.0: "Ignore turnovers"}[float(v)]
    return "Minus 1 on" if v else "Minus 1 off"


@app.get("/api/explain")
def explain(player: str, target: str = "durant_h2h", year: int = 0, split: str = "season",
            system: str = "tz", punt: str = "", teams: int = 12, roster: int = 13,
            league: str | None = None, m1: int | None = None, ref: str | None = None,
            center: str | None = None, transform: int | None = None,
            weights: str | None = None, tov: float | None = None):
    cur = _system(system, ref, center, transform, weights, tov, m1)
    if target not in E.SYSTEMS:
        raise HTTPException(400, "unknown target")
    tgt = E.SYSTEMS[target]
    year = year or current_year()
    cats = E.CATS
    if league:
        lg = STORE.league(league)
        if not lg:
            raise HTTPException(404, "League not loaded; import it again.")
        frames, cats = lg["frames"], lg["parsed"]["cats"]
        teams, roster = len(lg["parsed"]["teams"]), lg["parsed"]["roster_size"]
    else:
        frames, _ = STORE.pool(year)
    _, df = _pick_split(frames, split)
    idx = df.index[df["id"] == player]
    if not len(idx):
        raise HTTPException(404, "Player not found in this stat window.")
    i = idx[0]
    use = [c for c in cats if c not in _punts(punt)] or cats
    size = teams * roster
    cache: dict = {}

    def run(sy: E.System):
        key = tuple(sorted(sy.spec().items()))
        if key not in cache:
            sc = E.score(df, sy, cats=use, pool_size=size)
            cache[key] = (sc, int(sc["value"].rank(ascending=False, method="min")[i]))
        return cache[key]

    def detail(sy: E.System):
        sc, rank = run(sy)
        w = E.category_weights(sy, use)
        row = sc.loc[i]
        return {"rank": rank, "value": round(float(row["value"]), 3),
                "dropped": row["dropped"], "spec": sy.spec(), "label": sy.label,
                "cats": {c: {"v": round(float(row[f"v_{c}"]), 2),
                             "w": round(float(w.get(c, 0.0)), 2),
                             "contrib": round(float(row[f"v_{c}"] * w.get(c, 0.0)), 2)}
                         for c in use}}

    cs, ts = cur.spec(), tgt.spec()
    diffs = [k for k in SWITCH_ORDER if cs[k] != ts[k]]
    base_rank = run(cur)[1]
    singles, path, step = [], [], cur
    for k in diffs:
        one = E.make_system(cur, **{k: ts[k]})
        singles.append({"switch": k, "label": _switch_label(k, ts[k]), "rank": run(one)[1],
                        "delta": base_rank - run(one)[1]})
        prev = run(step)[1]
        step = E.make_system(step, **{k: ts[k]})
        path.append({"switch": k, "label": _switch_label(k, ts[k]), "rank": run(step)[1],
                     "delta": prev - run(step)[1]})
    presets = [{"key": s.key, "label": s.label, "rank": run(s)[1]} for s in E.SYSTEMS.values()]
    r = df.loc[i]
    return {"player": {"id": player, "name": r["name"], "team": r["team"], "g": int(r["g"]),
                       "mpg": round(float(r["mpg"]), 1)},
            "current": detail(cur), "target": detail(tgt), "target_key": target,
            "singles": singles, "path": path, "presets": presets}


class TradeBody(BaseModel):
    team_a: int
    team_b: int = 0
    a_gives: list[str] = []
    b_gives: list[str] = []
    a_drops: list[str] = []
    b_drops: list[str] = []
    split: str = "season"
    system: str = "tz"
    punt: str = ""
    m1: int | None = None
    ref: str | None = None
    center: str | None = None
    transform: int | None = None
    weights: str | None = None
    tov: float | None = None


@app.post("/api/league/{key}/trade")
def trade(key: str, body: TradeBody):
    lg, p, used, pool, punts, _ = _league_ctx(key, body.split, _system(body.system, body.ref, body.center, body.transform, body.weights, body.tov, body.m1), body.punt)
    if not body.a_gives and not body.b_gives:
        raise HTTPException(400, "Pick at least one player to move.")
    rep = L.trade_report(p, pool, p["cats"], body.team_a, body.team_b, body.a_gives,
                         body.b_gives, body.a_drops, body.b_drops)
    rep["cats"] = p["cats"]
    rep["punts"] = punts
    return rep


# --------------------------------------------------------------------------- #
if os.path.isdir(FRONTEND):
    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

    @app.get("/")
    def index():
        return FileResponse(os.path.join(FRONTEND, "index.html"))
