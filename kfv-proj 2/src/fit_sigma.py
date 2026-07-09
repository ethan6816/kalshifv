import argparse
import json
import numpy as np
import pandas as pd
from pathlib import Path


def compute_sigma(pbp: pd.DataFrame, game_length_minutes: float = 60.0) -> dict:
    df = pbp.copy()
    df["margin"] = df.home_score - df.away_score
    df["final_margin"] = df.final_home_score - df.final_away_score
    df["tau"] = ((game_length_minutes - df.minutes_elapsed) / game_length_minutes).clip(lower=1e-6)

    df["y"] = df.final_margin - df.margin
    df["y_scaled"] = df.y / np.sqrt(df.tau)

    sigma = float(df["y_scaled"].std(ddof=1))

    return {
        "sigma": sigma,
        "n_snapshots": int(len(df)),
        "n_games": int(df.game_id.nunique()),
        "game_length_minutes": game_length_minutes,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="play-by-play CSV")
    parser.add_argument("--output", required=True, help="JSON output path")
    parser.add_argument("--game-length", type=float, default=60.0)
    args = parser.parse_args()

    pbp = pd.read_csv(args.input)
    result = compute_sigma(pbp, game_length_minutes=args.game_length)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)

    print(json.dumps(result, indent=2))
    print(f"\nSaved to {args.output}")


if __name__ == "__main__":
    main()
