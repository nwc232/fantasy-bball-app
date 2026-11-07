"""Streaming planner rules, on the demo league (mid-week, day 3 of 7)."""
from fastapi.testclient import TestClient

from app import engine as E
from app import league as L
from app import stream as S
from app.main import app
from app.store import STORE

c = TestClient(app)


def _ctx():
    key = STORE.demo_league()
    lg = STORE.leagues[key]
    p = lg["parsed"]
    pool = L.value_pool(lg["frames"]["season"], E.SYSTEMS["durant_h2h"], p["cats"], [], 156)
    return p, pool, lg["sched"]


def test_plan_improves_and_respects_add_limit():
    p, pool, sched = _ctx()
    r = S.plan(p, pool, sched, 1, p["current_period"])
    assert r["adds_left"] == 3                       # demo limit 4, 1 used
    assert len(r["moves"]) <= 3
    assert r["after"]["exp_cats"] >= r["before"]["exp_cats"]
    for m in r["moves"]:
        assert m["gain"] > 0


def test_every_move_is_legal_and_roster_size_constant():
    p, pool, sched = _ctx()
    r = S.plan(p, pool, sched, 1, p["current_period"], droppable=None, adds_left=4)
    names = [x["name"] for x in r["grid_before"]["rows"]]
    after = r["grid_after"]["rows"]
    # on every remaining day the roster size is unchanged
    for i, day in enumerate(r["week_days"]):
        if r["today_index"] is not None and i < r["today_index"]:
            continue
        on = sum(1 for row in after if row["cells"][i] != "off")
        assert on == len(names)
    # nobody is dropped twice, nobody added twice
    drops = [m["drop"]["id"] for m in r["moves"]]
    adds = [m["add"]["id"] for m in r["moves"]]
    assert len(set(adds)) == len(adds)
    assert len(set(drops)) == len(drops)


def test_chain_reuses_one_roster_spot():
    p, pool, sched = _ctx()
    lowest = S.plan(p, pool, sched, 1, p["current_period"], adds_left=0)["droppable"][0]
    r = S.plan(p, pool, sched, 1, p["current_period"], droppable=[lowest], adds_left=3)
    adds = {m["add"]["id"] for m in r["moves"]}
    assert r["moves"][0]["drop"]["id"] == lowest
    for m in r["moves"][1:]:
        assert m["drop"]["id"] in adds                # later moves drop an earlier streamer


def test_no_droppables_means_no_moves_and_waivers_excluded():
    p, pool, sched = _ctx()
    r = S.plan(p, pool, sched, 1, p["current_period"], droppable=[], adds_left=3)
    assert r["moves"] == []
    r = S.plan(p, pool, sched, 1, p["current_period"])
    ids = {b["id"] for b in r["board"]}
    st = pool.set_index("id")
    assert all(st.at[i, "status"] == "FREEAGENT" and st.at[i, "inj_status"] != "OUT" for i in ids)


def test_future_week_and_modes():
    p, pool, sched = _ctx()
    nxt = S.plan(p, pool, sched, 1, p["current_period"] + 1)
    assert nxt["adds_left"] == 4 and not nxt["is_current"]
    auto = S.plan(p, pool, sched, 1, p["current_period"], adds_left=0)
    tom = S.plan(p, pool, sched, 1, p["current_period"], adds_left=0, mode="tomorrow")
    assert tom["before"]["starts"] <= auto["before"]["starts"]


def test_lineup_respects_positions():
    p, pool, sched = _ctx()
    pool = pool.drop_duplicates("id").set_index("id", drop=False).assign(avail=1.0)
    centers = [i for i, s in pool["slots"].items() if set(s) == {4, 9, 10, 11}][:6]
    ctx = S.Ctx(pool=pool, sched=sched, days=[1], today=None, mode="today",
                slot_list=[0, 1, 2, 3, 4, 5, 6, 11, 11, 11], cats=E.CATS, objective="cats")
    # six pure centers: only C + 3 UT can hold them
    assert len(ctx.starters(tuple(centers))) == 4


def test_stream_endpoint():
    key = c.post("/api/league/demo").json()["key"]
    r = c.post(f"/api/league/{key}/stream", json={"team_id": 1})
    assert r.status_code == 200
    j = r.json()
    assert j["opponent"]["id"] != 1 and j["board"]
