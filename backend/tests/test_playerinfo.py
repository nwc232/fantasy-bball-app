"""ESPN player extras: parsers are defensive and never raise."""
from fastapi.testclient import TestClient

from app import playerinfo as PI
from app.main import app

GAMELOG = {
    "labels": ["MIN", "FG", "FG%", "3PT", "3P%", "FT", "FT%", "REB", "AST", "BLK", "STL", "PF", "TO", "PTS"],
    "events": {
        "401": {"gameDate": "2026-11-08T00:30Z", "atVs": "vs", "gameResult": "W", "score": "118-110",
                "opponent": {"abbreviation": "BOS"}},
        "402": {"gameDate": "2026-11-10T00:00Z", "atVs": "@", "gameResult": "L", "score": "101-99",
                "opponent": {"abbreviation": "NYK"}},
    },
    "seasonTypes": [
        {"displayName": "2026-27 Regular Season", "categories": [{"events": [
            {"eventId": "401", "stats": ["34", "10-18", "55.6", "2-5", "40.0", "6-7", "85.7", "9", "7", "1", "2", "3", "4", "28"]},
            {"eventId": "402", "stats": ["36", "8-20", "40.0", "1-6", "16.7", "4-4", "100", "11", "5", "0", "1", "2", "3", "21"]},
        ]}]},
        {"displayName": "2026-27 Preseason", "categories": [{"events": [{"eventId": "300", "stats": []}]}]},
    ],
}
STATS = {"categories": [{"name": "averages", "labels": ["GP", "MIN", "PTS", "REB", "AST"],
                         "statistics": [{"season": {"year": 2026, "displayName": "2025-26"}, "teamSlug": "denver-nuggets",
                                         "stats": ["65", "34.8", "27.7", "12.9", "10.7"]},
                                        {"season": {"year": 2027, "displayName": "2026-27"}, "teamSlug": "denver-nuggets",
                                         "stats": ["9", "35.1", "29.0", "13.0", "11.2"]}],
                         "totals": ["900", "33.0", "25.0", "11.5", "8.0"]}]}
NEWS = {"feed": [{"headline": "Jokic posts triple-double", "story": "<p>Nikola Jokic had <b>28</b> points...</p>",
                  "published": "2026-11-09T05:00:00Z", "links": {"web": {"href": "https://espn.com/x"}}}]}


def _fake(monkeypatch, routes):
    def get(url, params=None):
        for frag, data in routes.items():
            if frag in url:
                if isinstance(data, Exception):
                    raise data
                return data
        raise RuntimeError("unexpected url " + url)
    monkeypatch.setattr(PI, "_get", get)


def test_parsers(monkeypatch):
    _fake(monkeypatch, {"/gamelog": GAMELOG, "/stats": STATS, "news/players": NEWS})
    g = PI.game_log("3112335")
    assert [x["id"] for x in g["games"]] == ["402", "401"]          # newest first, preseason skipped
    assert g["games"][0]["opp"] == "NYK" and g["games"][0]["stats"]["PTS"] == "21"
    c = PI.career("3112335")
    assert [s["season"] for s in c["seasons"]] == ["2025-26", "2026-27"] and c["career"]["PTS"] == "25.0"
    n = PI.news("3112335")
    assert n["items"][0]["text"].startswith("Nikola Jokic had 28 points")
    assert n["items"][0]["link"] == "https://espn.com/x"


def test_failures_are_contained(monkeypatch):
    _fake(monkeypatch, {"/gamelog": ValueError("bad json"), "/stats": {"weird": 1},
                        "news/players": RuntimeError("down"), "nba/news": {"articles": []}})
    assert "error" in PI.game_log("1") and "error" in PI.career("1") and "error" in PI.news("1")
    c = TestClient(app)
    r = c.get("/api/player/1/espn")
    assert r.status_code == 200 and set(r.json()) == {"gamelog", "career", "news"}
    assert c.get("/api/player/abc/espn").status_code == 400


def test_player_card_and_pickups_endpoints():
    c = TestClient(app)
    key = c.post("/api/league/demo").json()["key"]
    j = c.get(f"/api/league/{key}").json()
    pid = j["teams"][0]["players"][0]["id"]
    card = c.get(f"/api/player/{pid}?league={key}&team_id=1").json()
    assert card["owner"] == j["teams"][0]["name"] and card["windows"] and card["snapshot"]["rank"] >= 1
    assert len(card["schedule"]) == 2 and len(card["schedule"][0]["days"]) == 7
    pk = c.get(f"/api/league/{key}/pickups?team_id=2").json()
    assert pk["players"] and all(p["status"] in ("FREEAGENT", "WAIVERS") for p in pk["players"])
    ranks = [p["build_rank"] for p in pk["players"]]
    assert ranks == sorted(ranks)
