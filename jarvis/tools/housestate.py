"""Live house state - what the TV and desktop PC are doing right now.

The home agent (laptop) reports the TV's foreground app every ~20s; the PC
listener (desktop) reports its foreground window every ~15s. Both POST to
/api/housestate and land here. The chat context and the mind's hourly
snapshot read it back, so "is my PC on?" and "what's on the TV?" get real
answers - and staleness is honest knowledge too (no report = off/asleep).
"""

import time

_state: dict = {}
FRESH_SECONDS = 90


def report(device: str, info: dict):
    _state[device] = {"info": info or {}, "ts": time.time()}


def snapshot() -> str:
    """One honest line about the house, for prompts. Empty string = nothing known."""
    now = time.time()
    lines = []

    tv = _state.get("tv")
    if tv:
        age = now - tv["ts"]
        info = tv["info"]
        if age < FRESH_SECONDS:
            if info.get("power") == "off" or not info.get("app"):
                lines.append("TV: off")
            else:
                lines.append(f"TV is on, showing the {info['app']} app")
        else:
            lines.append(f"TV: no report for {int(age // 60)}m (agent may be down)")

    pc = _state.get("pc")
    if pc:
        age = now - pc["ts"]
        info = pc["info"]
        if age < FRESH_SECONDS:
            win = (info.get("window") or "").strip()
            lines.append("Desktop PC is on" + (f', foreground window: "{win[:60]}"' if win else ""))
        else:
            lines.append(f"Desktop PC: last seen {int(age // 60)}m ago (likely off or asleep)")

    return "; ".join(lines)
