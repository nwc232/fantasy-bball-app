# Category Lab

Live 9-cat fantasy basketball rankings with punts, plus ESPN league import, H2H matchup odds, power rankings and a trade analyzer.

- **Rankings**: preset systems are DURANT H2H (the default), Category Lab, standard Z, G-score and DURANT. **Model settings** exposes every switch: what the scale is measured against (rostered / rostered + waivers / whole NBA), the zero point (pool average / waiver level), the transform, category weights, turnover weight, and Minus 1. Change any of them and you get a Custom system. Stats can be this season, last 7/15/30 days, ESPN projections or last season. The punt chips drop categories, and "vs Z" shows each player's movement against the standard rank.
- **Fit for my team**: with a league loaded, switch Rankings to "Fit for my team". For anyone not on your team, it shows how much he'd change your weekly odds against your league if he took the spot of the player listed. For your own players, it shows how much better they are than the best free agent who could replace them; negative means that free agent fits better. It's scored the way your league scores, so a punt build is handled automatically. Filter to "Free agents" for the best pickups for your team.
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
- **Trade analyzer**: pick players from any two teams, or from free agents for add/drops. Uneven trades are balanced automatically: a team that ends up over the roster limit drops its lowest-valued player (never one it just received), and a team with an open spot picks up the free agent (waivers included) who most improves its odds. The same is applied to the "before" rosters, so a team that already had an open spot doesn't make the trade look better than it is. Your own ✕ drops override the automatic ones, and the checkbox turns balancing off.

## Run locally
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
# open http://localhost:8000
```
Click **Try the demo league** on the League tab to see every feature with 2025-26 data and no ESPN account.

## Deploy (free, on Render)
1. Sign in at render.com with GitHub.
2. Click **New → Blueprint** and pick this repo. Render reads `render.yaml` and asks for **APP_PASSWORD**. Set one: the site shows a login page, and you stay logged in for 30 days on each device. Changing the password logs everyone out.
3. Click **Apply**. The first build takes a few minutes, and then you get a URL like `https://category-lab.onrender.com`.
4. Every push to `main` redeploys automatically.

Free-tier notes:
- The service sleeps after about 15 minutes idle, so the first visit after that takes 30-60 seconds to wake up.
- Imported leagues are kept in memory, so they're lost when it sleeps or redeploys. Tick **Remember on this device** when importing and the page re-imports by itself.
- Render's $7/month Starter plan doesn't sleep.

Any Docker host works too (Fly.io, Railway, etc.): deploy the `Dockerfile` and set `PORT` and `APP_PASSWORD`. Without `APP_PASSWORD` the site is open to anyone with the URL, which is fine locally.

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
