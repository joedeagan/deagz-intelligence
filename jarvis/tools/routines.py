"""Auto-routines — one-command morning setup, bedtime mode, focus mode, etc."""

import datetime

from jarvis.tools.base import Tool, registry


# WALL ERA: the brain lives on the always-on laptop now — routines must NEVER
# touch this machine's screen/apps (the old desktop-era version opened Chrome
# and dimmed the LAPTOP whenever "morning" reached the chat brain). The wall
# page runs the real goodnight/good-morning routines; these are the brain-side
# fallbacks if a routine phrase slips through to chat.

def morning_routine(**kwargs) -> str:
    """Morning summary — weather + portfolio, spoken. No machine actions."""
    briefing_parts = []

    try:
        from jarvis.tools.system import get_weather
        weather = get_weather()
        briefing_parts.append(weather.split("\n")[0] if weather else "")
    except Exception:
        pass

    try:
        from jarvis.tools.kalshi import get_portfolio
        portfolio = get_portfolio()
        lines = portfolio.split("\n")[:3]
        briefing_parts.append(" ".join(lines))
    except Exception:
        pass

    now = datetime.datetime.now()
    hour = now.hour
    greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"
    day = now.strftime("%A")

    summary = f"{greeting}, Deagz. It's {day}. "
    summary += ". ".join(b for b in briefing_parts if b)
    return summary


def bedtime_routine(**kwargs) -> str:
    """Bedtime mode — pauses music, says goodnight. No machine actions."""
    results = []

    # Pause music
    try:
        from jarvis.tools.spotify import spotify_control
        spotify_control("pause")
        results.append("Music paused")
    except Exception:
        pass

    return f"Winding down. {'. '.join(results)}. Goodnight, Deagz."


def focus_mode(duration: int = 60, **kwargs) -> str:
    """Focus mode — blocks distractions, sets a timer."""
    results = []

    # Lower volume
    try:
        from jarvis.tools.spotify import _get_spotify
        sp = _get_spotify()
        if sp:
            sp.volume(15)
        results.append("Volume lowered")
    except Exception:
        pass

    # Set a timer
    try:
        from jarvis.tools.system import set_alarm
        set_alarm(minutes=duration, message=f"Focus session complete — {duration} minutes")
        results.append(f"Timer set for {duration} minutes")
    except Exception:
        pass

    return f"Focus mode active. {'. '.join(results)}. I'll stay quiet unless you need me. Timer set for {duration} minutes."


# ─── Register ───

registry.register(Tool(
    name="morning_routine",
    description="Run the full morning routine — opens Chrome + Spotify, plays morning playlist at low volume, sets brightness, gives weather + portfolio briefing. Use for 'good morning', 'start my morning', 'morning routine', 'set me up for the day'.",
    parameters={"type": "object", "properties": {}},
    handler=morning_routine,
))

registry.register(Tool(
    name="bedtime_routine",
    description="Bedtime mode — dims screen, pauses music, winds down. Use for 'goodnight', 'bedtime', 'I'm going to sleep', 'wind down'.",
    parameters={"type": "object", "properties": {}},
    handler=bedtime_routine,
))

registry.register(Tool(
    name="focus_mode",
    description="Focus mode — lowers volume, sets a timer, minimizes distractions. Use for 'focus mode', 'study mode timer', 'I need to focus for an hour', 'do not disturb'.",
    parameters={
        "type": "object",
        "properties": {
            "duration": {"type": "integer", "description": "Focus duration in minutes (default 60)"},
        },
    },
    handler=focus_mode,
))
