from dataclasses import dataclass


@dataclass
class KellyResult:
    edge: float
    kelly_fraction: float
    recommended_fraction: float
    should_trade: bool


def kelly_fraction_yes(model_prob: float, market_price: float) -> float:
    price = market_price
    if price <= 0 or price >= 1:
        return 0.0

    b = (1 - price) / price
    f_star = (model_prob * (1 + b) - 1) / b
    return f_star


def size_position(model_prob: float, market_price: float, config: dict) -> KellyResult:
    edge = model_prob - market_price

    min_edge = config.get("min_edge_to_trade", 0.03)
    slippage = config.get("slippage_haircut", 0.01)
    kelly_frac_mult = config.get("fraction", 0.25)

    effective_price = market_price + slippage if edge > 0 else market_price - slippage
    effective_price = min(max(effective_price, 0.01), 0.99)

    if abs(edge) < min_edge:
        return KellyResult(edge=edge, kelly_fraction=0.0,
                            recommended_fraction=0.0, should_trade=False)

    if edge > 0:
        f_star = kelly_fraction_yes(model_prob, effective_price)
    else:
        f_star = kelly_fraction_yes(1 - model_prob, 1 - effective_price)

    f_star = max(f_star, 0.0)
    recommended = f_star * kelly_frac_mult

    return KellyResult(
        edge=edge,
        kelly_fraction=f_star,
        recommended_fraction=recommended,
        should_trade=recommended > 0,
    )


if __name__ == "__main__":
    cfg = {"fraction": 0.25, "min_edge_to_trade": 0.03, "slippage_haircut": 0.01}

    examples = [
        (0.75, 0.63),
        (0.40, 0.55),
        (0.52, 0.50),
    ]
    for model_p, market_p in examples:
        r = size_position(model_p, market_p, cfg)
        print(f"model={model_p:.2f} market={market_p:.2f} -> edge={r.edge:+.3f} "
              f"full_kelly={r.kelly_fraction:.3f} recommended={r.recommended_fraction:.3f} "
              f"trade={r.should_trade}")
