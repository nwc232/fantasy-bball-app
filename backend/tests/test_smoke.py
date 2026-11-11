"""Offline end-to-end test using the demo league (exercises the ESPN parsers)."""
from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)


def test_rankings_all_systems():
    for system in ["tz", "z", "g", "durant", "durant_h2h"]:
        r = c.get(f"/api/rankings?system={system}&punt=ft")
        assert r.status_code == 200, r.text
        assert len(r.json()["players"]) > 300


def test_league_matchups_trade():
    key = c.post("/api/league/demo").json()["key"]
    j = c.get(f"/api/league/{key}?system=tz").json()
    assert len(j["power"]) == 12 and len(j["matchups"]) == 6
    a, b = j["teams"][0], j["teams"][1]
    r = c.post(f"/api/league/{key}/trade", json={
        "team_a": a["id"], "team_b": b["id"],
        "a_gives": [a["players"][1]["id"]], "b_gives": [b["players"][0]["id"]]})
    assert r.status_code == 200, r.text
    assert len(r.json()["sides"]) == 2
    # add/drop against free agents
    fa = j["free_agents"][0]["id"]
    r = c.post(f"/api/league/{key}/trade", json={
        "team_a": a["id"], "team_b": 0, "a_gives": [a["players"][-1]["id"]], "b_gives": [fa]})
    assert r.status_code == 200, r.text


def test_standard_z_matches_basketball_monster():
    """BBM published 25-26 Kevin Durant: pts 1.62, 3pm .72, reb -.18, ast .49, fg .88, ft 1.32, to -1.58."""
    r = c.get("/api/rankings?system=z&split=prev").json()
    kd = next(p for p in r["players"] if p["name"] == "Kevin Durant")
    bbm = {"pts": 1.62, "fg3m": .72, "reb": -.18, "ast": .49, "fg": .88, "ft": 1.32, "tov": -1.58}
    for k, v in bbm.items():
        assert abs(kd["v"][k] - v) < 0.06, (k, kd["v"][k], v)
    assert abs(kd["rank"] - 15) <= 1


def test_minus_one_toggle():
    off = c.get("/api/rankings?system=tz&split=prev&m1=0").json()
    on = c.get("/api/rankings?system=tz&split=prev&m1=1").json()
    assert off["minus_one"] is False and on["minus_one"] is True
    g_off = next(p for p in off["players"] if p["name"] == "Giannis Antetokounmpo")
    g_on = next(p for p in on["players"] if p["name"] == "Giannis Antetokounmpo")
    assert g_on["rank"] < g_off["rank"] and g_on["dropped"] == "FT%" and g_off["dropped"] == ""
    # DURANT defaults to on, and can be forced off
    d = c.get("/api/rankings?system=durant_h2h&split=prev").json()
    d_off = c.get("/api/rankings?system=durant_h2h&split=prev&m1=0").json()
    assert d["minus_one"] is True and d_off["minus_one"] is False


def test_custom_spec_and_presets():
    r = c.get("/api/rankings?system=tz&split=prev&ref=nba&weights=durant_h2h&tov=0&transform=1&m1=1&center=pool").json()
    assert r["system"] == "durant_h2h" or r["spec"]["reference"] == "nba"
    r = c.get("/api/rankings?system=tz&split=prev&ref=waivers&tov=0.5&transform=1&m1=0&weights=equal&center=replacement").json()
    assert r["system"] == "custom"
    assert c.get("/api/rankings?system=tz&ref=bogus").status_code == 400


def test_eligibility_scales_with_season():
    import pandas as pd
    from app import engine as E
    df = pd.DataFrame({"g": [5, 4, 2, 1, 1] * 40, "mpg": [30, 25, 12, 40, 5] * 40})
    e = E.eligible(df)
    assert set(df.loc[e, "g"]) == {5, 4, 2}          # 25% of 5 games -> 2 games minimum
    df2 = pd.DataFrame({"g": [82, 40, 21, 20] * 40, "mpg": [30] * 160})
    assert set(df2.loc[E.eligible(df2), "g"]) == {82, 40, 21}


def test_explain_and_refresh():
    j = c.get("/api/rankings?system=tz&split=prev").json()
    pid = j["players"][40]["id"]
    e = c.get(f"/api/explain?player={pid}&split=prev&system=tz&target=durant_h2h").json()
    assert e["current"]["rank"] == 41 or e["current"]["rank"] <= 41
    assert e["path"][-1]["rank"] == e["target"]["rank"]
    assert {p["key"] for p in e["presets"]} == {"z", "durant_h2h"}
    key = c.post("/api/league/demo").json()["key"]
    assert "updated" in c.post(f"/api/league/{key}/refresh").json()


