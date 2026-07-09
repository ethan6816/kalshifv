import argparse
import json
import re
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from build_pbp import build, GAME_LENGTH
from fit_sigma import compute_sigma
from backtest import run_backtest
from calibration import compute_calibration, plot_calibration

SIGMA_KEY = {"nfl": "default_nfl", "ncaaf": "default_ncaaf", "nba": "default_nba",
             "wnba": "default_wnba", "ncaamb": "default_ncaamb"}


def write_config_sigma(config_path, league, sigma):
    key = SIGMA_KEY[league]
    text = Path(config_path).read_text()
    new = re.sub(rf"(\n\s*{key}:\s*)[0-9.]+", rf"\g<1>{sigma:.2f}", text)
    if new != text:
        Path(config_path).write_text(new)
        print(f"  updated {key} = {sigma:.2f} in {config_path}")
    else:
        print(f"  (could not find {key} in {config_path}; leaving it unchanged)")


def main():
    ap = argparse.ArgumentParser(
        description="One command: scrape real games -> fit sigma -> backtest -> calibration plot.")
    ap.add_argument("--league", required=True, choices=list(GAME_LENGTH))
    ap.add_argument("--seasons", nargs="+", type=int, help="e.g. 2023 2024 2025")
    ap.add_argument("--data", default=None, help="reuse an existing scraped CSV instead of scraping")
    ap.add_argument("--limit", type=int, default=None, help="cap games (quick test)")
    ap.add_argument("--downsample-seconds", type=int, default=60)
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--write-config", action="store_true", help="save fitted sigma back into config.yaml")
    ap.add_argument("--outdir", default="output")
    ap.add_argument("--datadir", default="data")
    args = ap.parse_args()

    league, gl = args.league, GAME_LENGTH[args.league]

    if args.data:
        df = pd.read_csv(args.data)
        print(f"Loaded {len(df)} snapshots from {args.data}")
    else:
        if not args.seasons:
            ap.error("give --seasons (or --data to reuse a scraped file)")
        print(f"Scraping real {league.upper()} games from ESPN (no API key)...")
        df = build(league, args.seasons, args.downsample_seconds, args.limit)
        if df.empty:
            print("No data pulled. Check network / seasons.")
            return
        data_path = Path(args.datadir) / f"{league}_pbp_real.csv"
        data_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(data_path, index=False)
        print(f"Saved raw data -> {data_path}")

    sigma_info = compute_sigma(df, game_length_minutes=gl)
    sigma = sigma_info["sigma"]
    Path(args.outdir).mkdir(parents=True, exist_ok=True)
    sigma_path = Path(args.outdir) / f"sigma_{league}.json"
    sigma_path.write_text(json.dumps(sigma_info, indent=2))

    bt = run_backtest(df, sigma=sigma, game_length_minutes=gl)
    brier = float(((bt.model_prob - bt.home_won) ** 2).mean())
    calib = compute_calibration(bt)
    plot_path = Path(args.outdir) / f"calibration_{league}.png"
    plot_calibration(calib, str(plot_path))

    print("\n" + "=" * 60)
    print(f"  {league.upper()} fitted on REAL data")
    print("=" * 60)
    print(f"  games:        {sigma_info['n_games']}")
    print(f"  snapshots:    {sigma_info['n_snapshots']}")
    print(f"  sigma:        {sigma:.2f} points   (was a config guess before)")
    print(f"  Brier score:  {brier:.4f}   (0.25 = coin flip, lower = better)")
    print(f"  sigma file:   {sigma_path}")
    print(f"  calibration:  {plot_path}")
    if args.write_config:
        write_config_sigma(args.config, league, sigma)
    print(f"\n  Use it live:  python src/scan.py --league {league} --sigma {sigma_path} --watch\n")


if __name__ == "__main__":
    main()
