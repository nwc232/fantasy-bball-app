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
    # TO is already ignored by DURANT H2H, so "punt TO" never appears as its own build
    assert not any(b["punts"] == ["tov"] for b in r["builds"])


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
