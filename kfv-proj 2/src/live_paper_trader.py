import argparse
import json
import time
import yaml
from dataclasses import dataclass, asdict, field
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from stern_model import GameState, in_game_win_prob
from kelly import size_position


@dataclass
class Position:
    side: str
    entry_price: float
    contracts: float
    stake: float
    poll_note: str
    status: str = "open"
    pnl: float = 0.0


@dataclass
class Ledger:
    ticker: str
    yes_team: str
    starting_bankroll: float = 1000.0
    cash: float = 1000.0
    positions: list = field(default_factory=list)
    log: list = field(default_factory=list)

    @property
    def realized_pnl(self):
        return round(self.cash - self.starting_bankroll, 2)

    @property
    def exposure(self):
        return round(sum(p.stake for p in self.positions if p.status == "open"), 2)

    def open_side(self, side):
        return any(p.status == "open" and p.side == side for p in self.positions)

    def book(self, side, price, stake, note):
        stake = min(stake, self.cash)
        if stake <= 0 or price <= 0:
            return None
        contracts = stake / price
        pos = Position(side=side, entry_price=round(price, 4), contracts=round(contracts, 2),
                       stake=round(stake, 2), poll_note=note)
        self.positions.append(pos)
        self.cash -= stake
        self.log.append(f"BOOK {side} {pos.contracts} @ {pos.entry_price}  stake=${pos.stake}  ({note})")
        return pos

    def settle(self, yes_won: bool):
        for p in self.positions:
            if p.status != "open":
                continue
            win = (p.side == "YES" and yes_won) or (p.side == "NO" and not yes_won)
            payoff = p.contracts * (1.0 if win else 0.0)
            p.pnl = round(payoff - p.stake, 2)
            p.status = "settled"
            self.cash += payoff
            self.log.append(f"SETTLE {p.side} {p.contracts} -> {'WON' if win else 'LOST'}  pnl=${p.pnl}")

    def save(self, path):
        d = asdict(self)
        d["realized_pnl"] = self.realized_pnl
        d["exposure"] = self.exposure
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(d, indent=2))

    @classmethod
    def load_or_new(cls, path, ticker, yes_team, bankroll):
        p = Path(path)
        if p.exists():
            d = json.loads(p.read_text())
            led = cls(ticker=d["ticker"], yes_team=d["yes_team"],
                      starting_bankroll=d["starting_bankroll"], cash=d["cash"],
                      log=d.get("log", []))
            led.positions = [Position(**{k: v for k, v in pos.items()}) for pos in d.get("positions", [])]
            return led
        return cls(ticker=ticker, yes_team=yes_team, starting_bankroll=bankroll, cash=bankroll)


def model_prob_for_yes(state: GameState, sigma: float, home_team: str, yes_team: str) -> float:
    p_home = in_game_win_prob(state, sigma)
    if yes_team.upper() == home_team.upper():
        return p_home
    return 1.0 - p_home


def decide_and_book(ledger: Ledger, model_yes_prob: float, quote: dict, cfg: dict, note: str):
    kelly_cfg = cfg["kelly"]
    mid = quote.get("mid")
    if mid is None:
        return None
    res = size_position(model_yes_prob, mid, kelly_cfg)
    if not res.should_trade:
        return {"edge": res.edge, "action": "hold", "reason": "below threshold"}

    side = "YES" if res.edge > 0 else "NO"
    exec_price = quote.get("buy_yes") if side == "YES" else quote.get("buy_no")
    if exec_price is None:
        return {"edge": res.edge, "action": "hold", "reason": "no executable ask on that side"}
    if ledger.open_side(side):
        return {"edge": res.edge, "action": "hold", "reason": f"already hold {side}"}

    stake = res.recommended_fraction * (ledger.cash + ledger.exposure)
    pos = ledger.book(side, exec_price, stake, note)
    return {"edge": res.edge, "action": "book", "side": side, "price": exec_price,
            "stake": pos.stake if pos else 0.0}


