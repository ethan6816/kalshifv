import argparse
import json
import numpy as np
import pandas as pd
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from kelly import size_position


REGIMES = {
    "sharp_model":   dict(model_noise=0.02, market_noise=0.06, bias=0.00),
    "no_edge":       dict(model_noise=0.05, market_noise=0.05, bias=0.00),
    "biased_market": dict(model_noise=0.03, market_noise=0.05, bias=0.12),
    "overconfident": dict(model_noise=0.08, market_noise=0.04, bias=0.00),
}


def run_paper_trades(bt: pd.DataFrame, cfg: dict, regime: str, seed: int = 0,
                     starting_bankroll: float = 1000.0):
    rng = np.random.default_rng(seed)
    kelly_cfg = cfg["kelly"]
    rp = REGIMES[regime]

    per_game = bt.groupby("game_id", group_keys=False)[bt.columns.tolist()].apply(
        lambda g: g.sample(1, random_state=seed)
    ).reset_index(drop=True)

    bankroll = starting_bankroll
    rows = []
    for _, r in per_game.iterrows():
        truth = float(np.clip(r.model_prob, 0.001, 0.999))
        model_prob = float(np.clip(truth + rng.normal(0, rp["model_noise"]), 0.01, 0.99))
        mkt = 0.5 + (truth - 0.5) * (1 - rp["bias"]) + rng.normal(0, rp["market_noise"])
        price = float(np.clip(mkt, 0.02, 0.98))

        res = size_position(model_prob, price, kelly_cfg)
        if not res.should_trade:
            rows.append(dict(game_id=r.game_id, traded=False, side=None, price=price,
                             model_prob=model_prob, stake=0.0, pnl=0.0, bankroll=bankroll))
            continue

        side = "YES" if res.edge > 0 else "NO"
        stake = res.recommended_fraction * bankroll
        slip = kelly_cfg.get("slippage_haircut", 0.01)
        home_won = int(r.home_won)

        if side == "YES":
            fill = min(price + slip, 0.99)
            contracts = stake / fill
            payoff = contracts * (1.0 if home_won == 1 else 0.0)
            pnl = payoff - stake
        else:
            fill = min((1 - price) + slip, 0.99)
            contracts = stake / fill
            payoff = contracts * (1.0 if home_won == 0 else 0.0)
            pnl = payoff - stake

        bankroll += pnl
        rows.append(dict(game_id=r.game_id, traded=True, side=side, price=round(price, 3),
                         model_prob=round(model_prob, 3), edge=round(res.edge, 3),
                         stake=round(stake, 2), pnl=round(pnl, 2), bankroll=round(bankroll, 2)))

    ledger = pd.DataFrame(rows)
    traded = ledger[ledger.traded]
    n = len(traded)
    wins = int((traded.pnl > 0).sum()) if n else 0
    summary = dict(
        regime=regime,
        games=len(ledger),
        trades=n,
        win_rate=round(wins / n, 3) if n else None,
        total_pnl=round(bankroll - starting_bankroll, 2),
        roi_pct=round(100 * (bankroll - starting_bankroll) / starting_bankroll, 1),
        ending_bankroll=round(bankroll, 2),
    )
    return ledger, summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backtest", required=True, help="output/backtest_results.csv")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--out", default="output/paper_trades")
    ap.add_argument("--seeds", type=int, default=20, help="Monte Carlo runs per regime")
    args = ap.parse_args()

    import yaml
    with open(args.config) as f:
        cfg = yaml.safe_load(f)
    bt = pd.read_csv(args.backtest)

    Path(args.out).mkdir(parents=True, exist_ok=True)
    print(f"{'REGIME':<15}{'trades':>8}{'win_rate':>10}{'mean ROI%':>12}{'std ROI%':>10}"
          f"{'% runs profitable':>20}")
    for regime in REGIMES:
        rois, summ0, ledger0 = [], None, None
        for s in range(args.seeds):
            ledger, summary = run_paper_trades(bt, cfg, regime, seed=s)
            rois.append(summary["roi_pct"])
            if s == 0:
                summ0, ledger0 = summary, ledger
        ledger0.to_csv(Path(args.out) / f"ledger_{regime}.csv", index=False)
        rois = np.array(rois)
        print(f"{regime:<15}{summ0['trades']:>8}{summ0['win_rate']:>10}"
              f"{rois.mean():>12.1f}{rois.std():>10.1f}{100*(rois>0).mean():>19.0f}%")


if __name__ == "__main__":
    main()