def test_uneven_trade_is_balanced():
    key = c.post("/api/league/demo").json()["key"]
    j = c.get(f"/api/league/{key}").json()
    a, b = j["teams"][0], j["teams"][1]
    body = {"team_a": a["id"], "team_b": b["id"],
            "a_gives": [a["players"][1]["id"], a["players"][2]["id"]],
            "b_gives": [b["players"][0]["id"]]}
    r = c.post(f"/api/league/{key}/trade", json=body).json()
    sa, sb = r["sides"]
    assert sa["roster_size_after"] == sa["roster_limit"] and len(sa["auto_adds"]) == 1
    assert sb["roster_size_after"] == sb["roster_limit"] and len(sb["auto_drops"]) == 1
    received = {p["id"] for p in sb["gets"]}
    assert sb["auto_drops"][0]["id"] not in received        # never auto-drop who you just got
    off = c.post(f"/api/league/{key}/trade", json={**body, "fill": False}).json()
    assert off["sides"][0]["roster_size_after"] == sa["roster_limit"] - 1


def test_empty_stat_windows_are_not_created():
    """Zero-stat rows for injured rostered players must not invent a window
    (e.g. 'last season' in the demo) that would project everyone at 0."""
    from app.store import STORE
    key = STORE.demo_league()
    frames = STORE.leagues[key]["frames"]
    assert set(frames) == {"season"}
    for f in frames.values():
        assert (f["g"] > 0).sum() > 100
    j = c.get(f"/api/league/{key}?split=prev").json()
    assert j["split"] == "season"
    assert j["power"][0]["cats"]["pts"]["weekly"] > 0


def test_login_session(monkeypatch):
    from app import main as M
    monkeypatch.setattr(M, "APP_PASSWORD", "hoops")
    fresh = TestClient(app)
    assert fresh.get("/api/health").status_code == 200              # health check stays open
    assert fresh.get("/login").status_code == 200
    assert fresh.get("/static/style.css").status_code == 200
    assert fresh.get("/api/meta").status_code == 401                 # API needs a session
    r = fresh.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert fresh.post("/api/login", json={"password": "nope"}).status_code == 401
    r = fresh.post("/api/login", json={"password": "hoops"})
    assert r.status_code == 200 and "cl_session" in r.cookies
    assert "httponly" in r.headers["set-cookie"].lower()
    assert fresh.get("/api/meta").status_code == 200                 # cookie now sent
    assert fresh.get("/api/meta").json()["auth"] is True
    fresh.cookies.set("cl_session", "9999999999.forged")
    assert fresh.get("/api/meta").status_code == 401                 # forged token rejected
    monkeypatch.setattr(M, "APP_PASSWORD", "changed")                # new password logs everyone out
    good = TestClient(app)
    good.cookies.set("cl_session", r.cookies["cl_session"])
    assert good.get("/api/meta").status_code == 401


def test_espn_rostered_player_is_never_listed_as_free_agent():
    """Regression: a player ESPN marks as rostered but missing from the parsed
    league rosters used to be downgraded to FREEAGENT."""
    from app import demo as D
    from app.store import STORE
    key = STORE.demo_league()
    p = STORE.leagues[key]["parsed"]
    players = D.demo_players()
    rostered = {r["id"] for t in p["teams"] for r in t["roster"]}
    a, b = [x for x in players if str(x["id"]) not in rostered][:2]
    a.update(onTeamId=3, status="ONTEAM")          # ESPN knows the team
    b.update(onTeamId=0, status="ONTEAM")          # ESPN says rostered, team unknown
    f = STORE._league_frames(p, players, D.YEAR)["season"].set_index("id")
    assert f.at[str(a["id"]), "fantasy_team"] == 3
    assert f.at[str(b["id"]), "fantasy_team"] == -1
    avail = f[f["fantasy_team"] == 0]
    assert str(a["id"]) not in avail.index and str(b["id"]) not in avail.index
    assert set(avail["status"]) <= {"FREEAGENT", "WAIVERS"}


def test_only_two_systems_offered_and_cat_order():
    m = c.get("/api/meta").json()
    assert [s["key"] for s in m["systems"]] == ["durant_h2h", "z"]
    assert m["default_system"] == "durant_h2h"
    j = c.get("/api/rankings?split=prev").json()
    assert j["cats"] == ["fg", "ft", "fg3m", "pts", "reb", "ast", "stl", "blk", "tov"]
