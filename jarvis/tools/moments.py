"""Time capsules - "Jarvis, remember this moment."

He seals the moment: the date, what the room was doing (TV, PC, live game),
and whatever Joe says about it. Later they come back two ways:
  - on demand: "what moments do we have" / "remember that moment from..."
  - unprompted: the mind's hourly snapshot includes today's anniversaries,
    so on the right day he simply brings it up himself.
"""

import datetime
import json
from pathlib import Path

from jarvis.tools.base import Tool, registry

MOMENTS_FILE = Path(__file__).parent.parent.parent / "data" / "memory" / "moments.json"


def _load() -> list:
    try:
        return json.loads(MOMENTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(moments: list):
    MOMENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    MOMENTS_FILE.write_text(json.dumps(moments, indent=2, ensure_ascii=False), encoding="utf-8")


def _scene() -> str:
    bits = []
    try:
        from jarvis.tools.housestate import snapshot
        hs = snapshot()
        if hs:
            bits.append(hs)
    except Exception:
        pass
    try:
        from jarvis.tools.gameday import snapshot as game
        g = game()
        if g.get("team"):
            bits.append(f"{g['team']} {g['us']} - {g['opp']} {g['them']} ({g['detail']})")
    except Exception:
        pass
    return "; ".join(bits)


def capture_moment(note: str = "", **kwargs) -> str:
    now = datetime.datetime.now()
    moments = _load()
    moments.append({
        "ts": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "pretty": now.strftime("%A, %B %d, %Y at %I:%M %p"),
        "note": (note or "").strip()[:300],
        "scene": _scene(),
    })
    _save(moments)
    return ("Sealed. " + now.strftime("%B %d, %Y, %I:%M %p")
            + (" — " + note if note else "") + ". I'll keep this one.")


def recall_moments(query: str = "", **kwargs) -> str:
    moments = _load()
    if not moments:
        return "No sealed moments yet. Say 'remember this moment' when one deserves keeping."
    q = (query or "").lower().strip()
    hits = [m for m in moments if not q or q in m.get("note", "").lower()
            or q in m.get("pretty", "").lower() or q in m.get("scene", "").lower()]
    if not hits:
        return f"No moment matches '{query}'."
    lines = []
    for m in hits[-6:]:
        line = m["pretty"] + (": " + m["note"] if m.get("note") else "")
        if m.get("scene"):
            line += f" (the room: {m['scene']})"
        lines.append(line)
    return "Sealed moments: " + " | ".join(lines)


def anniversary_lines() -> str:
    """Moments whose anniversary is today (yearly, or exactly one month) —
    fed to the mind so he brings them up himself."""
    today = datetime.date.today()
    out = []
    for m in _load():
        try:
            d = datetime.date.fromisoformat(m["date"])
        except Exception:
            continue
        if d == today:
            continue
        yearly = (d.month, d.day) == (today.month, today.day)
        one_month = (d.day == today.day
                     and (today.year * 12 + today.month) - (d.year * 12 + d.month) == 1)
        if yearly or one_month:
            age = "one month ago" if one_month else f"{today.year - d.year} year(s) ago today"
            out.append(f"{age}: {m.get('note') or 'a sealed moment'}"
                       + (f" ({m.get('scene')})" if m.get("scene") else ""))
    return "\n".join(out)


# first run: seal the true founding moment
if not MOMENTS_FILE.exists():
    try:
        _save([{
            "ts": "2026-07-07T19:00:00",
            "date": "2026-07-07",
            "pretty": "Tuesday, July 07, 2026 at 7:00 PM",
            "note": "Joe mounted me on his bedroom wall",
            "scene": "Guardians vs Twins on the TV that evening",
        }])
    except Exception:
        pass


registry.register(Tool(
    name="capture_moment",
    description=("Seal a time capsule of RIGHT NOW - the date and what the room is doing, "
                 "plus the user's note. Use for 'remember this moment', 'time capsule this', "
                 "'never forget this'. Pass whatever the user said about the moment as note."),
    parameters={
        "type": "object",
        "properties": {
            "note": {"type": "string", "description": "What this moment is / why it matters"},
        },
    },
    handler=capture_moment,
))

registry.register(Tool(
    name="recall_moments",
    description=("Recall sealed time-capsule moments. Use for 'what moments do we have', "
                 "'remember that moment when...', 'read my time capsules'."),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Optional filter word/date"},
        },
    },
    handler=recall_moments,
))
