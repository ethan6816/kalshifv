import argparse
import json
import pandas as pd
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from stern_model import GameState, in_game_win_prob


def run_backtest(pbp: pd.DataFrame, sigma: float, game_length_minutes: float = 60.0) -> pd.DataFrame:
    df = pbp.copy()
    df["home_won"] = (df.final_home_score > df.final_away_score).astype(int)

    probs = []
    for _, row in df.iterrows():
        state = GameState(
            home_score=row.home_score,
            away_score=row.away_score,
            minutes_elapsed=row.minutes_elapsed,
            game_length_minutes=game_length_minutes,
        )
        probs.append(in_game_win_prob(state, sigma))

    df["model_prob"] = probs
    df["brier_component"] = (df.model_prob - df.home_won) ** 2
    return df


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pbp", required=True)
    parser.add_argument("--sigma", required=True, help="JSON file from fit_sigma.py")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    pbp = pd.read_csv(args.pbp)
    with open(args.sigma) as f:
        sigma_data = json.load(f)

    result = run_backtest(pbp, sigma=sigma_data["sigma"],
                           game_length_minutes=sigma_data["game_length_minutes"])

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False)

    brier_score = result["brier_component"].mean()
    print(f"Backtest complete: {len(result)} snapshots across {result.game_id.nunique()} games")
    print(f"Overall Brier score: {brier_score:.4f}  (lower is better; 0.25 = coin flip, 0 = perfect)")
    print(f"Saved to {args.output}")


if __name__ == "__main__":
    main()
