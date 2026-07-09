from dataclasses import dataclass
from scipy.stats import norm
import numpy as np


@dataclass
class GameState:
    home_score: int
    away_score: int
    minutes_elapsed: float
    game_length_minutes: float = 60.0

    @property
    def margin(self) -> float:
        return self.home_score - self.away_score

    @property
    def tau(self) -> float:
        remaining = max(self.game_length_minutes - self.minutes_elapsed, 1e-6)
        return remaining / self.game_length_minutes


def in_game_win_prob(state: GameState, sigma: float, pregame_prob: float = None,
                      blend_weight: float = 0.0) -> float:
    tau = state.tau
    m = state.margin

    z = m / (sigma * np.sqrt(tau))
    p_score_model = norm.cdf(z)

    if pregame_prob is None or blend_weight == 0.0:
        return float(p_score_model)

    w = blend_weight * tau
    p_blended = w * pregame_prob + (1 - w) * p_score_model
    return float(np.clip(p_blended, 0.0, 1.0))


def implied_probability_from_kalshi_price(yes_price_cents: float) -> float:
    return yes_price_cents / 100.0


if __name__ == "__main__":
    sigma = 13.5
    examples = [
        GameState(home_score=0, away_score=0, minutes_elapsed=0),
        GameState(home_score=10, away_score=0, minutes_elapsed=15),
        GameState(home_score=10, away_score=7, minutes_elapsed=45),
        GameState(home_score=10, away_score=7, minutes_elapsed=58),
        GameState(home_score=17, away_score=20, minutes_elapsed=59),
    ]
    for s in examples:
        p = in_game_win_prob(s, sigma)
        print(f"margin={s.margin:+d}  minutes_elapsed={s.minutes_elapsed:>4.1f}  "
              f"tau={s.tau:.3f}  P(home wins)={p:.3f}")
