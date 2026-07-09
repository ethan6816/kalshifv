# Kalshi Fair Value Engine — NFL/NBA Win Probability

A live "fair value" engine for Kalshi game-winner markets. It computes a model-based
win probability for an NFL or NBA game at any point in time and compares it against
Kalshi's live market price to flag mispricings.

Three components, in increasing sophistication:

1. **Elo ratings** — pre-game win probability from team strength.
2. **Stern's Brownian-motion model** — in-game win probability from current score
   margin and time remaining (this is the "stochastic modeling" core of the project).
3. **Calibration + Kelly sizing** — proves the model is honest, and turns edge into
   a bet size.

See `docs/math.tex` for the full derivation and reasoning behind each piece.

---

## ⭐ The main program: `scan.py`

This is the whole point. One command scans every open Kalshi game market,
computes our own live win probability, compares it to Kalshi's price, and prints
a ranked list of **which contracts to bet** (best edge first) with a Kelly stake:

```bash
# see it work offline first (sample games, no network):
python src/scan.py --demo --league wnba

# real: scan a live league. Kalshi market data needs no API key.
python src/scan.py --league wnba --out output/recommendations.csv
python src/scan.py --sigma output/sigma_real.json --out output/recommendations.csv   # NFL w/ fitted sigma
```

**Does it work? Run the self-test** — one command, no API key, checks that the
live ESPN + Kalshi data path is reachable and shows what's live right now:

```bash
python src/scan.py --selftest --league all
```

Example output:
```
  wnba    ESPN:  6 games (2 live)   Kalshi[KXWNBAGAME]:  8 open markets
  nfl     ESPN:  0 games (0 live)   Kalshi[KXNFLGAME]:   0 open markets   (off-season)
```
A real bet recommendation only appears when a league has **live games AND open
markets at the same time**. `--selftest` is how you confirm the plumbing before
trusting a live scan.

Scan every in-season league at once:
```bash
python src/scan.py --league all --out output/recommendations.csv
```

Real-time WNBA (auto-refreshes; leave it running during a game):
```bash
python src/scan.py --league wnba --watch --interval 30
```
Each cycle re-pulls the live score + Kalshi price and reprints the bet list. It
only shows a recommendation when a game is live AND the market's open, so during
a game you'll watch edges appear and disappear as the score and price move.

Supported leagues (`--league`): `nfl`, `nba`, `wnba`, `ncaamb` (men's college
basketball), `ncaaf` (college football), or `all`. Each has a Kalshi series ticker and an
ESPN feed wired in. `--sigma` is optional — omit it and the scanner uses a rough
per-sport default from `config.yaml` so you can run immediately, but those
defaults are guesses: **refit σ on that sport's real data before betting money.**

Two sport-specific notes:
- **In season now (July):** only `wnba` has live games. `nfl`/`ncaaf` start in
  fall, `nba`/`ncaamb` in late fall. Off-season leagues will say "no open markets."
