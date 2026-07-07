"""Jarvis's inner life - the hourly thinking pass.

Once an hour (waking hours only), Jarvis looks at a snapshot of Joe's world -
time, weather, lists, facts, the library, his teams, the Kalshi book - and
DECIDES FOR HIMSELF whether anything is worth saying out loud. No scripted
triggers: one model call playing the role of his inner monologue, whose
default answer is silence.

Guardrails that keep him lovable instead of unbearable:
  - hard cap of DAILY_CAP spoken thoughts per day
  - a log of everything he's said (data/mind_log.json) fed back into the
    prompt so he can never repeat himself
  - quiet hours 10pm-8am, same as the observer
  - anything he says rides the same announcement pipe the intercom uses

Knobs: MIND_EVERY_MIN (default 60), MIND_MODEL (default haiku).
"""

import datetime
import json
import os
import re
import threading
import time
from pathlib import Path

MIND_LOG = Path(__file__).parent.parent.parent / "data" / "mind_log.json"
THINK_EVERY = max(15, int(os.getenv("MIND_EVERY_MIN", "60"))) * 60
DAILY_CAP = 5

_running = False


def _quiet_hours() -> bool:
    h = datetime.datetime.now().hour
    return h >= 22 or h < 8


def _load_log() -> list:
    try:
        return json.loads(MIND_LOG.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_log(log: list):
    try:
        MIND_LOG.parent.mkdir(parents=True, exist_ok=True)
        MIND_LOG.write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _gather() -> str:
    """One text snapshot of everything Jarvis can see. Every source optional."""
    parts = []
    now = datetime.datetime.now()
    parts.append("Time: " + now.strftime("%A, %B %d - %I:%M %p"))
    try:
        from jarvis.tools.system import get_weather
        parts.append("Weather: " + (get_weather() or "").split("\n")[0])
    except Exception:
        pass
    try:
        from jarvis.tools.memory import get_list, get_facts
        parts.append("His lists:\n" + get_list(""))
        parts.append("Known facts:\n" + get_facts())
    except Exception:
        pass
    try:
        from jarvis.tools.sports import team_report
        parts.append("Guardians: " + team_report("guardians"))
    except Exception:
        pass
    try:
        from jarvis.tools.ears import _movie_names
        movies = _movie_names()
        if movies:
            parts.append("Movie library: " + movies)
    except Exception:
        pass
    try:
        import httpx
        from jarvis.config import KALSHI_BOT_URL
        r = httpx.get(f"{KALSHI_BOT_URL}/api/portfolio", timeout=8).json()
        parts.append(f"Kalshi: balance {r.get('balance', '?')}, "
                     f"{len(r.get('positions', []))} open positions")
    except Exception:
        pass
    try:
        from jarvis.tools import housestate
        hs = housestate.snapshot()
        if hs:
            parts.append("The house right now: " + hs)
    except Exception:
        pass
    return "\n\n".join(parts)


SOUL = (
    "You are JARVIS's inner monologue - the quiet hourly moment where you look "
    "around Joe's room and decide whether anything is worth saying out loud "
    "through his wall display. Joe is a teenager in Akron, Ohio; you are his "
    "AI butler. DEFAULT TO SILENCE: an assistant who pipes up every hour is "
    "unbearable, one who speaks once or twice a day with something genuinely "
    "useful or delightful feels alive. Speak ONLY when: something changed that "
    "he would want to know about, OR you can connect two things he would not "
    "have connected himself (a game tonight, rain before an errand on his "
    "list), OR a rare touch of butler warmth is truly earned. NEVER repeat or "
    "rephrase anything from the already-said list. Reply ONLY with JSON: "
    '{"speak": "..."} to talk or {"speak": ""} for silence - silence is the '
    "usual right answer. Max 2 spoken-style sentences, address him as sir."
)


def _think(announce):
    log = _load_log()
    today = datetime.date.today().isoformat()
    if len([e for e in log if e.get("date") == today]) >= DAILY_CAP:
        return
    recent = [e.get("text", "") for e in log[-15:]]

    import anthropic
    from jarvis.config import ANTHROPIC_API_KEY
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model=os.getenv("MIND_MODEL", "claude-haiku-4-5-20251001"),
        max_tokens=200,
        system=SOUL,
        messages=[{
            "role": "user",
            "content": ("SNAPSHOT OF JOE'S WORLD:\n" + _gather()
                        + "\n\nTHINGS YOU ALREADY SAID RECENTLY (never repeat these):\n"
                        + ("\n".join("- " + r for r in recent) if recent else "(nothing yet)")),
        }],
    )
    raw = " ".join(b.text for b in msg.content if b.type == "text")
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return
    try:
        speak = (json.loads(m.group(0)).get("speak") or "").strip()
    except Exception:
        return
    if not speak:
        return  # he considered the room and chose silence
    announce(speak[:300])
    log.append({"date": today, "ts": time.time(), "text": speak})
    _save_log(log[-50:])
    print(f"[mind] spoke: {speak[:80]}")


def _loop(announce):
    time.sleep(180)  # let the house finish waking up before the first thought
    while True:
        try:
            if not _quiet_hours():
                _think(announce)
        except Exception as e:
            print(f"[mind] thinking pass failed: {e}")
        time.sleep(THINK_EVERY)


def start_mind(announce_fn):
    """Start the inner-life thread. announce_fn(text) speaks through the wall."""
    global _running
    if _running:
        return
    _running = True
    threading.Thread(target=_loop, args=(announce_fn,), daemon=True, name="jarvis-mind").start()
