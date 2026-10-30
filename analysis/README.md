# Ranking study

Both scripts replay 2025-26: 12-team, 13-round snake drafts. 11 opponents draft off standard Z with ADP noise; one test team drafts greedily by the settings under test. Every week is replayed from real box scores, 9-cat H2H, all-play.

    python simulate_pools.py 1000        # perfect info: values from the full season
    python simulate_pools.py 1000 oos    # real-world: values from Oct-Dec, play Jan-Apr
    python simulate_weights.py 1000 [oos]

- `simulate_pools.py`: the reference pool (rostered / +waivers / whole NBA) with and without the transform, plus DURANT variants.
- `simulate_weights.py`: turnover weight, category weights, and Minus 1 with pool-average vs waiver-level zero.
- `estimate_noise.py` and `estimate_dispersion.py` produce the constants in `backend/app/engine.py`.

Known weakness: the test drafter takes the highest-ranked player, with no team-fit logic. That handicaps Minus 1 and punt builds.
