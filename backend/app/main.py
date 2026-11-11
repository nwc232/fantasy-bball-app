from __future__ import annotations

import os
import time

import numpy as np
import pandas as pd
import logging
import math
import traceback

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import engine as E
from . import espn
from . import league as L
from . import stream as ST
from . import build as BUILD
from .store import STORE, current_year

app = FastAPI(title="Fantasy Category Rankings")
log = logging.getLogger("categorylab")

# Optional site password. Set APP_PASSWORD on the host to turn it on; leave it
# unset when running locally. Logging in sets a signed, HttpOnly cookie that lasts
# 30 days. The signing key is derived from the password, so changing the password
# logs everyone out.
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
SESSION_COOKIE = "cl_session"
SESSION_DAYS = 30
PUBLIC_PATHS = {"/login", "/api/login", "/api/health", "/api/logout"}


def _session_key() -> bytes:
    import hashlib
    return hashlib.sha256(("category-lab:" + APP_PASSWORD).encode()).digest()


def _make_session() -> str:
    import hashlib
    import hmac
    exp = str(int(time.time()) + SESSION_DAYS * 86400)
    sig = hmac.new(_session_key(), exp.encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def _valid_session(token: str | None) -> bool:
    import hashlib
    import hmac
    if not token or "." not in token:
        return False
    exp, _, sig = token.partition(".")
    good = hmac.new(_session_key(), exp.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, good) and exp.isdigit() and int(exp) > time.time()


@app.middleware("http")
async def _password_gate(request: Request, call_next):
    path = request.url.path
    if (not APP_PASSWORD or path in PUBLIC_PATHS or path.startswith("/static/")
            or _valid_session(request.cookies.get(SESSION_COOKIE))):
        return await call_next(request)
    if path.startswith("/api/"):
        return JSONResponse(status_code=401, content={"detail": "Please log in again."})
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/login", status_code=303)


class LoginBody(BaseModel):
    password: str


@app.post("/api/login")
async def login(body: LoginBody, request: Request):
    import asyncio
    import secrets
    if not APP_PASSWORD:
        return {"ok": True}
    if not secrets.compare_digest(body.password.encode(), APP_PASSWORD.encode()):
        await asyncio.sleep(0.8)                      # slow down guessing
        raise HTTPException(401, "Wrong password.")
    resp = JSONResponse({"ok": True})
    secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    resp.set_cookie(SESSION_COOKIE, _make_session(), max_age=SESSION_DAYS * 86400,
                    httponly=True, secure=secure, samesite="lax", path="/")
    return resp


@app.post("/api/logout")
def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@app.get("/login")
def login_page():
    return FileResponse(os.path.join(FRONTEND, "login.html"))


@app.get("/api/health")
def health():
    return {"ok": True}


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    """Show the real error in the UI (and the full traceback in the server log)
    instead of a bare 500."""
    log.error("Unhandled error on %s\n%s", request.url.path, traceback.format_exc())
    return JSONResponse(status_code=500, content={
        "detail": f"Server error ({type(exc).__name__}): {exc}. "
                  "The full traceback is in the terminal running the server."})


def _json_safe(o):
    """NaN/inf -> None so a stray missing stat can't break the JSON response."""
    if isinstance(o, float):
        return None if (math.isnan(o) or math.isinf(o)) else o
    if isinstance(o, dict):
        return {k: _json_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_json_safe(v) for v in o]
    if isinstance(o, (np.floating,)):
        return _json_safe(float(o))
    if isinstance(o, (np.integer,)):
        return int(o)
    return o
FRONTEND = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")

STAT_COLS = ["fg3m", "pts", "reb", "ast", "stl", "blk", "tov"]


def _system(system: str, ref=None, center=None, transform=None, weights=None, tov=None,
            m1=None) -> E.System:
    if system not in E.ALL_SYSTEMS:
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
            row["fantasy_team_name"] = team_names.get(
                ft_id, "Rostered (team unknown)" if ft_id < 0 else
                "Waivers" if str(d.get("status", "")).upper() == "WAIVERS" else "FA")
            row["status"] = str(d.get("status", "") or "").upper()
        if "slot" in d:
            row["slot"] = d["slot"]
        row["no_stats"] = int(d["g"]) == 0
        out.append(row)
    return out


# --------------------------------------------------------------------------- #
@app.get("/api/meta")
def meta():
    return {
        "year": current_year(),
        "default_system": E.DEFAULT_SYSTEM,
        "auth": bool(APP_PASSWORD),
        "systems": [{"key": s.key, "label": s.label, "blurb": s.blurb, "spec": s.spec()}
                    for s in E.SYSTEMS.values()],
        "options": {"reference": E.REFERENCES, "weights": E.WEIGHT_LABELS,
                    "center": {"pool": "Pool average", "replacement": "Waiver level"},
                    "tov": {"1.0": "Full", "0.5": "Half", "0.0": "Ignore"}},
        "splits": {k: v[0] for k, v in espn.SPLITS.items()},
        "cats": [{"key": c, "label": E.LABELS[c]} for c in E.CATS],
    }


@app.get("/api/rankings")
def rankings(year: int = 0, split: str = "season", system: str = E.DEFAULT_SYSTEM, punt: str = "",
             teams: int = 12, roster: int = 13, league: str | None = None,
             refresh: bool = False, m1: int | None = None, ref: str | None = None,
             center: str | None = None, transform: int | None = None,
             weights: str | None = None, tov: float | None = None):
    sy = _system(system, ref, center, transform, weights, tov, m1)
    year = year or current_year()
    team_names = None
    cats = E.CATS
    parsed, sched = None, None
    if league:
        lg = STORE.league(league)
        if not lg:
            raise HTTPException(404, "League not loaded; import it again.")
        frames, source = lg["frames"], lg["source"]
        parsed, sched = lg["parsed"], lg["sched"]
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
    if sched is None:
        sched = STORE.schedule(year)
    return {"source": source, "split": used, "available_splits": list(frames),
            "schedule": _schedule_block(parsed, sched),
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
def league_view(key: str, split: str = "season", system: str = E.DEFAULT_SYSTEM, punt: str = "",
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
            system: str = E.DEFAULT_SYSTEM, punt: str = "", teams: int = 12, roster: int = 13,
            league: str | None = None, m1: int | None = None, ref: str | None = None,
            center: str | None = None, transform: int | None = None,
            weights: str | None = None, tov: float | None = None):
    cur = _system(system, ref, center, transform, weights, tov, m1)
    if target not in E.ALL_SYSTEMS:
        raise HTTPException(400, "unknown target")
    tgt = E.ALL_SYSTEMS[target]
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


@app.get("/api/league/{key}/build")
def team_build(key: str, team_id: int, split: str = "season", system: str = E.DEFAULT_SYSTEM,
               build: str | None = None, m1: int | None = None, ref: str | None = None,
               center: str | None = None, transform: int | None = None,
               weights: str | None = None, tov: float | None = None):
    """Build advisor: which categories to build around, who doesn't fit, swap ideas.
    build: comma-separated punts to analyse ('none' for no punts); default = recommended."""
    sy = _system(system, ref, center, transform, weights, tov, m1)
    lg = STORE.league(key)
    if not lg:
        raise HTTPException(404, "League not loaded; import it again.")
    p = lg["parsed"]
    if team_id not in {t["id"] for t in p["teams"]}:
        raise HTTPException(404, "No such team in this league.")
    used, df = _pick_split(lg["frames"], split)
    punts = None if build is None else ([] if build in ("", "none") else
                                        [c for c in build.split(",") if c in p["cats"]])
    res = BUILD.advise(p, df, sy, team_id, punts)
    res.pop("_pool", None); res.pop("_drops", None)
    res["split"] = used
    return _json_safe(res)


# --------------------------------------------------------------------------- #
# Player card
# --------------------------------------------------------------------------- #
WINDOW_ORDER = ["season", "last7", "last15", "last30", "proj", "prev"]


def _per_game(r) -> dict:
    fga, fta = float(r["fga"]), float(r["fta"])
    return {"g": int(r["g"]), "mpg": round(float(r["mpg"]), 1),
            **{c: round(float(r[c]), 1) for c in STAT_COLS},
            "fg": round(float(r["fgm"]) / fga, 3) if fga else None,
            "ft": round(float(r["ftm"]) / fta, 3) if fta else None,
            "fga": round(fga, 1), "fta": round(fta, 1)}


def _two_weeks(p: dict | None, sched: dict) -> tuple[list[tuple[str, list[int]]], int | None, object]:
    """[(label, day ids)] for this matchup week and next, plus today's day id and the
    calendar anchor. With a league: its matchup weeks. Without: Monday-Sunday weeks."""
    from datetime import datetime
    from . import weeks as W
    anchor = (p or {}).get("anchor") or W.anchor_from_schedule(sched)
    if p:
        cur = p["current_period"]
        out = [(lbl, p["matchup_periods"].get(per)) for lbl, per in (("This week", cur), ("Next week", cur + 1))]
        return [(l, d) for l, d in out if d], p.get("current_day"), anchor
    if not anchor:
        return [], None, None
    today = anchor[0] + (datetime.now(W.ET).date() - anchor[1]).days
    start = today - datetime.now(W.ET).weekday()
    return [("This week", list(range(start, start + 7))),
            ("Next week", list(range(start + 7, start + 14)))], today, anchor


def _schedule_block(p: dict | None, sched: dict) -> dict | None:
    """Days of this week and next, and which of them each NBA team plays."""
    weeks_, today, anchor = _two_weeks(p, sched)
    if not weeks_ or not sched:
        return None
    from . import weeks as W
    out = {"weeks": [], "teams": {}}
    for label, days in weeks_:
        out["weeks"].append({"label": label, "days": [
            {**W.label(d, anchor, i), "today": d == today, "past": today is not None and d < today,
             "nba_games": sum(1 for t in sched.values() if d in t) // 2} for i, d in enumerate(days)]})
    for team, games in sched.items():
        out["teams"][team] = {key: [d in games for d in days]
                              for key, (_, days) in zip(("this", "next"), weeks_)}
    return out


def _week_schedule(team: str, sched: dict, days: list[int], today: int | None, anchor) -> list[dict]:
    from . import weeks as W
    g = sched.get(team) or {}
    return [{**W.label(d, anchor, i), "game": d in g, "past": today is not None and d < today,
             "today": d == today, "nba_games": sum(1 for t in sched.values() if d in t) // 2}
            for i, d in enumerate(days)]


@app.get("/api/player/{pid}")
def player_card(pid: str, year: int = 0, split: str = "season", system: str = E.DEFAULT_SYSTEM,
                punt: str = "", teams: int = 12, roster: int = 13, league: str | None = None,
                team_id: int | None = None, m1: int | None = None, ref: str | None = None,
                center: str | None = None, transform: int | None = None,
                weights: str | None = None, tov: float | None = None):
    from datetime import datetime
    from . import weeks as W
    sy = _system(system, ref, center, transform, weights, tov, m1)
    year = year or current_year()
    p = None
    cats = E.CATS
    if league:
        lg = STORE.league(league)
        if not lg:
            raise HTTPException(404, "League not loaded; import it again.")
        p, frames, sched = lg["parsed"], lg["frames"], lg["sched"]
        cats = p["cats"]
        teams, roster = len(p["teams"]), p["roster_size"]
    else:
        frames, _ = STORE.pool(year)
        sched = STORE.schedule(year)
    used, df = _pick_split(frames, split)

    info = None
    for k in [used] + WINDOW_ORDER:
        f = frames.get(k)
        if f is not None and (f["id"] == pid).any():
            info = f[f["id"] == pid].iloc[0]
            break
    if info is None:
        raise HTTPException(404, "Player not found.")

    use = [c for c in cats if c not in _punts(punt)] or cats
    sc = E.score(df, sy, cats=use, pool_size=teams * roster)
    snap = None
    if (df["id"] == pid).any():
        i = df.index[df["id"] == pid][0]
        rank = int(sc["value"].rank(ascending=False, method="min")[i])
        snap = {"rank": rank, "of": int(len(df)), "value": round(float(sc.at[i, "value"]), 3),
                "dropped": sc.at[i, "dropped"],
                "v": {c: round(float(sc.at[i, f"v_{c}"]), 2) for c in cats}}

    windows = []
    for k in WINDOW_ORDER:
        f = frames.get(k)
        if f is None:
            continue
        m = f[(f["id"] == pid) & (f["g"] > 0)]
        if len(m):
            windows.append({"key": k, "label": espn.SPLITS[k][0], **_per_game(m.iloc[0])})

    owner, build = None, None
    ft = int(info.get("fantasy_team", 0) or 0)
    if p:
        names = {t["id"]: t["name"] for t in p["teams"]}
        owner = names.get(ft) if ft > 0 else ("Rostered" if ft < 0 else
                                              "Waivers" if info.get("status") == "WAIVERS" else "Free agent")
        if team_id and snap:
            res = BUILD.advise(p, df, sy, team_id)
            pv = res["_pool"]
            if pid in pv.index:
                b = res["build"]
                build = {"punts": b["punts"], "build_rank": int(pv.at[pid, "build_rank"]),
                         "std_rank": int(pv.at[pid, "rank"]), "team": res["team"]["name"]}

    # this week and next
    weeks_, today, anchor = _two_weeks(p, sched)
    sched_out = [{"label": lbl, "days": _week_schedule(info["team"], sched, days, today, anchor)}
                 for lbl, days in weeks_]

    return _json_safe({
        "id": pid, "name": info["name"], "team": info["team"], "pos": info.get("pos", ""),
        "injury": info.get("injury", ""), "status": info.get("status", ""),
        "owned": float(info.get("owned", 0) or 0), "owner": owner,
        "split": used, "cats": cats, "snapshot": snap, "windows": windows,
        "build": build, "schedule": sched_out,
        "espn_extras": not (lg["source"].startswith("Demo") if league else frames.keys() == {"prev"}),
    })


@app.get("/api/player/{pid}/espn")
def player_espn(pid: str):
    """Game log, career averages and news from ESPN's public APIs (best effort)."""
    from . import playerinfo as PI
    if not pid.isdigit():
        raise HTTPException(400, "bad player id")
    return _json_safe({"gamelog": PI.game_log(pid), "career": PI.career(pid), "news": PI.news(pid)})


class StreamBody(BaseModel):
    team_id: int
    period: int = 0
    droppable: list[str] | None = None
    adds_left: int | None = None
    mode: str = "auto"
    split: str = "season"
    system: str = E.DEFAULT_SYSTEM
    punt: str = ""
    m1: int | None = None
    ref: str | None = None
    center: str | None = None
    transform: int | None = None
    weights: str | None = None
    tov: float | None = None


@app.post("/api/league/{key}/stream")
def stream(key: str, body: StreamBody):
    sy = _system(body.system, body.ref, body.center, body.transform, body.weights, body.tov, body.m1)
    lg, p, used, pool, punts, _ = _league_ctx(key, body.split, sy, body.punt)
    if body.mode not in ("auto", "today", "tomorrow"):
        raise HTTPException(400, "mode must be auto, today or tomorrow")
    if not lg["sched"]:
        raise HTTPException(503, "The NBA schedule isn't available, so games can't be counted.")
    try:
        res = ST.plan(p, pool, lg["sched"], body.team_id, body.period or p["current_period"],
                      droppable=body.droppable, adds_left=body.adds_left, mode=body.mode)
    except ValueError as e:
        raise HTTPException(400, str(e))
    res["split"] = used
    res["periods"] = [x for x in sorted(p["matchup_periods"]) if x >= p["current_period"]][:3]
    return _json_safe(res)


class TradeBody(BaseModel):
    team_a: int
    team_b: int = 0
    a_gives: list[str] = []
    b_gives: list[str] = []
    a_drops: list[str] = []
    b_drops: list[str] = []
    split: str = "season"
    system: str = E.DEFAULT_SYSTEM
    punt: str = ""
    m1: int | None = None
    ref: str | None = None
    center: str | None = None
    transform: int | None = None
    weights: str | None = None
    tov: float | None = None
    fill: bool = True


@app.post("/api/league/{key}/trade")
def trade(key: str, body: TradeBody):
    lg, p, used, pool, punts, _ = _league_ctx(key, body.split, _system(body.system, body.ref, body.center, body.transform, body.weights, body.tov, body.m1), body.punt)
    if not body.a_gives and not body.b_gives:
        raise HTTPException(400, "Pick at least one player to move.")
    rep = L.trade_report(p, pool, p["cats"], body.team_a, body.team_b, body.a_gives,
                         body.b_gives, body.a_drops, body.b_drops, fill=body.fill)
    rep["cats"] = p["cats"]
    rep["punts"] = punts
    return rep


# --------------------------------------------------------------------------- #
if os.path.isdir(FRONTEND):
    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

    def _asset_version() -> str:
        """Changes whenever app.js / style.css change, so browsers fetch the new files."""
        m = max(os.path.getmtime(os.path.join(FRONTEND, f)) for f in ("app.js", "style.css"))
        return str(int(m))

    @app.get("/")
    def index():
        from fastapi.responses import HTMLResponse
        html = open(os.path.join(FRONTEND, "index.html"), encoding="utf-8").read()
        v = _asset_version()
        html = html.replace("/static/app.js", f"/static/app.js?v={v}") \
                   .replace("/static/style.css", f"/static/style.css?v={v}")
        return HTMLResponse(html, headers={"Cache-Control": "no-cache"})
