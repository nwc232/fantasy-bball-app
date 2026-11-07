# Category Lab

Live 9-cat fantasy basketball rankings with punts, plus ESPN league import, H2H matchup odds, power rankings and a trade analyzer.

- **Rankings**: preset systems are DURANT H2H (the default), Category Lab, standard Z, G-score and DURANT. **Model settings** exposes every switch: what the scale is measured against (rostered / rostered + waivers / whole NBA), the zero point (pool average / waiver level), the transform, category weights, turnover weight, and Minus 1. Change any of them and you get a Custom system. Stats can be this season, last 7/15/30 days, ESPN projections or last season. The punt chips drop categories, and "vs Z" shows each player's movement against the standard rank.
- **Why this rank?**: click any player's name. It shows his rank under every system, which setting moves him most between your system and another (e.g. Category Lab vs DURANT H2H), and his category values side by side.
- **Refresh**: the ↻ button re-pulls ESPN stats and your league rosters. The page also refreshes on its own every 10 minutes while it's open, and the server re-pulls a league once its data is over 10 minutes old.
- **League**: import an ESPN league (public, or private with your cookies). Shows each team's projected weekly category totals, category ranks, and all-play win % against every other team.
- **Matchups**: win probability for every matchup in a given week, plus odds per category. Games are counted from the real NBA schedule and capped at your daily starting slots.
- **Streaming**: plans this week's add/drops against your actual opponent. It counts:
  - what has already happened this week, plus every remaining game, skipping games that have tipped off
  - ESPN's position slots day by day, so a player only helps on days he'd actually start
  - injuries
  - your league's weekly add limit

  It works out chains (a Mon–Tue streamer, then a Wed–Sun one in the same spot) and ranks every free agent by how much he'd raise your odds this week. It follows your league's scoring: win chance for most-categories leagues, expected categories for each-category leagues. It suggests drops from your 3 lowest-valued players by default; tap players to change who's droppable. Your opponent is projected from their current roster.
- **Trade analyzer**: pick players from any two teams, or from free agents for add/drops, and mark drops. For both sides it shows how each category's weekly total, win %, and rank change, along with all-play win % and power rank, and how the trade moves every team in the league.

## Run locally
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
# open http://localhost:8000
```
Click **Try the demo league** on the League tab to see every feature with 2025-26 data and no ESPN account.

## Deploy (free)
- **Render**: push this folder to a GitHub repo, then New → Blueprint → pick the repo. `render.yaml` and the `Dockerfile` handle the rest.
- **Fly.io / Railway**: deploy the `Dockerfile` as-is. It listens on `$PORT`.

Live stats come from ESPN's fantasy API, which works from cloud hosts. stats.nba.com blocks most datacenter IPs, so it isn't used. If ESPN can't be reached, the site falls back to the bundled 2025-26 season and says so in the header.

## Importing a private ESPN league
1. Find the League ID in your league URL (`leagueId=…`).
2. On fantasy.espn.com, open DevTools → Application → Cookies and copy `espn_s2` and `SWID`.
3. Paste both into the League tab. The server keeps them in memory only, so you'll need to re-import after a restart. Tick "Remember" to store them in your browser instead.

If you deploy publicly, anyone with the URL can use your server. The cookies are only ever sent by the person importing, but if that worries you, keep the URL to yourself or put the app behind your host's basic auth.

## How it works
- `backend/app/engine.py`: valuation systems. All share one z-score core with switches for reference pool, Yeo-Johnson transform, category weights, Minus 1 and G-score variance.
- `backend/app/espn.py`: ESPN endpoints and parsers. Stat and slot IDs were checked against the `espn_api` package.
- `backend/app/league.py`: weekly projections, Monte Carlo matchup odds, power rankings and trades.
- `backend/app/demo.py`: builds an ESPN-shaped demo league from the bundled season, so the ESPN parsers run in tests.
- `analysis/`: the DURANT study (draft-and-play simulation on 2025-26 game logs) and the scripts that estimated the noise and dispersion constants.

Run `cd backend && python -m pytest tests` to run the offline test suite. One test checks that standard Z reproduces Basketball Monster's published values.

## Known limits
- Weekly projections ignore positional slot rules: any player can fill any start.
- Matchup and trade odds are per-game based. Injured players count at full value unless they're in an IR slot or you drop them in the trade analyzer.
- Categories outside the standard 9 (DD, A/TO, 3P%, OREB…) are listed on the League tab but not modelled.
- Early in the season, "This season" is a tiny sample. Switch Stats to **ESPN projections** or **Last season** until about 15 games in.
