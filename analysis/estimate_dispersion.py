"""Per-game variance/mean ratios (counting stats) and overdispersion of
shooting % vs binomial, for top-156 players. Used for matchup win probabilities."""
from common import *
s = season(); g = logs()
pool = E.score(s, "z")["value"].nlargest(156).index
gp = g[g.name.isin(set(s.loc[pool, "name"]))]
out = {}
for c in ["pts", "fg3m", "reb", "ast", "stl", "blk", "tov"]:
    st = gp.groupby("name")[c].agg(["mean", "var"])
    out[c] = round((st["var"].sum() / st["mean"].sum()), 2)
# shooting: weekly-level check of binomial overdispersion
start = g.date.min() - pd.to_timedelta(g.date.min().weekday(), unit="D")
gp = gp.assign(wk=((gp.date - start).dt.days // 7))
wk = gp.groupby(["name", "wk"])[["fgm", "fga", "ftm", "fta"]].sum()
for m, a, k in [("fgm", "fga", "fg"), ("ftm", "fta", "ft")]:
    w = wk[wk[a] >= 5].copy()
    p = (w.groupby("name")[m].sum() / w.groupby("name")[a].sum()).reindex(w.index.get_level_values(0)).values
    resid = (w[m] - p * w[a]) ** 2
    binom = p * (1 - p) * w[a]
    out[k] = round(resid.sum() / binom.sum(), 2)
print(out)
