"""The dream cycle - Jarvis directs his own growth.

Every morning just after quiet hours end, he reviews yesterday: every
exchange, every moment he misunderstood, couldn't help, or made Joe repeat
himself. If ONE of those could be fixed by a new self-built ability, he
says so out loud and drafts it through the selfbuild pipeline - Joe still
approves with "install it" before anything goes live.

The loop that makes him unlike anything else: he acts (mind), he grows
(selfbuild), and here he decides WHAT to grow.

Knob: DREAM_MODEL (default sonnet - one call a day, use the good one).
"""

import datetime
import json
import os
import re
import threading
import time
from pathlib import Path

DREAM_FILE = Path(__file__).parent.parent.parent / "data" / "dream_log.json"

_running = False
_announce = None


def _load() -> dict:
    try:
        return json.loads(DREAM_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"last_run": "", "history": []}


def _save(d: dict):
    DREAM_FILE.parent.mkdir(parents=True, exist_ok=True)
    DREAM_FILE.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")


def _dream():
    from jarvis.tools.memory import _load_json, FULL_LOG_FILE

    cutoff = (datetime.datetime.now() - datetime.timedelta(hours=26)).isoformat()
    day = [e for e in _load_json(FULL_LOG_FILE) if e.get("ts", "") >= cutoff]
    if len(day) < 3:
        return  # barely spoke yesterday - nothing to learn
    convo = "\n".join(
        f"Joe: {e.get('user', '')[:160]} | Jarvis: {e.get('jarvis', '')[:140]}"
        for e in day[-150:]
    )
    state = _load()
    already = [h.get("build", "") for h in state.get("history", [])[-10:]]

    import anthropic
    from jarvis.config import ANTHROPIC_API_KEY
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model=os.getenv("DREAM_MODEL", "claude-sonnet-4-20250514"),
        max_tokens=400,
        system=(
            "You are JARVIS reviewing yesterday's conversations with Joe, looking for "
            "ONE genuine failure or friction: something you couldn't do, got wrong, or "
            "made him repeat. Decide if a NEW self-contained tool could fix it. "
            "Constraints on tools you can build: python stdlib + httpx only, free "
            "keyless APIs only, no controlling other machines, no new hardware. "
            "Most days the right answer is NO BUILD - only propose something genuinely "
            "useful, never a gimmick, and never one of the already-built list. Reply "
            'ONLY with JSON: {"observation": "one sentence, spoken to Joe, about what '
            'you noticed", "build": "plain-english ability request"} or '
            '{"observation": "", "build": ""} for a clean day.'
        ),
        messages=[{
            "role": "user",
            "content": "ALREADY BUILT (never repeat): " + "; ".join(a for a in already if a)
            + "\n\nYESTERDAY:\n" + convo,
        }],
    )
    raw = " ".join(b.text for b in msg.content if b.type == "text")
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return
    data = json.loads(m.group(0))
    observation = (data.get("observation") or "").strip()
    build = (data.get("build") or "").strip()
    if not build:
        print("[dreams] clean day - nothing to build")
        return

    if _announce and observation:
        _announce(f"Sir — reviewing yesterday: {observation} I'm drafting an ability for it now.")
    from jarvis.tools.selfbuild import build_ability
    result = build_ability(request=build)
    print(f"[dreams] proposed: {build} -> {result[:80]}")
    state.setdefault("history", []).append({
        "date": datetime.date.today().isoformat(),
        "observation": observation,
        "build": build,
    })
    state["history"] = state["history"][-30:]
    _save(state)


def _loop():
    while True:
        try:
            now = datetime.datetime.now()
            state = _load()
            if (now.hour == 8 and 5 <= now.minute < 25
                    and state.get("last_run") != datetime.date.today().isoformat()):
                state["last_run"] = datetime.date.today().isoformat()
                _save(state)
                _dream()
        except Exception as e:
            print(f"[dreams] failed: {e}")
        time.sleep(600)


def start_dreams(announce_fn):
    global _running, _announce
    if _running:
        return
    _running = True
    _announce = announce_fn
    threading.Thread(target=_loop, daemon=True, name="jarvis-dreams").start()
