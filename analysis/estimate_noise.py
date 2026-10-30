from common import *
s = season(); g = logs()
z = E.score(s, "z")
pool = z["value"].nlargest(156).index
names = set(s.loc[pool, "name"])
gp = g[g.name.isin(names)].copy()
ref = s.loc[pool]
fg_lg = ref.fgm.sum()/ref.fga.sum(); ft_lg = ref.ftm.sum()/ref.fta.sum()
gp["fg"] = gp.fgm - fg_lg*gp.fga; gp["ft"] = gp.ftm - ft_lg*gp.fta
gp["tov"] = -gp.tov
x = E.category_inputs(s, pool).loc[pool]
out = {}
for c in E.CATS:
    sigma2 = x[c].var(ddof=0)
    tau2 = gp.groupby("name")[c].var().mean()
    out[c] = round(tau2/sigma2, 2)
print(out)
