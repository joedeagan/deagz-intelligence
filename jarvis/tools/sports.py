"""Sports desk - Cleveland team results and schedules via ESPN's public API.

"Did the Cavs win?" / "When do the Browns play?" / "How are the Guardians doing?"
No API key needed. Game times come from ESPN's shortDetail strings, which are
already Eastern - never convert timezones on Windows (see the v-history TZ pitfall).
"""

import datetime

import httpx

from jarvis.tools.base import Tool, registry

# nickname -> (sport, league, team slug/id, spoken name)
TEAMS = {
    "cavs": ("basketball", "nba", "cle", "Cavaliers"),
    "cavaliers": ("basketball", "nba", "cle", "Cavaliers"),
    "browns": ("football", "nfl", "cle", "Browns"),
    "guardians": ("baseball", "mlb", "cle", "Guardians"),
    "indians": ("baseball", "mlb", "cle", "Guardians"),
    "buckeyes": ("football", "college-football", "194", "Buckeyes"),
    "ohio state": ("football", "college-football", "194", "Buckeyes"),
    "monsters": ("hockey", "nhl", "cbj", "Blue Jackets"),  # closest NHL: Columbus
    "blue jackets": ("hockey", "nhl", "cbj", "Blue Jackets"),
}

ESPN = "https://site.api.espn.com/apis/site/v2/sports"


def _resolve(team: str):
    t = (team or "").lower().strip()
    for junk in ("the ", "cleveland ", "my "):
        if t.startswith(junk):
            t = t[len(junk):]
    for key, val in TEAMS.items():
        if key in t or t in key:
            return val
    return None


def _day_phrase(iso_date: str) -> str:
    """'yesterday' / 'on Saturday' from an ESPN UTC date, close enough for speech."""
    try:
        game = datetime.datetime.strptime(iso_date[:10], "%Y-%m-%d").date()
        today = datetime.date.today()
        delta = (today - game).days
        if delta <= 0:
            return "today"
        if delta == 1:
            return "yesterday"
        if delta < 7:
            return "on " + game.strftime("%A")
        return "on " + game.strftime("%B %d")
    except Exception:
        return "recently"


def _event_line(event: dict, spoken: str) -> str:
    """One spoken sentence for a completed/live/upcoming ESPN event."""
    comp = (event.get("competitions") or [{}])[0]
    status = (comp.get("status") or event.get("status") or {}).get("type", {})
    state = status.get("state", "")
    competitors = comp.get("competitors", [])
    us = them = None
    for c in competitors:
        name = (c.get("team") or {}).get("displayName", "")
        if spoken.lower() in name.lower() or name.lower().endswith(spoken.lower()):
            us = c
        else:
            them = c
    if us is None or them is None:  # can't tell sides - fall back to ESPN's words
        return event.get("name", "") + " - " + status.get("shortDetail", "")

    def score(c):
        s = c.get("score")
        if isinstance(s, dict):
            s = s.get("displayValue", "")
        return str(s or "")

    tm = them.get("team") or {}
    them_name = tm.get("shortDisplayName") or (tm.get("displayName", "the opponent")).split()[-1]
    if state == "post":
        won = us.get("winner")
        if won is None:  # team endpoint sometimes omits winner - compare scores
            try:
                won = float(score(us)) > float(score(them))
            except Exception:
                won = None
        verdict = "beat" if won else "lost to"
        return (f"They {verdict} the {them_name} "
                f"{score(us)} to {score(them)} {_day_phrase(event.get('date', ''))}.")
    if state == "in":
        return (f"They're playing the {them_name} right now - "
                f"{score(us)} to {score(them)}, {status.get('shortDetail', 'in progress')}.")
    # upcoming - ESPN's shortDetail is already Eastern ("7/7 - 7:40 PM EDT")
    where = "at home" if us.get("homeAway") == "home" else "away"
    when = status.get("shortDetail", "") or event.get("date", "")
    return f"They play the {them_name} {where}, {when}."


def team_report(team: str = "", **kwargs) -> str:
    """Record + last result + next game for a team, ready to be spoken."""
    resolved = _resolve(team)
    if not resolved:
        known = ", ".join(sorted({v[3] for v in TEAMS.values()}))
        return f"I only track {known} directly - for other teams, search the web."
    sport, league, slug, spoken = resolved

    parts = [f"The {spoken}"]
    try:
        r = httpx.get(f"{ESPN}/{sport}/{league}/teams/{slug}", timeout=8)
        t = r.json().get("team", {})
        rec = (t.get("record", {}).get("items") or [{}])[0].get("summary", "")
        if rec:
            parts[0] += f" are {rec}"
        next_events = t.get("nextEvent", [])
    except Exception:
        return "ESPN isn't answering right now, sir."

    # last completed + first upcoming game from the schedule
    last_line = ""
    sched_next = ""
    try:
        r = httpx.get(f"{ESPN}/{sport}/{league}/teams/{slug}/schedule", timeout=8)
        events = r.json().get("events", [])
        done, upcoming = [], []
        for e in events:
            st = (e.get("competitions") or [{}])[0].get("status", {}).get("type", {})
            (done if st.get("completed") else upcoming).append(e)
        if done:
            last_line = _event_line(done[-1], spoken)
        if upcoming:
            sched_next = "Next up: " + _event_line(upcoming[0], spoken)
    except Exception:
        pass

    # next / live game from the team endpoint
    next_line = ""
    for e in next_events[:1]:
        comp = (e.get("competitions") or [{}])[0]
        state = comp.get("status", {}).get("type", {}).get("state", "")
        line = _event_line(e, spoken)
        if state == "post":
            if not last_line:
                last_line = line  # offseason: nextEvent IS the last game
        else:
            next_line = ("Live: " if state == "in" else "Next up: ") + line

    if not next_line:
        next_line = sched_next  # offseason: nextEvent is empty but the schedule is out
    out = parts[0] + "." if len(parts[0]) > len(f"The {spoken}") else ""
    pieces = [p for p in (out, last_line, next_line) if p]
    if not pieces:
        pieces.append(f"The {spoken} have nothing on the schedule right now - likely the offseason.")
    return " ".join(pieces)


registry.register(Tool(
    name="team_report",
    description=(
        "Sports desk: record, latest result, and next game for the user's teams - "
        "Cavaliers, Browns, Guardians, Ohio State Buckeyes, Blue Jackets. "
        "Use for 'did the Cavs win', 'when do the Browns play', 'Guardians score', "
        "'how are the Guardians doing', 'who do the Browns play next'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "team": {"type": "string", "description": "Team name or nickname (e.g. 'cavs', 'browns', 'guardians')"},
        },
        "required": ["team"],
    },
    handler=team_report,
))
