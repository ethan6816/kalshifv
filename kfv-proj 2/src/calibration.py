import argparse
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path


def compute_calibration(df: pd.DataFrame, n_bins: int = 10) -> pd.DataFrame:
    bins = np.linspace(0, 1, n_bins + 1)
    df = df.copy()
    df["bin"] = pd.cut(df["model_prob"], bins, include_lowest=True)

    grouped = df.groupby("bin", observed=True).agg(
        predicted_mean=("model_prob", "mean"),
        actual_rate=("home_won", "mean"),
        n=("home_won", "size"),
    ).reset_index()

    return grouped


def plot_calibration(calib: pd.DataFrame, output_path: str):
    fig, ax = plt.subplots(figsize=(6, 6))

    ax.plot([0, 1], [0, 1], "k--", alpha=0.5, label="Perfect calibration")

    sizes = calib["n"] / calib["n"].max() * 400 + 20
    ax.scatter(calib["predicted_mean"], calib["actual_rate"], s=sizes,
               alpha=0.7, edgecolors="black", label="Model bins (size = sample count)")

    ax.set_xlabel("Predicted win probability")
    ax.set_ylabel("Actual win rate")
    ax.set_title("Calibration: Stern Model vs. Realized Outcomes")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.legend()
    ax.grid(alpha=0.3)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    print(f"Saved calibration plot to {output_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="backtest_results.csv from backtest.py")
    parser.add_argument("--output", required=True, help="PNG output path")
    parser.add_argument("--bins", type=int, default=10)
    args = parser.parse_args()

    df = pd.read_csv(args.input)
    calib = compute_calibration(df, n_bins=args.bins)
    print(calib.to_string(index=False))

    plot_calibration(calib, args.output)

    brier = ((df.model_prob - df.home_won) ** 2).mean()
    print(f"\nBrier score: {brier:.4f}")


if __name__ == "__main__":
    main()
