"""Build advisor."""
from fastapi.testclient import TestClient

from app import build as B
from app import engine as E
from app.main import app
from app.store import STORE

c = TestClient(app)


def _ctx():
    key = STORE.demo_league()
    lg = STORE.leagues[key]
    return lg["parsed"], lg["frames"]["season"]


def test_builds_cover_punt_sets_and_prefer_weak_categories():
    p, df = _ctx()
    r = B.advise(p, df, E.SYSTEMS["durant_h2h"], 5)          # Stat Stuffers: weak REB/BLK
    assert r["need"] == 5 and all(len(b["punts"]) <= 3 for b in r["builds"])
    win = {x["cat"]: x["win_pct"] for x in r["profile"]}
    top = r["builds"][0]
    # the recommended punts are categories this team is losing, not ones it wins
    assert all(win[c] < 50 for c in top["punts"])
    assert len(r["builds"]) == B.MAX_BUILDS and r["builds"][0]["place"] == 1


def test_turnovers_count_in_builds_even_under_durant():
    """DURANT rankings ignore TO, but a build should only ignore it when you punt it."""
    p, df = _ctx()
    sy = E.SYSTEMS["durant_h2h"]
    keep = B.advise(p, df, sy, 5, [])
    punt = B.advise(p, df, sy, 5, ["tov"])
    assert keep["tov_note"] and "tov" in keep["build"]["targets"]
    assert punt["build"]["punts"] == ["tov"] and "tov" not in punt["build"]["targets"]
    # build ranks differ once TO is in or out (high-turnover players move)
    a = {m["id"]: m["build_rank"] for m in keep["players"] if m["build_rank"]}
    b = {m["id"]: m["build_rank"] for m in punt["players"] if m["build_rank"]}
    assert a != b


def test_misfits_and_swap_targets_are_priced_similarly_but_fit_better():
    p, df = _ctx()
    r = B.advise(p, df, E.SYSTEMS["durant_h2h"], 5)          # Stat Stuffers
    mis = [m for m in r["players"] if m["label"] == "doesn't fit"]
    assert mis, "expected at least one misfit for this team"
    for m in mis:
        assert m["build_rank"] > m["std_rank"]
        for t in r["targets"][m["id"]]:
            assert t["build_rank"] < m["build_rank"]
            assert int(m["std_rank"] * 0.7) - 8 <= t["std_rank"] <= int(m["std_rank"] * 1.3) + 8


def test_choosing_a_build_and_endpoint():
    key = c.post("/api/league/demo").json()["key"]
    j = c.get(f"/api/league/{key}/build?team_id=2&build=reb,blk").json()
    assert sorted(j["build"]["punts"]) == ["blk", "reb"]
    j = c.get(f"/api/league/{key}/build?team_id=2&build=none").json()
    assert j["build"]["punts"] == []
    assert c.get(f"/api/league/{key}/build?team_id=999").status_code == 404


def test_custom_build_beyond_search_and_too_many_punts():
    key = c.post("/api/league/demo").json()["key"]
    j = c.get(f"/api/league/{key}/build?team_id=2&build=reb,blk,ast,tov").json()   # 4 punts: still 5 to win
    assert len(j["build"]["punts"]) == 4 and j["build"]["place"] is None and j["build"]["team_rank"] >= 1
    r = c.get(f"/api/league/{key}/build?team_id=2&build=reb,blk,ast,tov,stl")
    assert r.status_code == 400
