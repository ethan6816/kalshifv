import re
import requests

SCOREBOARDS = {
    "nfl": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
    "nba": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
    "wnba": "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard",
    "ncaamb": "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard",
    "ncaaf": "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard",
}
LEAGUE_TIMING = {
    "nfl": {"game_length": 60.0, "period_minutes": 15.0, "n_periods": 4},
    "nba": {"game_length": 48.0, "period_minutes": 12.0, "n_periods": 4},
    "wnba": {"game_length": 40.0, "period_minutes": 10.0, "n_periods": 4},
    "ncaamb": {"game_length": 40.0, "period_minutes": 20.0, "n_periods": 2},
    "ncaaf": {"game_length": 60.0, "period_minutes": 15.0, "n_periods": 4},
}


def _norm(s):
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def team_aliases(team: dict) -> set:
    keys = ["abbreviation", "displayName", "shortDisplayName", "location", "name", "nickname"]
    out = set()
    for k in keys:
        v = team.get(k)
        if v:
            out.add(_norm(v))
    return {a for a in out if a}


def _clock_to_seconds(display_clock: str) -> float:
    if not display_clock:
        return 0.0
    s = str(display_clock).strip()
    if ":" in s:
        mm, ss = s.split(":")
        return int(mm) * 60 + float(ss)
    try:
        return float(s)
    except ValueError:
        return 0.0


def minutes_elapsed_from_status(status: dict, league: str) -> float:
    t = LEAGUE_TIMING[league]
    period = int(status.get("period", 1) or 1)
    clock_left_s = _clock_to_seconds(status.get("displayClock", "0:00"))
    period_min = t["period_minutes"]
    completed = min(period - 1, t["n_periods"]) * period_min
    used_this_period = period_min - clock_left_s / 60.0
    elapsed = completed + used_this_period
    return float(min(max(elapsed, 0.0), t["game_length"] - 1e-6))


def parse_event(event: dict, league: str) -> dict:
    comp = event["competitions"][0]
    competitors = comp["competitors"]
    home = next(c for c in competitors if c["homeAway"] == "home")
    away = next(c for c in competitors if c["homeAway"] == "away")
    status = comp.get("status", {}) or event.get("status", {})
    stype = status.get("type", {}) or {}
    return {
        "event_id": event.get("id"),
        "league": league,
        "home_team": home["team"].get("abbreviation") or home["team"].get("displayName"),
        "away_team": away["team"].get("abbreviation") or away["team"].get("displayName"),
        "home_aliases": team_aliases(home["team"]),
        "away_aliases": team_aliases(away["team"]),
        "home_score": int(home.get("score", 0) or 0),
        "away_score": int(away.get("score", 0) or 0),
        "state": stype.get("state"),
        "period": status.get("period"),
        "display_clock": status.get("displayClock"),
        "minutes_elapsed": minutes_elapsed_from_status(status, league),
        "short_detail": stype.get("shortDetail"),
    }


def list_games(league: str = "nfl") -> list:
    league = league.lower()
    resp = requests.get(SCOREBOARDS[league], timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return [parse_event(ev, league) for ev in data.get("events", [])]


def find_game(league: str, team: str) -> dict | None:
    t = _norm(team)
    for g in list_games(league):
        if t in g["home_aliases"] or t in g["away_aliases"] \
           or t in (_norm(g["home_team"]), _norm(g["away_team"])):
            return g
    return None


if __name__ == "__main__":
    import sys
    lg = sys.argv[1] if len(sys.argv) > 1 else "nfl"
    games = list_games(lg)
    if not games:
        print(f"No {lg.upper()} games on the scoreboard right now.")
    for g in games:
        print(f"{g['away_team']:>5} @ {g['home_team']:<5}  "
              f"{g['away_score']}-{g['home_score']}  "
              f"[{g['state']}] {g['short_detail']}  "
              f"-> minutes_elapsed={g['minutes_elapsed']:.1f}")