- **College team matching:** pro leagues (~30 teams) match Kalshi↔ESPN cleanly.
  College has hundreds of teams with inconsistent abbreviations, so some markets
  may show up as "unmatched" and get skipped (safe — it just won't bet them). If
  a team you want is skipped, add its Kalshi code to the alias handling.

Example output:

```
  RECOMMENDED BETS  (edge ≥ 3%, quarter-Kelly on $1000)
  BUY YES on DAL  @ 0.47  (backs DAL to win) | model 82% vs mkt 46% | edge 36.2% | stake $166.04 | DAL@PHI 17-10 Q4 8:12
  BUY NO  on KC   @ 0.30  (backs BUF to win) | model 58% vs mkt 71% | edge 12.7% | stake $ 41.94 | BUF@KC 20-21 Q4 2:40
```

Each market is "will <team> win?" — the tool tells you the side (YES/NO), the
price to pay, who you're backing, your model probability vs the market, the edge,
and the recommended stake. It only lists bets whose edge clears
`min_edge_to_trade` in `config.yaml`.

Two important caveats before betting real money:
- **It's currently July (offseason).** There are no live NFL/NBA games to scan
  right now, so a live run will correctly say "no open markets." Use `--demo`
  until the season starts.
- **Refit σ on real data first** (section 3b) — the shipped σ is from mock data.

---

## 1. Setup

```bash
cd kalshi-fair-value
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Get data

You need two data sources:

**A. Historical play-by-play data (to fit sigma and to backtest)**

Easiest option — the `nfl_data_py` package pulls the same data as nflfastR:

```bash
pip install nfl_data_py
python -c "
import nfl_data_py as nfl
df = nfl.import_pbp_data([2022, 2023, 2024])
df.to_csv('data/nfl_pbp_raw.csv', index=False)
"
```

If you don't have this yet, run `src/generate_mock_data.py` first — it creates
synthetic but realistic game data so you can build and test the entire pipeline
before touching real data.

```bash
python src/generate_mock_data.py
```

This writes `data/mock_pbp.csv` and `data/mock_games.csv`.

**B. Kalshi market data**

1. Create a Kalshi account and generate an API key at https://kalshi.com
   (Settings → API Keys). Read-only market data does not require trading
   permissions.
2. Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

3. Find the market ticker for the game you want (e.g. on the Kalshi site,
   the NFL winner markets look like `KXNFLGAME-25SEP07DALPHI-DAL`). Put it
   into `config.yaml`.

## 3. Pipeline — run in order

```bash
# Step 1: fit Elo ratings from historical games
python src/elo.py --input data/mock_games.csv --output output/elo_ratings.csv

# Step 2: calibrate sigma (volatility) for the in-game model
python src/fit_sigma.py --input data/mock_pbp.csv --output output/sigma_fit.json

# Step 3: backtest the full model on historical games, check calibration
python src/backtest.py --pbp data/mock_pbp.csv --sigma output/sigma_fit.json \
    --output output/backtest_results.csv

# Step 4: produce the calibration plot (the "proof" chart)
python src/calibration.py --input output/backtest_results.csv \
    --output output/calibration_plot.png

# Step 5 (needs live Kalshi access + a live game): monitor live mispricings
python src/live_monitor.py --ticker KXNFLGAME-XXXXX --sigma output/sigma_fit.json
```

## 3a. Paper trading — try it for real (no real money)

Two additions make this a self-running paper trader instead of a manual monitor:
`espn_feed.py` auto-pulls the live score/clock, and `live_paper_trader.py` books
simulated fills and keeps a persistent P&L ledger. Kalshi market data is public,
so **no API key is needed** for read-only prices.

First, sanity-check it offline (no network, scripted game):

```bash
python src/live_paper_trader.py --demo --sigma output/sigma_fit.json
```

Then run it against a real, in-progress game. Find the Kalshi ticker and note
which team the YES contract pays on (the suffix, e.g. `-DAL` => YES pays if DAL
wins — often the away team):

```bash
python src/live_paper_trader.py \
  --league nfl --home PHI --away DAL \
  --ticker KXNFLGAME-25SEP07DALPHI-DAL --yes-team DAL \
  --sigma output/sigma_real.json           # see 3b: fit sigma on REAL data first
```

It polls every 15s, books paper trades when the edge clears the threshold, and
writes `output/paper_ledger_<ticker>.json` (survives restarts). At the final
whistle it settles every open position against the real winner and prints P&L.

> Reality check: profitability depends entirely on whether your model is sharper
> than Kalshi's price. `src/paper_trade.py` (Monte Carlo over historical games)
> shows that against an **efficient** market you *lose* to slippage; you only
> profit if the market is genuinely mispriced. Run several real games before
> concluding anything.

## 3b. Fit sigma on REAL NFL data (not mock)

The default `sigma_fit.json` is fit on synthetic data. For live trading, refit on
real games:

```bash
pip install nfl_data_py
python src/build_real_pbp.py --seasons 2022 2023 2024 --out data/nfl_pbp_real.csv
python src/fit_sigma.py --input data/nfl_pbp_real.csv --output output/sigma_real.json
python src/backtest.py  --pbp data/nfl_pbp_real.csv --sigma output/sigma_real.json \
    --output output/backtest_real.csv
python src/calibration.py --input output/backtest_real.csv --output output/calibration_real.png
```

Compare `calibration_real.png` to the mock one — the gap tells you how well the
normal-margin assumption actually holds on real football.

## 4. What each script produces

| Script | Output | What to look at |
|---|---|---|
| `elo.py` | team ratings over time | sanity check: good teams should have higher ratings |
| `fit_sigma.py` | single number, sigma | should be roughly stable across seasons |
| `backtest.py` | model prob vs actual outcome for every game-state row | raw material for calibration |
| `calibration.py` | reliability diagram (PNG) | should hug the 45° line if model is honest |
| `live_monitor.py` | live log of (model prob, market price, edge, suggested Kelly stake) | this is your "trading signal" output |

## 5. Repo structure

```
kalshi-fair-value/
├── README.md
├── requirements.txt
├── config.yaml               # sport, sigma defaults, thresholds
├── .env.example
├── data/                     # raw + mock data lives here (gitignored)
├── output/                   # generated results, plots (gitignored)
├── docs/
│   └── math.tex              # full mathematical writeup
└── src/
    ├── generate_mock_data.py # synthetic data so the pipeline runs standalone
    ├── elo.py                 # pre-game win probability
    ├── stern_model.py         # in-game win probability (core stochastic model)
    ├── fit_sigma.py            # calibrates volatility parameter from history
    ├── backtest.py             # runs model over historical games
    ├── calibration.py          # reliability diagram + Brier score
    ├── kelly.py                 # position sizing from model edge
    ├── scan.py                  # ⭐ MAIN PROGRAM: scan markets -> ranked bets
    ├── kalshi_client.py         # public Kalshi market data (no key needed to read)
    ├── live_monitor.py          # manual-entry live monitor (original)
    ├── espn_feed.py             # auto live score/clock from ESPN (no key)
    ├── live_paper_trader.py     # self-filling paper-trading ledger loop
    ├── paper_trade.py           # Monte Carlo paper-trading backtest (is there edge?)
    └── build_real_pbp.py        # convert nfl_data_py pbp -> fit_sigma schema
```

## 6. Honest limitations (say these out loud in an interview — it shows judgment)

- Stern's model assumes the score margin behaves like driftless Brownian motion.
  It's a good approximation but ignores end-game strategic effects (fouling,
  garbage time, timeout usage) — NBA especially deviates near the end of games.
- Sigma is treated as constant across all game states. A more advanced version
  fits sigma as a function of time remaining (scoring pace differs early vs. late).
- Kalshi order books are thin. The "edge" you compute against the last traded
  price may not be executable at size — `kelly.py` includes a slippage haircut
  parameter for this reason, but it's a simplification, not a full market-impact
  model.
- This is a paper-trading / research tool. Live order execution against Kalshi's
  trading API is not included — extending `kalshi_client.py` to place orders
  is the natural next step once you trust the signal.
