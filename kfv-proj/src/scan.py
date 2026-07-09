import argparse
import json
import yaml
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from stern_model import GameState, in_game_win_prob
from kelly import size_position
from espn_feed import list_games, _norm

LEAGUE_SERIES = {
    "nfl": "KXNFLGAME",
    "nba": "KXNBAGAME",
    "wnba": "KXWNBAGAME",
    "ncaamb": "KXNCAAMBGAME",
    "ncaaf": "KXNCAAFGAME",
}
GAME_LENGTH = {"nfl": 60.0, "nba": 48.0, "wnba": 40.0, "ncaamb": 40.0, "ncaaf": 60.0}
SIGMA_DEFAULT_KEY = {
    "nfl": "default_nfl", "nba": "default_nba", "wnba": "default_wnba",
    "ncaamb": "default_ncaamb", "ncaaf": "default_ncaaf",
}


def yes_team_from_ticker(ticker: str) -> str:
    return ticker.strip().split("-")[-1].upper() if ticker else ""


def build_index(games):
    idx = {}
    for g in games:
        aliases = set(g.get("home_aliases", set())) | set(g.get("away_aliases", set()))
        aliases |= {_norm(g["home_team"]), _norm(g["away_team"])}
        for a in aliases:
            if a:
                idx.setdefault(a, g)
    return idx


def _side_of(game, yes_norm):
    if yes_norm in set(game.get("away_aliases", set())) or yes_norm == _norm(game["away_team"]):
        return "away"
    if yes_norm in set(game.get("home_aliases", set())) or yes_norm == _norm(game["home_team"]):
        return "home"
    return None


def match_market(market, idx):
    candidates = [yes_team_from_ticker(market.get("ticker"))]
    for f in ("yes_sub_title", "yes_subtitle", "subtitle"):
        v = market.get(f)
        if v:
            candidates.append(v)
    for c in candidates:
        n = _norm(c)
        if n and n in idx:
            g = idx[n]
            side = _side_of(g, n)
            if side:
                return g, side, n
    return None, None, None


def evaluate(market, quote, idx, sigma, league, cfg, bankroll):
    ticker = market.get("ticker")
    yes_team = yes_team_from_ticker(ticker)
    game, yes_side, yes_norm = match_market(market, idx)

    if game is None:
        return {"league": league, "ticker": ticker, "skip": "no matching ESPN game", "yes_team": yes_team}
    if game["state"] != "in":
        return {"league": league, "ticker": ticker, "skip": f"game not live ({game['state']})",
                "yes_team": yes_team, "match": f"{game['away_team']}@{game['home_team']}"}
    if quote.get("mid") is None:
        return {"league": league, "ticker": ticker, "skip": "no Kalshi price", "yes_team": yes_team}

    state = GameState(home_score=game["home_score"], away_score=game["away_score"],
                      minutes_elapsed=game["minutes_elapsed"],
                      game_length_minutes=GAME_LENGTH[league])
    p_home = in_game_win_prob(state, sigma)
    model_yes = p_home if yes_side == "home" else 1 - p_home

    res = size_position(model_yes, quote["mid"], cfg["kelly"])
    side = "YES" if res.edge > 0 else "NO"
    exec_price = quote["buy_yes"] if side == "YES" else quote["buy_no"]
    yes_label = game["home_team"] if yes_side == "home" else game["away_team"]
    other = game["away_team"] if yes_side == "home" else game["home_team"]
    bet_team = yes_label if side == "YES" else other

    return {
        "league": league,
        "ticker": ticker,
        "match": f"{game['away_team']}@{game['home_team']}",
        "clock": game["short_detail"],
        "score": f"{game['away_score']}-{game['home_score']}",
        "yes_team": yes_label,
        "model_yes": round(model_yes, 3),
        "market_mid": quote["mid"],
        "edge": round(res.edge, 3),
        "side": side,
        "bet_team": bet_team,
        "exec_price": exec_price,
        "stake_frac": round(res.recommended_fraction, 4),
        "stake_dollars": round(res.recommended_fraction * bankroll, 2),
        "should_trade": res.should_trade,
    }


def render(recs, bankroll, min_edge, title):
    bets = sorted([r for r in recs if r.get("should_trade")], key=lambda r: -abs(r["edge"]))
    live_nobet = [r for r in recs if "skip" not in r and not r.get("should_trade")]

    print("\n" + "=" * 78)
    print(f"  {title}  (edge >= {min_edge:.0%}, quarter-Kelly on ${bankroll:.0f})")
    print("=" * 78)
    if not bets:
        print("  No bets clear the edge threshold right now.")
    for r in bets:
        action = f"BUY {r['side']} on {r['yes_team']}"
        print(f"  [{r['league']:<6}] {action:<20} @ {r['exec_price']:<5} "
              f"(backs {r['bet_team']:<5}) | model {r['model_yes']:.0%} vs mkt {r['market_mid']:.0%} "
              f"| edge {abs(r['edge']):.1%} | ${r['stake_dollars']:>7.2f} ({r['stake_frac']:.1%}) "
              f"| {r['match']} {r['score']} {r['clock']}")

    if live_nobet:
        print("\n  Live games, no edge:")
        for r in live_nobet:
            print(f"    [{r['league']:<6}] {r['match']:<12} {r['score']:<7} model {r['model_yes']:.0%} "
                  f"vs mkt {r['market_mid']:.0%} (edge {r['edge']:+.1%})  {r['clock']}")

    skips = [r for r in recs if "skip" in r]
    if skips:
        print(f"\n  Skipped {len(skips)} markets (not live / unmatched / no price).")
    print()
    return bets


