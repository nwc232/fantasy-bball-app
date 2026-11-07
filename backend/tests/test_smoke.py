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
    assert {p["key"] for p in e["presets"]} == {"tz", "z", "g", "durant", "durant_h2h"}
    key = c.post("/api/league/demo").json()["key"]
    assert "updated" in c.post(f"/api/league/{key}/refresh").json()
