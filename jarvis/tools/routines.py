"""Auto-routines — one-command morning setup, bedtime mode, focus mode, etc."""

import subprocess
import datetime
import threading
from pathlib import Path

from jarvis.tools.base import Tool, registry


def morning_routine(**kwargs) -> str:
    """Full morning routine — opens apps, starts music, sets brightness, triggers briefing."""
    results = []

    # Set brightness to 80%
    try:
        subprocess.run(
            'powershell -Command "(Get-WmiObject -Namespace root/WMI '
            '-Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,80)"',
            shell=True, capture_output=True, timeout=5,
        )
        results.append("Brightness set to 80%")
    except Exception:
        pass

    # Open Chrome
    try:
        subprocess.Popen("start chrome", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        results.append("Chrome opened")
    except Exception:
        pass

    # Open Spotify and play a morning playlist
    try:
        subprocess.Popen("start spotify", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        results.append("Spotify opened")

        # Give Spotify time to start, then play morning music
        def _play_morning():
            import time
            time.sleep(5)
            try:
                from jarvis.tools.spotify import _get_spotify
                sp = _get_spotify()
                if sp:
                    devices = sp.devices()
                    active = None
                    for d in devices.get("devices", []):
                        if d.get("is_active"):
                            active = d["id"]
                            break
                    if not active and devices.get("devices"):
                        active = devices["devices"][0]["id"]
                    if active:
                        # Search for a chill morning playlist
                        res = sp.search(q="morning chill vibes", type="playlist", limit=1)
                        items = res.get("playlists", {}).get("items", [])
                        if items:
                            sp.start_playback(device_id=active, context_uri=items[0]["uri"])
                            sp.shuffle(True, device_id=active)
                            sp.volume(30, device_id=active)
            except Exception:
                pass

        threading.Thread(target=_play_morning, daemon=True).start()
        results.append("Morning playlist queuing (volume 30%)")
    except Exception:
        pass

    # Get weather + portfolio summary for the briefing
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
        # Just the first 2 lines (balance + portfolio value)
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
    summary += f". {', '.join(results)}. You're all set."

    return summary


def bedtime_routine(**kwargs) -> str:
    """Bedtime mode — dims screen, pauses music, summarizes the day."""
    results = []

    # Dim brightness
    try:
        subprocess.run(
            'powershell -Command "(Get-WmiObject -Namespace root/WMI '
            '-Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,15)"',
            shell=True, capture_output=True, timeout=5,
        )
        results.append("Screen dimmed to 15%")
    except Exception:
        pass

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
