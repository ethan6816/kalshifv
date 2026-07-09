import argparse
import time
from datetime import date, timedelta
from pathlib import Path
import sys

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent))
from espn_feed import SCOREBOARDS, minutes_elapsed_from_status

GAME_LENGTH = {"nfl": 60.0, "ncaaf": 60.0, "nba": 48.0, "wnba": 40.0, "ncaamb": 40.0}
SEASON_WINDOW = {
    "nfl": ((9, 1), (2, 15)),
    "ncaaf": ((8, 24), (1, 25)),
    "nba": ((10, 20), (6, 25)),
    "wnba": ((5, 1), (10, 20)),
    "ncaamb": ((11, 1), (4, 10)),
}


def _summary_url(league):
    return SCOREBOARDS[league].replace("scoreboard", "summary")


def game_ids_for_date(league, d):
    r = requests.get(SCOREBOARDS[league], params={"dates": d.strftime("%Y%m%d")}, timeout=15)
    r.raise_for_status()
    ids = []
    for ev in r.json().get("events", []):
        state = (((ev.get("status") or {}).get("type")) or {}).get("state")
        if state == "post":
            ids.append(ev.get("id"))
    return ids


def season_game_ids(league, season):
    (m0, d0), (m1, d1) = SEASON_WINDOW.get(league, ((1, 1), (12, 31)))
    start = date(season, m0, d0)
    end = date(season if m1 >= m0 else season + 1, m1, d1)
    ids, d = [], start
    while d <= end:
        try:
            ids += game_ids_for_date(league, d)
        except Exception as e:
            print(f"  {d}: {type(e).__name__}: {e}")
        d += timedelta(days=1)
        time.sleep(0.12)
    return ids


def fetch_summary(league, game_id):
    r = requests.get(_summary_url(league), params={"event": game_id}, timeout=15)
    r.raise_for_status()
    return r.json()


def plays_to_snapshots(summary, league, game_id=None):
    header = summary.get("header", {})
    comps = (header.get("competitions") or [{}])[0]
    competitors = comps.get("competitors", [])
    home = next((c for c in competitors if c.get("homeAway") == "home"), {})
    away = next((c for c in competitors if c.get("homeAway") == "away"), {})
    gid = game_id or header.get("id")

    def _int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    final_home, final_away = _int(home.get("score")), _int(away.get("score"))

    rows = []
    for p in summary.get("plays", []):
        hs, as_ = _int(p.get("homeScore")), _int(p.get("awayScore"))
        if hs is None or as_ is None:
            continue
        period = ((p.get("period") or {}).get("number")) or 1
        clock = (p.get("clock") or {}).get("displayValue") or "0:00"
        me = minutes_elapsed_from_status({"period": period, "displayClock": clock}, league)
        rows.append({"game_id": gid, "minutes_elapsed": round(me, 3),
                     "home_score": hs, "away_score": as_})

    cols = ["game_id", "minutes_elapsed", "home_score", "away_score",
            "final_home_score", "final_away_score"]
    if not rows:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(rows)
    if final_home is None or final_away is None:
        last = df.sort_values("minutes_elapsed").iloc[-1]
        final_home = final_home if final_home is not None else int(last.home_score)
        final_away = final_away if final_away is not None else int(last.away_score)
    df["final_home_score"], df["final_away_score"] = final_home, final_away
    return df[cols]


def downsample(df, seconds=60):
    df = df.sort_values("minutes_elapsed").copy()
    df["bucket"] = (df["minutes_elapsed"] // (seconds / 60.0)).astype(int)
    return df.drop_duplicates(["game_id", "bucket"], keep="last").drop(columns="bucket")


def build(league, seasons, downsample_seconds=60, limit=None):
    all_ids = []
    for s in seasons:
        ids = season_game_ids(league, s)
        print(f"  season {s}: {len(ids)} completed games")
        all_ids += ids
    if limit:
        all_ids = all_ids[:limit]

    frames = []
    for i, gid in enumerate(all_ids, 1):
        try:
            snaps = plays_to_snapshots(fetch_summary(league, gid), league, gid)
            if len(snaps):
                frames.append(downsample(snaps, downsample_seconds))
        except Exception as e:
            print(f"  game {gid}: {type(e).__name__}: {e}")
        if i % 25 == 0:
            print(f"  ...{i}/{len(all_ids)} games")
        time.sleep(0.12)

    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    gl = GAME_LENGTH[league]
    return out[out.minutes_elapsed.between(0, gl - 0.01)].reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser(description="Scrape real play-by-play from ESPN into fit_sigma schema, any league.")
    ap.add_argument("--league", default="wnba", choices=list(GAME_LENGTH))
    ap.add_argument("--seasons", nargs="+", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--downsample-seconds", type=int, default=60)
    ap.add_argument("--limit", type=int, default=None, help="cap number of games (quick test)")
    args = ap.parse_args()

    out = build(args.league, args.seasons, args.downsample_seconds, args.limit)
    if out.empty:
        print("No data pulled. Check network and that those seasons had games.")
        return
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out, index=False)
    print(f"Wrote {len(out)} snapshots across {out.game_id.nunique()} games -> {args.out}")


if __name__ == "__main__":
    main()
