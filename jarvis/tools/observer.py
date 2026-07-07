"""The observer - proactive Jarvis. He speaks first.

A background loop on the house brain that watches for things worth saying
and drops them into the wall's announcement queue (the same pipe the family
intercom uses - the wall polls it every 5s and speaks whatever arrives).

Checks, every 5 minutes:
  - new movies indexed by Jellyfin ("Se7en just landed in the library")
  - rain coming in the next couple of hours (Open-Meteo, Akron)
  - Kalshi positions that moved hard (take-profit / take-a-look nudges)

Quiet hours 10pm-8am: announcements WAKE the wall, so the observer holds its
tongue at night and catches up in the morning. Runs on the laptop only -
the cloud fallback brain must never double-speak into the same room.
"""

import datetime
import json
import os
import threading
import time
from pathlib import Path

import httpx

STATE_FILE = Path(__file__).parent.parent.parent / "data" / "observer_state.json"
CHECK_EVERY = 300  # seconds between patrols
AKRON = {"latitude": 41.0814, "longitude": -81.519}

_running = False


def _quiet_hours() -> bool:
    h = datetime.datetime.now().hour
    return h >= 22 or h < 8


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict):
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception:
        pass


def _jellyfin_key() -> str:
    key = os.getenv("JELLYFIN_API_KEY", "")
    if not key:
        try:  # the home agent's config on this same machine already holds the key
            key = json.loads(Path("C:/jarvis-agent/config.json").read_text()).get("api_key", "")
        except Exception:
            key = ""
    return key


# --- checks: each takes the shared state dict, returns spoken lines ---------

def _check_new_movies(state: dict) -> list:
    r = httpx.get(
        "http://127.0.0.1:8096/Items",
        params={"IncludeItemTypes": "Movie", "Recursive": "true", "api_key": _jellyfin_key()},
        timeout=8,
    )
    items = r.json().get("Items", [])
    ids = {i.get("Id"): i.get("Name") for i in items if i.get("Id")}
    known = state.get("movie_ids")
    state["movie_ids"] = sorted(ids)
    if known is None:
        return []  # first patrol = baseline, announce nothing
    fresh = [name for mid, name in ids.items() if mid not in set(known)]
    return [f"Sir, {name} just landed in the library. Say the word and I'll put it on."
            for name in fresh[:3]]


def _check_rain(state: dict) -> list:
    if time.time() - state.get("last_rain_warn", 0) < 6 * 3600:
        return []
    r = httpx.get(
        "https://api.open-meteo.com/v1/forecast",
        params={**AKRON, "hourly": "precipitation_probability",
                "forecast_hours": 3, "timezone": "America/New_York"},
        timeout=8,
    )
    h = r.json().get("hourly", {})
    for t, prob in zip(h.get("time", []), h.get("precipitation_probability", [])):
        if prob is not None and prob >= 60:
            hour = datetime.datetime.fromisoformat(t)
            label = hour.strftime("%I %p").lstrip("0")
            state["last_rain_warn"] = time.time()
            return [f"Sir, heads up - {int(prob)} percent chance of rain around {label}."]
    return []


def _check_kalshi(state: dict) -> list:
    from jarvis.config import KALSHI_BOT_URL
    r = httpx.get(f"{KALSHI_BOT_URL}/api/portfolio", timeout=10)
    lines = []
    warned = state.setdefault("kalshi_warned", {})
    now = time.time()
    for pos in r.json().get("positions", []):
        upnl = pos.get("upnl", 0)
        if not isinstance(upnl, (int, float)) or abs(upnl) < 1.00:
            continue
        name = str(pos.get("ticker") or pos.get("market_ticker") or pos.get("title") or "a position")
        if now - warned.get(name, 0) < 6 * 3600:
            continue  # already mentioned this one recently
        warned[name] = now
        if upnl > 0:
            lines.append(f"Sir, your Kalshi position {name} is up {upnl:.2f} dollars. "
                         "Might be time to take profit.")
        else:
            lines.append(f"Sir, your Kalshi position {name} is down {abs(upnl):.2f} dollars. "
                         "Worth a look.")
    # keep the cooldown map from growing forever
    state["kalshi_warned"] = {k: v for k, v in warned.items() if now - v < 24 * 3600}
    return lines[:2]


# --- the patrol loop ---------------------------------------------------------

def _loop(announce):
    time.sleep(60)  # let the server finish waking up first
    while True:
        try:
            if not _quiet_hours():
                state = _load_state()
                msgs = []
                for check in (_check_new_movies, _check_rain, _check_kalshi):
                    try:
                        msgs += check(state)
                    except Exception:
                        pass  # a dead service just means nothing to say
                _save_state(state)
                for m in msgs[:3]:  # never machine-gun the room
                    announce(m)
                    time.sleep(15)  # the wall speaks one announcement per poll
        except Exception:
            pass
        time.sleep(CHECK_EVERY)


def start_observer(announce_fn):
    """Start the patrol thread. announce_fn(text) drops a line into the wall's queue."""
    global _running
    if _running:
        return
    _running = True
    threading.Thread(target=_loop, args=(announce_fn,), daemon=True, name="jarvis-observer").start()
