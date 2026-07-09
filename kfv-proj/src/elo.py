import argparse
import pandas as pd
import yaml
from pathlib import Path


def load_config(path="config.yaml"):
    with open(path) as f:
        return yaml.safe_load(f)


def expected_score(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10 ** (-(rating_a - rating_b) / 400.0))


class EloSystem:
    def __init__(self, initial_rating=1500.0, k_factor=20.0, home_field_advantage=65.0):
        self.initial_rating = initial_rating
        self.k = k_factor
        self.hfa = home_field_advantage
        self.ratings = {}

    def get_rating(self, team: str) -> float:
        return self.ratings.get(team, self.initial_rating)

    def pregame_win_prob(self, home_team: str, away_team: str) -> float:
        r_home = self.get_rating(home_team) + self.hfa
        r_away = self.get_rating(away_team)
        return expected_score(r_home, r_away)

    def update(self, home_team: str, away_team: str, home_won: bool):
        r_home = self.get_rating(home_team)
        r_away = self.get_rating(away_team)

        exp_home = expected_score(r_home + self.hfa, r_away)
        actual_home = 1.0 if home_won else 0.0

        self.ratings[home_team] = r_home + self.k * (actual_home - exp_home)
        self.ratings[away_team] = r_away + self.k * ((1 - actual_home) - (1 - exp_home))

    def run_season(self, games: pd.DataFrame) -> pd.DataFrame:
        games = games.sort_values("date").reset_index(drop=True)
        pregame_probs = []

        for _, row in games.iterrows():
            p = self.pregame_win_prob(row.home_team, row.away_team)
            pregame_probs.append(p)
            home_won = row.home_score > row.away_score
            self.update(row.home_team, row.away_team, home_won)

        games["pregame_home_prob"] = pregame_probs
        return games


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="CSV with columns: date,home_team,away_team,home_score,away_score")
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    cfg = load_config(args.config)["elo"]
    games = pd.read_csv(args.input, parse_dates=["date"])

    elo = EloSystem(
        initial_rating=cfg["initial_rating"],
        k_factor=cfg["k_factor"],
        home_field_advantage=cfg["home_field_advantage"],
    )
    result = elo.run_season(games)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False)

    final_ratings = pd.Series(elo.ratings).sort_values(ascending=False)
    print("Final ratings (top 10):")
    print(final_ratings.head(10))
    print(f"\nSaved pregame probabilities to {args.output}")


if __name__ == "__main__":
    main()
