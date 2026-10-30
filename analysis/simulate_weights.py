"""
Does DURANT draft better H2H teams?  Simulation on 2025-26 actual game logs.

Each trial: 12-team, 13-round snake draft. 11 opponents draft off standard
9-cat Z ranks with ADP-style noise. One test team (random slot) drafts greedily
by the system under test. Then every regular-season week is played from real
box scores, all-play against the other 11 teams, 9-cat H2H.
Same random seeds for every system (paired comparison).

Values are in-sample (full-season per-game averages): this tests the
valuation formula, not projection skill. Players need 30+ games to be draftable.
"""
import sys
from common import *

N_TRIALS = int(sys.argv[1]) if len(sys.argv) > 1 else 400
OOS = len(sys.argv) > 2 and sys.argv[2] == "oos"   # value on Oct-Dec, play Jan-Apr
TEAMS, ROUNDS = 12, 13
STATS = ["pts", "fg3m", "reb", "ast", "stl", "blk", "tov", "fgm", "fga", "ftm", "fta"]

s = season()
g = logs()
name_to_idx = {n: i for i, n in enumerate(s["name"])}
g["pi"] = g["name"].map(name_to_idx)
missing = g["pi"].isna().mean()
g = g.dropna(subset=["pi"])
g["pi"] = g["pi"].astype(int)
start = g["date"].min() - pd.to_timedelta(g["date"].min().weekday(), unit="D")
g["wk"] = ((g["date"] - start).dt.days // 7).astype(int)
weeks = sorted(g["wk"].unique())
weeks = [w for w in weeks if g[g.wk == w]["date"].nunique() >= 4]  # drop all-star stub weeks
W = np.zeros((len(s), max(weeks) + 1, len(STATS)))
np.add.at(W, (g["pi"].values, g["wk"].values), g[STATS].values)
W = W[:, weeks, :]
if OOS:
    cut = pd.Timestamp("2026-01-01")
    first = g[g.date < cut]
    agg = first.groupby("pi")[STATS].sum()
    gp = first.groupby("pi").size()
    mins = first.groupby("pi")["MIN"].sum()
    s = s.copy()
    s["g"] = gp.reindex(s.index).fillna(0).values
    for c in STATS:
        s[c] = (agg[c].reindex(s.index) / gp.reindex(s.index)).fillna(0).values
    s["mpg"] = (mins.reindex(s.index) / gp.reindex(s.index)).fillna(0).values
    keep_w = [i for i, w in enumerate(weeks) if start + pd.Timedelta(weeks=int(w)) >= cut]
    W = W[:, keep_w, :]
    s = s[s.g > 0]
    W = W[s.index.values]
    s = s.reset_index(drop=True)
print(f"logs matched: {1-missing:.1%}, weeks played: {W.shape[1]}, oos={OOS}")

eligible = np.where(s["g"].values >= (15 if OOS else 30))[0]

M = E.make_system
SYS = {
    "Z, rostered (standard)": (M("z"), None),
    "TZ, rostered": (M("z", transform=True), None),
    "TZ, rostered, TO 0.5": (M("z", transform=True, tov=0.5), None),
    "TZ, rostered, TO 0": (M("z", transform=True, tov=0.0), None),
    "TZ, rostered, G weights": (M("z", transform=True, weights="variance"), None),
    "TZ, rostered, G weights, TO 0.5": (M("z", transform=True, weights="variance", tov=0.5), None),
    "TZ, rostered, DURANT H2H wts, TO 0": (M("z", transform=True, weights="durant_h2h", tov=0.0), None),
    "TZ, rostered, TO 0.5, M1 vs pool avg": (M("z", transform=True, tov=0.5, minus_one=True), None),
    "TZ, rostered, TO 0.5, M1 vs waiver level": (M("z", transform=True, tov=0.5, minus_one=True, center="replacement"), None),
    "TZ, rostered, H2H wts, TO 0, M1 vs waiver level": (M("z", transform=True, weights="durant_h2h", tov=0.0, minus_one=True, center="replacement"), None),
}
values = {}
for name, (sy, cats) in SYS.items():
    values[name] = E.score(s, sy, cats=cats)["value"].values
z_rank = pd.Series(values["Z, rostered (standard)"]).rank(ascending=False).values


def draft(test_vals, slot, rng):
    avail = np.zeros(len(s), bool); avail[eligible] = True
    # opponents: ADP-ish noise on Z rank, one draw per opponent
    opp_key = z_rank[None, :] * np.exp(rng.normal(0, 0.25, (TEAMS, len(s))))
    rosters = [[] for _ in range(TEAMS)]
    for r in range(ROUNDS):
        order = range(TEAMS) if r % 2 == 0 else reversed(range(TEAMS))
        for t in order:
            cand = np.where(avail)[0]
            if t == slot:
                p = cand[np.argmax(test_vals[cand])]
            else:
                p = cand[np.argmin(opp_key[t, cand])]
            rosters[t].append(p); avail[p] = False
    return rosters


PLAY_LABELS = ["PTS", "3PM", "REB", "AST", "STL", "BLK", "TO", "FG%", "FT%"]


def play(rosters, slot):
    T = np.stack([W[r].sum(axis=0) for r in rosters])          # team x week x stat
    cat = np.stack([T[..., 0], T[..., 1], T[..., 2], T[..., 3], T[..., 4], T[..., 5],
                    -T[..., 6], T[..., 7] / np.maximum(T[..., 8], 1),
                    T[..., 9] / np.maximum(T[..., 10], 1)], axis=-1)   # team x week x 9
    me, opp = cat[slot][None], np.delete(cat, slot, axis=0)
    res = np.where(me > opp, 1.0, np.where(me < opp, 0.0, 0.5))          # opp x week x 9
    wins, losses = res.sum(-1), (1 - res).sum(-1)
    match = np.where(wins > losses, 1, np.where(wins < losses, 0, 0.5))
    return res.mean(), match.mean(), res.mean(axis=(0, 1))


rows = []
for name in SYS:
    rng_slots = np.random.default_rng(7)
    out = []
    for trial in range(N_TRIALS):
        rng = np.random.default_rng(1000 + trial)
        slot = rng_slots.integers(TEAMS)
        rosters = draft(values[name], slot, rng)
        out.append(play(rosters, slot))
    cs = np.array([o[0] for o in out]); mw = np.array([o[1] for o in out])
    percat = np.mean([o[2] for o in out], axis=0)
    rows.append({"system": name, "cat_win%": cs.mean() * 100, "matchup_win%": mw.mean() * 100,
                 "se": mw.std() / np.sqrt(N_TRIALS) * 100,
                 **{l: round(v * 100) for l, v in zip(PLAY_LABELS, percat)}})
    print(name, round(mw.mean() * 100, 1), flush=True)

res = pd.DataFrame(rows)
base = res.iloc[0]["matchup_win%"]
res["vs Z"] = res["matchup_win%"] - base
pd.set_option("display.width", 220)
print(res.round(1).to_string(index=False))
res.round(2).to_csv("sim_weights_oos.csv" if OOS else "sim_weights.csv", index=False)
