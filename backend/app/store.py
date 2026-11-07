"""In-memory caches for player pools and imported leagues."""
from __future__ import annotations

import time
from datetime import date

import pandas as pd

from . import demo, espn, weeks

POOL_TTL = 20 * 60
LEAGUE_TTL = 10 * 60


def current_year() -> int:
    t = date.today()
    return t.year + 1 if t.month >= 9 else t.year


def _clean(frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    out = {}
    for k, f in frames.items():
        if f is None or f.empty:
            continue
        f = f.drop_duplicates("id", keep="first").reset_index(drop=True)
        out[k] = f[f["g"] > 0].reset_index(drop=True)
    return out


class Store:
    def __init__(self) -> None:
        self.pools: dict[int, tuple[float, dict, str]] = {}
        self.leagues: dict[str, dict] = {}
        self.pro_sched: dict[int, tuple[float, dict]] = {}

    # ---- player pool ----------------------------------------------------- #
    def pool(self, year: int, force: bool = False) -> tuple[dict, str]:
        hit = self.pools.get(year)
        if hit and not force and time.time() - hit[0] < POOL_TTL:
            return hit[1], hit[2]
        try:
            raw = espn.fetch_player_pool(year)
            frames = _clean(espn.players_to_frames(raw, year))
            if not frames:
                raise espn.ESPNError("ESPN returned no player stats yet.")
            source = f"ESPN, fetched {time.strftime('%H:%M UTC', time.gmtime())}"
        except espn.ESPNError as e:
            frames = _clean(espn.players_to_frames(demo.demo_players(), demo.YEAR))
            frames = {"prev": frames["season"]}
            source = f"Bundled 2025-26 season (ESPN unavailable: {e})"
        self.pools[year] = (time.time(), frames, source)
        return frames, source

    def schedule(self, year: int) -> dict:
        hit = self.pro_sched.get(year)
        if hit and time.time() - hit[0] < 6 * 3600:
            return hit[1]
        try:
            s = espn.parse_pro_schedule(espn.fetch_pro_schedule(year))
        except espn.ESPNError:
            s = {}
        self.pro_sched[year] = (time.time(), s)
        return s

    # ---- leagues --------------------------------------------------------- #
    def import_league(self, league_id: str, year: int, espn_s2: str | None,
                      swid: str | None) -> str:
        raw = espn.fetch_league(league_id, year, espn_s2, swid)
        parsed = espn.parse_league(raw, year)
        try:
            pool_raw = espn.fetch_player_pool(year, league_id, espn_s2, swid)
        except espn.ESPNError:
            pool_raw = []
        try:   # FGA/FTA so far this week, for FG%/FT% (best effort)
            box = espn.fetch_week_box(league_id, year, parsed["current_period"],
                                      parsed["current_day"] or 1, espn_s2, swid)
            parsed["week_box"] = espn.parse_week_box(box, parsed["current_period"])
        except espn.ESPNError:
            parsed["week_box"] = {}
        frames = self._league_frames(parsed, pool_raw, year)
        key = f"{league_id}-{year}"
        sched = self.schedule(year)
        self._map_weeks(parsed, sched)
        self.leagues[key] = {"parsed": parsed, "frames": frames, "sched": sched,
                             "creds": (league_id, year, espn_s2, swid), "ts": time.time(),
                             "source": "ESPN league"}
        return key

    @staticmethod
    def _map_weeks(parsed: dict, sched: dict, anchor=None) -> None:
        anchor = anchor or weeks.anchor_from_schedule(sched)
        last = parsed.get("last_day") or max(
            (max(v) for v in sched.values() if v), default=parsed.get("current_day") or 170)
        mp, how = weeks.build(parsed["matchup_periods_raw"], parsed.get("observed_days") or {},
                              parsed.get("first_day") or 1, last, anchor)
        parsed["matchup_periods"] = mp
        parsed["weeks_source"] = how
        parsed["anchor"] = anchor

    def _league_frames(self, parsed: dict, pool_raw: list, year: int) -> dict:
        if pool_raw:
            base = espn.players_to_frames(pool_raw, year)
        else:
            frames, _ = self.pool(year)
            base = frames
        roster = espn.players_to_frames(parsed["roster_entries"], year)
        owner = {r["id"]: t["id"] for t in parsed["teams"] for r in t["roster"]}
        out = {}
        for k in set(base) | set(roster):
            parts = [f for f in (roster.get(k), base.get(k)) if f is not None and not f.empty]
            if not parts:
                continue
            f = pd.concat(parts, ignore_index=True)
            f["fantasy_team"] = f["id"].map(owner).fillna(0).astype(int)
            if "status" not in f:
                f["status"] = "FREEAGENT"
            f.loc[f["fantasy_team"] != 0, "status"] = "ONTEAM"
            f.loc[(f["fantasy_team"] == 0) & (f["status"] == "ONTEAM"), "status"] = "FREEAGENT"
            out[k] = f
        return _clean(out)

    def demo_league(self) -> str:
        players = demo.demo_players()
        d = demo.demo_league(players)
        parsed = espn.parse_league(d["league"], demo.YEAR)
        parsed["week_box"] = {}
        frames = self._league_frames(parsed, players, demo.YEAR)
        sched = espn.parse_pro_schedule(d["pro_schedule"])
        self._map_weeks(parsed, sched, anchor=d["anchor"])
        self.leagues["demo"] = {"parsed": parsed, "frames": frames,
                                "sched": sched,
                                "creds": None, "ts": time.time(),
                                "source": "Demo league built from the 2025-26 season"}
        return "demo"

    def refresh_league(self, key: str) -> dict:
        lg = self.leagues.get(key)
        if not lg:
            raise KeyError(key)
        if lg["creds"]:
            self.import_league(*lg["creds"])
        else:
            self.demo_league()
        return self.leagues[key]

    def league(self, key: str) -> dict | None:
        lg = self.leagues.get(key)
        if lg and lg["creds"] and time.time() - lg["ts"] > LEAGUE_TTL:
            try:
                self.import_league(*lg["creds"])
                lg = self.leagues[key]
            except espn.ESPNError:
                pass
        return lg


STORE = Store()
