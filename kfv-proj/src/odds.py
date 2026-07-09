import argparse
import sys
import yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from stern_model import GameState, in_game_win_prob
from espn_feed import minutes_elapsed_from_status, LEAGUE_TIMING

GAME_LENGTH = {"nfl": 60.0, "nba": 48.0, "wnba": 40.0, "ncaamb": 40.0, "ncaaf": 60.0}
SIGMA_KEY = {"nfl": "default_nfl", "nba": "default_nba", "wnba": "default_wnba",
             "ncaamb": "default_ncaamb", "ncaaf": "default_ncaaf"}


def resolve_elapsed(league, elapsed, period, clock):
    if elapsed is not None:
        return float(elapsed)
    if period is not None:
        return minutes_elapsed_from_status({"period": period, "displayClock": clock or "0:00"}, league)
    raise SystemExit("Give the game time with either --elapsed MIN  or  --period N --clock MM:SS")


def compute(league, home_score, away_score, elapsed, sigma):
    state = GameState(home_score=home_score, away_score=away_score,
                      minutes_elapsed=elapsed, game_length_minutes=GAME_LENGTH[league])
    p_home = in_game_win_prob(state, sigma)
    return p_home, 1 - p_home, state.tau


def cents(p):
    return int(round(p * 100))


def run(league, home_score, away_score, elapsed, sigma, home_label, away_label):
    p_home, p_away, tau = compute(league, home_score, away_score, elapsed, sigma)
    margin = home_score - away_score
    pct_left = tau * 100
    print()
    print(f"  {league.upper()}  |  {away_label} {away_score}  -  {home_score} {home_label}  "
          f"(margin {margin:+d}, {elapsed:.1f} min in, {pct_left:.0f}% of game left, sigma={sigma})")
    print("  " + "-" * 58)
    print(f"  {home_label:<10} win prob  {p_home:6.1%}   ->  fair price ~{cents(p_home):>3d}c")
    print(f"  {away_label:<10} win prob  {p_away:6.1%}   ->  fair price ~{cents(p_away):>3d}c")
    print()
    print(f"  If Kalshi's YES price for {home_label} is BELOW {cents(p_home)}c, the model says it's underpriced.")
    print()
    return p_home, p_away


def interactive(cfg):
    print("Fair-odds calculator. Blank league = nfl. Ctrl+C to quit.")
    while True:
        try:
            league = (input("\nLeague [nfl/nba/wnba/ncaamb/ncaaf]: ").strip() or "nfl").lower()
            if league not in GAME_LENGTH:
                print("  unknown league"); continue
            hs = int(input("Home score: "))
            as_ = int(input("Away score: "))
            elapsed = float(input(f"Minutes elapsed (0-{GAME_LENGTH[league]:.0f}): "))
            sigma = cfg["sigma"][SIGMA_KEY[league]]
            run(league, hs, as_, elapsed, sigma, "HOME", "AWAY")
        except KeyboardInterrupt:
            print("\nbye"); return
        except (ValueError, KeyError) as e:
            print(f"  bad input: {e}")


def main():
    ap = argparse.ArgumentParser(description="Compute model fair win-odds for a live game state.")
    ap.add_argument("--league", default="nfl", choices=list(GAME_LENGTH))
    ap.add_argument("--home", type=int, help="home score")
    ap.add_argument("--away", type=int, help="away score")
    ap.add_argument("--elapsed", type=float, help="minutes elapsed")
    ap.add_argument("--period", type=int, help="quarter/half number")
    ap.add_argument("--clock", help="time left in period, MM:SS")
    ap.add_argument("--sigma", type=float, help="override volatility; else config default")
    ap.add_argument("--home-team", default="HOME")
    ap.add_argument("--away-team", default="AWAY")
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()

    with open(args.config) as f:
        cfg = yaml.safe_load(f)

    if args.home is None or args.away is None:
        interactive(cfg)
        return

    sigma = args.sigma if args.sigma is not None else cfg["sigma"][SIGMA_KEY[args.league]]
    elapsed = resolve_elapsed(args.league, args.elapsed, args.period, args.clock)
    run(args.league, args.home, args.away, elapsed, sigma, args.home_team, args.away_team)


if __name__ == "__main__":
    main()
