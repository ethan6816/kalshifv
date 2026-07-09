import argparse
import numpy as np
import pandas as pd


def build(seasons, downsample_seconds=60):
    import nfl_data_py as nfl
    raw = nfl.import_pbp_data(list(seasons), downcast=True)

    cols = ["game_id", "home_team", "away_team", "game_seconds_remaining",
            "total_home_score", "total_away_score"]
    df = raw[cols].dropna(subset=["game_seconds_remaining"]).copy()

    df["game_seconds_remaining"] = df["game_seconds_remaining"].clip(lower=0, upper=3600)
    df["minutes_elapsed"] = (3600 - df["game_seconds_remaining"]) / 60.0

    df = df.rename(columns={"total_home_score": "home_score",
                            "total_away_score": "away_score"})

    finals = (df.groupby("game_id")
                .agg(final_home_score=("home_score", "max"),
                     final_away_score=("away_score", "max"))
                .reset_index())
    df = df.merge(finals, on="game_id", how="left")

    df["bucket"] = (df["minutes_elapsed"] // (downsample_seconds / 60.0)).astype(int)
    df = df.sort_values("game_seconds_remaining").groupby(["game_id", "bucket"], as_index=False).first()

    out = df[["game_id", "minutes_elapsed", "home_score", "away_score",
              "final_home_score", "final_away_score"]].copy()
    out = out[out.minutes_elapsed.between(0, 59.99)]
    return out.reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", nargs="+", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--downsample-seconds", type=int, default=60)
    args = ap.parse_args()

    out = build(args.seasons, args.downsample_seconds)
    from pathlib import Path
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out, index=False)
    print(f"Wrote {len(out)} snapshots across {out.game_id.nunique()} games -> {args.out}")


if __name__ == "__main__":
    main()
