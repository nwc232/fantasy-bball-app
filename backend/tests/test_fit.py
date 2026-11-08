"""'Fits my team' ranking."""
import numpy as np
from fastapi.testclient import TestClient

from app import engine as E
from app import fit as F
from app import league as L
from app.main import app
from app.store import STORE

c = TestClient(app)


def _ctx():
    key = STORE.demo_league()
    lg = STORE.leagues[key]
    p = lg["parsed"]
    pool = L.value_pool(lg["frames"]["season"], E.SYSTEMS["durant_h2h"], p["cats"], [], 156)
    return p, pool


def test_vectorised_swap_matches_direct_evaluation():
    p, pool = _ctx()
    r = F.team_fit(p, pool, 1)
    pv = pool.drop_duplicates("id").set_index("id")
    pid, f = max(((k, v) for k, v in r["players"].items() if v["kind"] == "add"), key=lambda kv: kv[1]["fit"])
    drop_id = next(i for i in pv.index if pv.at[i, "name"] == f["swap"])
    me = next(t for t in p["teams"] if t["id"] == 1)
    swapped = {**me, "roster": [x for x in me["roster"] if x["id"] != drop_id] + [{"id": pid, "slot": 12}]}
    others = [t for t in p["teams"] if t["id"] != 1]
    om, ov = [], []
    for t in others:
        rows = L.roster_rows(t, pool)
        m, v = L.project(rows, L.games_in_period(rows, None, None, p["starters"]), p["cats"])
        om.append(m); ov.append(v)
    obj = "win" if "MOST" in p["scoring_type"] else "cats"
    before = L._team_odds(L.roster_rows(me, pool), p["starters"], p["cats"], np.array(om), np.array(ov), obj)
    after = L._team_odds(L.roster_rows(swapped, pool), p["starters"], p["cats"], np.array(om), np.array(ov), obj)
    unit = 100 if obj == "win" else 1
    assert abs((after - before) * unit - f["fit"]) < 0.02
    assert abs(before * unit - r["base"]) < 0.02


def test_kinds_and_endpoint():
    p, pool = _ctx()
    r = F.team_fit(p, pool, 1)
    mine = {x["id"] for x in next(t for t in p["teams"] if t["id"] == 1)["roster"]}
    assert all(v["kind"] == "keep" for k, v in r["players"].items() if k in mine)
    assert any(v["kind"] == "add" and v["fit"] > 0 for v in r["players"].values())
    key = c.post("/api/league/demo").json()["key"]
    j = c.get(f"/api/league/{key}/fit?team_id=2").json()
    assert j["team_id"] == 2 and len(j["players"]) > 300
    assert c.get(f"/api/league/{key}/fit?team_id=999").status_code == 404
