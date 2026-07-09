import argparse
import numpy as np
import pandas as pd
from pathlib import Path

TEAMS = [f"TEAM_{i:02d}" for i in range(20)]


def simulate_season(n_games: int, true_sigma: float, game_length: float,
                     snapshots_per_game: int, seed: int = 42):
    rng = np.random.default_rng(seed)

    games = []
    pbp_rows = []

    true_strength = {t: rng.normal(0, 100) for t in TEAMS}

    dates = pd.date_range("2023-09-01", periods=n_games, freq="D")

    for i in range(n_games):
        home, away = rng.choice(TEAMS, size=2, replace=False)
        date = dates[i]

        true_edge = (true_strength[home] - true_strength[away]) / 25 + 2.0

        n_steps = 200
        dt = game_length / n_steps
        drift_per_step = true_edge / n_steps
        vol_per_step = true_sigma * np.sqrt(dt / game_length)

        increments = rng.normal(drift_per_step, vol_per_step, size=n_steps)
        margin_path = np.concatenate([[0], np.cumsum(increments)])
        minutes_path = np.linspace(0, game_length, n_steps + 1)

        final_margin = margin_path[-1]
        away_score = max(int(rng.integers(10, 24)), 0)
        home_score_final = int(round(away_score + final_margin))
        home_score_final = max(home_score_final, 0)

        games.append({
            "date": date,
            "home_team": home,
            "away_team": away,
            "home_score": home_score_final,
            "away_score": away_score,
        })

        snap_idxs = np.sort(rng.choice(np.arange(1, n_steps), size=snapshots_per_game, replace=False))
        for idx in snap_idxs:
            frac = margin_path[idx] / final_margin if final_margin != 0 else 0
            snap_home = int(round(away_score + margin_path[idx])) if idx < n_steps else home_score_final
            snap_home = max(snap_home, 0)
            pbp_rows.append({
                "game_id": i,
                "minutes_elapsed": minutes_path[idx],
                "home_score": snap_home,
                "away_score": away_score,
                "final_home_score": home_score_final,
                "final_away_score": away_score,
            })

    games_df = pd.DataFrame(games)
    pbp_df = pd.DataFrame(pbp_rows)
    return games_df, pbp_df


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-games", type=int, default=400)
    parser.add_argument("--true-sigma", type=float, default=13.5)
    parser.add_argument("--game-length", type=float, default=60.0)
    parser.add_argument("--snapshots-per-game", type=int, default=15)
    parser.add_argument("--out-dir", default="data")
    args = parser.parse_args()

    games_df, pbp_df = simulate_season(
        n_games=args.n_games,
        true_sigma=args.true_sigma,
        game_length=args.game_length,
        snapshots_per_game=args.snapshots_per_game,
    )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    games_df.to_csv(out_dir / "mock_games.csv", index=False)
    pbp_df.to_csv(out_dir / "mock_pbp.csv", index=False)

    print(f"Wrote {len(games_df)} games to {out_dir/'mock_games.csv'}")
    print(f"Wrote {len(pbp_df)} snapshots to {out_dir/'mock_pbp.csv'}")
    print(f"True sigma used in simulation: {args.true_sigma} "
          f"(fit_sigma.py should recover something close to this)")


if __name__ == "__main__":
    main()