def run_live(args, cfg, sigma, game_length):
    from espn_feed import find_game
    from kalshi_client import get_quote

    ledger_path = args.ledger or f"output/paper_ledger_{args.ticker}.json"
    ledger = Ledger.load_or_new(ledger_path, args.ticker, args.yes_team, args.bankroll)
    print(f"Paper trading {args.away}@{args.home} | YES pays on {args.yes_team} | "
          f"ledger: {ledger_path}\nStart bankroll ${ledger.starting_bankroll}\n")

    while True:
        try:
            g = find_game(args.league, args.home)
            if g is None:
                print("Game not on ESPN scoreboard yet; retrying...")
                time.sleep(cfg["live_monitor"]["poll_interval_seconds"]); continue

            state = GameState(home_score=g["home_score"], away_score=g["away_score"],
                              minutes_elapsed=g["minutes_elapsed"], game_length_minutes=game_length)
            model_yes = model_prob_for_yes(state, sigma, args.home, args.yes_team)
            quote = get_quote(args.ticker)
            note = f"{g['short_detail']} {g['away_score']}-{g['home_score']}"
            out = decide_and_book(ledger, model_yes, quote, cfg, note)

            print(f"[{g['short_detail']}] {args.away} {g['away_score']} - {g['home_score']} {args.home} "
                  f"| model P({args.yes_team})={model_yes:.3f} mkt_mid={quote['mid']} "
                  f"| {out}")
            ledger.save(ledger_path)

            if g["state"] == "post":
                yes_won = (g["home_score"] > g["away_score"]) if args.yes_team.upper() == args.home.upper() \
                          else (g["away_score"] > g["home_score"])
                ledger.settle(yes_won)
                ledger.save(ledger_path)
                print(f"\nGAME FINAL. YES ({args.yes_team}) {'WON' if yes_won else 'LOST'}. "
                      f"Realized P&L: ${ledger.realized_pnl}  Ending bankroll: ${round(ledger.cash,2)}")
                break

            time.sleep(cfg["live_monitor"]["poll_interval_seconds"])
        except KeyboardInterrupt:
            ledger.save(ledger_path); print("\nStopped; ledger saved."); break


def run_demo(cfg, sigma, game_length):
    ledger = Ledger(ticker="DEMO", yes_team="HOME", starting_bankroll=1000.0, cash=1000.0)
    script = [(5, 0, 7, 0.45), (20, 10, 7, 0.47), (35, 17, 14, 0.52),
              (50, 24, 21, 0.55), (58, 27, 21, 0.6)]
    for me, hs, as_, mid in script:
        state = GameState(hs, as_, me, game_length)
        model_yes = in_game_win_prob(state, sigma)
        buy = min(mid + 0.02, 0.98)
        quote = {"mid": mid, "buy_yes": buy, "buy_no": round(1 - mid + 0.02, 4)}
        out = decide_and_book(ledger, model_yes, quote, cfg, f"Q@{me}min {as_}-{hs}")
        print(f"t={me:>2}min  HOME {hs}-{as_}  model={model_yes:.3f} mid={mid}  -> {out}")
    ledger.settle(yes_won=True)
    print(f"\nDEMO FINAL. Realized P&L ${ledger.realized_pnl}  bankroll ${round(ledger.cash,2)}")
    for line in ledger.log:
        print("  ", line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sigma", required=True, help="JSON from fit_sigma.py")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--demo", action="store_true", help="offline scripted game, no network")
    ap.add_argument("--league", default="nfl", choices=["nfl", "nba", "wnba", "ncaamb", "ncaaf"])
    ap.add_argument("--home"); ap.add_argument("--away")
    ap.add_argument("--ticker"); ap.add_argument("--yes-team", dest="yes_team")
    ap.add_argument("--ledger", default=None)
    ap.add_argument("--bankroll", type=float, default=1000.0)
    args = ap.parse_args()

    with open(args.config) as f:
        cfg = yaml.safe_load(f)
    with open(args.sigma) as f:
        sd = json.load(f)
    sigma, game_length = sd["sigma"], sd["game_length_minutes"]

    if args.demo:
        run_demo(cfg, sigma, game_length)
        return
    missing = [k for k in ("home", "away", "ticker", "yes_team") if not getattr(args, k)]
    if missing:
        ap.error(f"live mode needs: {', '.join('--' + m for m in missing)} (or use --demo)")
    run_live(args, cfg, sigma, game_length)


if __name__ == "__main__":
    main()