def resolve_sigma(league, args, cfg):
    if args.sigma:
        with open(args.sigma) as f:
            return json.load(f)["sigma"], "fitted"
    return cfg["sigma"][SIGMA_DEFAULT_KEY[league]], "config-default"


def load_live(league):
    from kalshi_client import get_markets, quote_from_market
    markets = get_markets(series_ticker=LEAGUE_SERIES[league], status="open")
    idx = build_index(list_games(league))
    return [(m, quote_from_market(m)) for m in markets], idx


def _demo_game(home, away, hs, as_, me, state, detail):
    return {"home_team": home, "away_team": away, "home_aliases": {_norm(home)},
            "away_aliases": {_norm(away)}, "home_score": hs, "away_score": as_,
            "minutes_elapsed": me, "state": state, "short_detail": detail}


def load_demo():
    from kalshi_client import quote_from_market
    markets = [
        {"ticker": "KXWNBAGAME-DEMO-LV", "yes_bid": 45, "yes_ask": 47, "last_price": 46, "status": "open"},
        {"ticker": "KXWNBAGAME-DEMO-NY", "yes_bid": 70, "yes_ask": 72, "last_price": 71, "status": "open"},
    ]
    games = [
        _demo_game("SEA", "LV", 48, 60, 30, "in", "Q3 4:10"),
        _demo_game("NY", "CONN", 55, 54, 36, "in", "Q4 3:20"),
    ]
    return [(m, quote_from_market(m)) for m in markets], build_index(games)


def run_selftest(leagues):
    print("\nSELFTEST - checking the live data path (no API key needed).\n")
    from kalshi_client import get_markets
    ok = True
    for lg in leagues:
        line = f"  {lg:<7} "
        try:
            games = list_games(lg)
            live = [g for g in games if g["state"] == "in"]
            line += f"ESPN: {len(games):>2} games ({len(live)} live)   "
        except Exception as e:
            ok = False
            line += f"ESPN: ERROR {type(e).__name__}: {e}   "
        try:
            mkts = get_markets(series_ticker=LEAGUE_SERIES[lg], status="open")
            line += f"Kalshi[{LEAGUE_SERIES[lg]}]: {len(mkts):>3} open markets"
        except Exception as e:
            ok = False
            line += f"Kalshi[{LEAGUE_SERIES[lg]}]: ERROR {type(e).__name__}: {e}"
        print(line)
    print("\n  " + ("PASS - endpoints reachable. If a league shows 0/0 it's just off-season."
                    if ok else "Some calls errored above - check your network / the series ticker."))
    print("  A real edge only appears when a league has LIVE games AND open markets at the same time.\n")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", default="nfl", choices=list(LEAGUE_SERIES) + ["all"])
    ap.add_argument("--sigma", default=None, help="JSON from fit_sigma.py; omit to use config default")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--bankroll", type=float, default=1000.0)
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--selftest", action="store_true", help="check live ESPN+Kalshi connectivity, then exit")
    ap.add_argument("--watch", action="store_true", help="re-scan continuously (real-time)")
    ap.add_argument("--interval", type=int, default=30, help="seconds between --watch refreshes")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    with open(args.config) as f:
        cfg = yaml.safe_load(f)
    min_edge = cfg["kelly"].get("min_edge_to_trade", 0.03)
    if args.demo:
        leagues = ["wnba"]
    elif args.league == "all":
        leagues = list(LEAGUE_SERIES)
    else:
        leagues = [args.league]

    if args.selftest:
        run_selftest(leagues)
        return

    if args.demo:
        title = "WNBA DEMO"
    elif args.league == "all":
        title = "ALL IN-SEASON"
    else:
        title = args.league.upper()

    if args.watch:
        import time
        from datetime import datetime
        print(f"Watching {title} every {args.interval}s. Ctrl+C to stop.")
        try:
            while True:
                print(f"\n\n######## {datetime.now():%H:%M:%S} ########")
                scan_once(leagues, args, cfg, min_edge, title)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nStopped.")
    else:
        scan_once(leagues, args, cfg, min_edge, title)


def scan_once(leagues, args, cfg, min_edge, title):
    all_recs = []
    for lg in leagues:
        sigma, _ = resolve_sigma(lg, args, cfg)
        try:
            pairs, idx = load_demo() if args.demo else load_live(lg)
        except Exception as e:
            print(f"  {lg}: could not load ({type(e).__name__}: {e})")
            continue
        if not pairs:
            print(f"  {lg}: no open markets right now.")
            continue
        all_recs += [evaluate(m, q, idx, sigma, lg, cfg, args.bankroll) for m, q in pairs]

    bets = render(all_recs, args.bankroll, min_edge, f"{title} RECOMMENDED BETS")

    if args.out and bets:
        import csv
        keys = ["league", "ticker", "match", "score", "clock", "side", "bet_team", "exec_price",
                "model_yes", "market_mid", "edge", "stake_frac", "stake_dollars"]
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            for r in bets:
                w.writerow(r)
        print(f"  Wrote {len(bets)} recommendations -> {args.out}")
    return bets


if __name__ == "__main__":
    main()
