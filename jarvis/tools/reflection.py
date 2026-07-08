"""Weekly reflection - the relationship that ages.

Every Sunday morning, Jarvis re-reads the week (every exchange, every fact)
and writes himself an updated portrait of Joe: who he is, what he keeps
coming back to, the running jokes worth reusing, what changed. The latest
portrait rides into EVERY conversation via the brain's persistent context -
so his understanding compounds week over week instead of resetting.

Knob: REFLECT_MODEL (default sonnet - this is once a week, use the good one).
"""

import datetime
import json
import os
import re
import threading
import time
from pathlib import Path

REFLECTIONS_FILE = Path(__file__).parent.parent.parent / "data" / "memory" / "reflections.json"

_running = False


def _load() -> list:
    try:
        return json.loads(REFLECTIONS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(items: list):
    REFLECTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    REFLECTIONS_FILE.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")


def latest_portrait() -> str:
    items = _load()
    if not items:
        return ""
    last = items[-1]
    out = last.get("portrait", "")
    jokes = last.get("jokes") or []
    if jokes:
        out += "\nRunning jokes/references worth reusing naturally: " + "; ".join(jokes[:6])
    return out.strip()


def _reflect():
    from jarvis.tools.memory import _load_json, FULL_LOG_FILE, FACTS_FILE

    cutoff = (datetime.datetime.now() - datetime.timedelta(days=7)).isoformat()
    week = [e for e in _load_json(FULL_LOG_FILE) if e.get("ts", "") >= cutoff]
    if len(week) < 5:
        return  # too quiet a week to learn from
    convo = "\n".join(
        f"[{e.get('date')}] Joe: {e.get('user', '')[:160]} | Jarvis: {e.get('jarvis', '')[:120]}"
        for e in week[-250:]
    )
    facts = _load_json(FACTS_FILE)
    fact_text = "; ".join(f"{k}: {v.get('fact', '')}" for k, v in list(facts.items())[:30])
    previous = latest_portrait()

    import anthropic
    from jarvis.config import ANTHROPIC_API_KEY
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model=os.getenv("REFLECT_MODEL", "claude-sonnet-4-20250514"),
        max_tokens=700,
        system=(
            "You are JARVIS reflecting on a week with Joe, the teenager you live with "
            "(a wall display in his bedroom in Akron). From the week's conversations, "
            "write your private notes: an updated PORTRAIT of who Joe is (voice, humor, "
            "what he cares about, moods, what he keeps returning to, how he likes being "
            "spoken to), plus running JOKES/references from this week worth calling back "
            "naturally, plus THEMES (ongoing threads to remember). Build on the previous "
            "portrait - evolve it, don't restart it. Be specific and warm, never clinical. "
            'Reply ONLY with JSON: {"portrait": "...", "jokes": ["..."], "themes": ["..."]}'
        ),
        messages=[{
            "role": "user",
            "content": (("PREVIOUS PORTRAIT:\n" + previous + "\n\n") if previous else "")
            + "KNOWN FACTS:\n" + fact_text + "\n\nTHIS WEEK:\n" + convo,
        }],
    )
    raw = " ".join(b.text for b in msg.content if b.type == "text")
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return
    data = json.loads(m.group(0))
    items = _load()
    items.append({
        "week_of": datetime.date.today().isoformat(),
        "portrait": data.get("portrait", ""),
        "jokes": data.get("jokes", []),
        "themes": data.get("themes", []),
    })
    _save(items[-12:])  # keep a quarter's worth
    print(f"[reflection] weekly portrait updated ({len(items)} total)")


def _loop():
    while True:
        try:
            now = datetime.datetime.now()
            items = _load()
            last_week = items[-1].get("week_of", "") if items else ""
            if now.weekday() == 6 and now.hour == 8 and last_week != datetime.date.today().isoformat():
                _reflect()
        except Exception as e:
            print(f"[reflection] failed: {e}")
        time.sleep(1800)  # check twice an hour


def start_reflection():
    global _running
    if _running:
        return
    _running = True
    threading.Thread(target=_loop, daemon=True, name="jarvis-reflection").start()
