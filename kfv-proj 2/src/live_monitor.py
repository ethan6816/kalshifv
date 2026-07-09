import argparse
import json
import time
import yaml
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from stern_model import GameState, in_game_win_prob
from kalshi_client import get_yes_price, get_mock_price
from kelly import size_position


def load_config(path="config.yaml"):
    with open(path) as f:
        return yaml.safe_load(f)


def get_live_game_state(game_length_minutes: float) -> GameState:
    print("\n--- Enter current game state (or Ctrl+C to stop) ---")
    home_score = int(input("Home score: "))
    away_score = int(input("Away score: "))
    minutes_elapsed = float(input(f"Minutes elapsed (0-{game_length_minutes}): "))
    return GameState(home_score=home_score, away_score=away_score,
                      minutes_elapsed=minutes_elapsed,
                      game_length_minutes=game_length_minutes)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", default=None, help="Kalshi market ticker; omit to use mock prices")
    parser.add_argument("--sigma", required=True, help="JSON file from fit_sigma.py")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--once", action="store_true", help="run a single check instead of looping")
    args = parser.parse_args()

    cfg = load_config(args.config)
    with open(args.sigma) as f:
        sigma_data = json.load(f)
    sigma = sigma_data["sigma"]
    game_length = sigma_data["game_length_minutes"]

    kelly_cfg = cfg["kelly"]
    alert_threshold = cfg["live_monitor"]["edge_alert_threshold"]

    while True:
        state = get_live_game_state(game_length)
        model_prob = in_game_win_prob(state, sigma)

        if args.ticker:
            market_price = get_yes_price(args.ticker)
        else:
            market_price = get_mock_price()
            print("(using mock market price -- no ticker supplied)")

        result = size_position(model_prob, market_price, kelly_cfg)

        print(f"\n  Model win prob (home):   {model_prob:.3f}")
        print(f"  Kalshi market price:     {market_price:.3f}")
        print(f"  Edge:                    {result.edge:+.3f}")
        print(f"  Recommended stake (frac of bankroll): {result.recommended_fraction:.3f}")

        if abs(result.edge) >= alert_threshold:
            side = "YES" if result.edge > 0 else "NO"
            print(f"  >>> ALERT: {abs(result.edge)*100:.1f}c edge detected. Suggested side: {side}")

        if args.once:
            break

        time.sleep(cfg["live_monitor"]["poll_interval_seconds"])


if __name__ == "__main__":
    main()
