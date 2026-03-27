"""Memory tools — persistent conversation history and preference learning."""

import json
import datetime
from pathlib import Path

from jarvis.tools.base import Tool, registry

MEMORY_DIR = Path(__file__).parent.parent.parent / "data" / "memory"
MEMORY_DIR.mkdir(parents=True, exist_ok=True)

CONVERSATIONS_FILE = MEMORY_DIR / "conversations.json"
PREFERENCES_FILE = MEMORY_DIR / "preferences.json"
FACTS_FILE = MEMORY_DIR / "facts.json"


def _load_json(path: Path) -> list | dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return [] if "conversations" in path.name else {}


def _save_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ─── Conversation Memory ───

def save_conversation(summary: str = "", **kwargs) -> str:
    """Save a conversation summary to memory."""
    convos = _load_json(CONVERSATIONS_FILE)
    entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "date": datetime.datetime.now().strftime("%A, %B %d, %Y at %I:%M %p"),
        "summary": summary,
    }
    convos.append(entry)
    # Keep last 200 conversations
    if len(convos) > 200:
        convos = convos[-200:]
    _save_json(CONVERSATIONS_FILE, convos)
    return f"Saved to memory: {summary}"


def recall_conversations(query: str = "", count: int = 10, **kwargs) -> str:
    """Search past conversations. Returns recent or matching entries."""
    convos = _load_json(CONVERSATIONS_FILE)
    if not convos:
        return "No past conversations stored yet."

    if query:
        q = query.lower()
        matches = [c for c in convos if q in c.get("summary", "").lower()]
        if not matches:
            return f"No conversations found matching '{query}'."
        results = matches[-count:]
    else:
        results = convos[-count:]

    lines = []
    for c in results:
        lines.append(f"[{c['date']}] {c['summary']}")
    return "\n".join(lines)


# ─── Preferences ───

def save_preference(category: str = "", value: str = "", **kwargs) -> str:
    """Save a user preference (music taste, habits, etc.)."""
    prefs = _load_json(PREFERENCES_FILE)
    prefs[category] = {
        "value": value,
        "updated": datetime.datetime.now().isoformat(),
    }
    _save_json(PREFERENCES_FILE, prefs)
    return f"Noted preference: {category} = {value}"


def get_preferences(**kwargs) -> str:
    """Get all stored user preferences."""
    prefs = _load_json(PREFERENCES_FILE)
    if not prefs:
        return "No preferences stored yet."
    lines = []
    for cat, data in prefs.items():
        lines.append(f"- {cat}: {data['value']}")
    return "\n".join(lines)


# ─── Facts / Knowledge ───

def save_fact(key: str = "", fact: str = "", **kwargs) -> str:
    """Save a fact about the user or their world."""
    facts = _load_json(FACTS_FILE)
    facts[key] = {
        "fact": fact,
        "saved": datetime.datetime.now().isoformat(),
    }
    _save_json(FACTS_FILE, facts)
    return f"Remembered: {key} — {fact}"


def get_facts(**kwargs) -> str:
    """Get all stored facts."""
    facts = _load_json(FACTS_FILE)
    if not facts:
        return "No facts stored yet."
    lines = []
    for key, data in facts.items():
        lines.append(f"- {key}: {data['fact']}")
    return "\n".join(lines)


# ─── Register Tools ───

registry.register(Tool(
    name="save_conversation",
    description="Save a conversation summary to long-term memory. Use after meaningful exchanges.",
    parameters={
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "Brief summary of what was discussed (1-2 sentences)",
            }
        },
        "required": ["summary"],
    },
    handler=save_conversation,
))

registry.register(Tool(
    name="recall_conversations",
    description="Search past conversation history. Use when user asks 'what did we talk about' or references past interactions.",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search term to filter conversations (empty for recent)",
            },
            "count": {
                "type": "integer",
                "description": "Number of results to return (default 10)",
            },
        },
    },
    handler=recall_conversations,
))

registry.register(Tool(
    name="save_preference",
    description="Save a user preference. Use when user expresses likes/dislikes or habits.",
    parameters={
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "Category (e.g. 'music', 'food', 'sports_team', 'work_schedule')",
            },
            "value": {
                "type": "string",
                "description": "The preference value",
            },
        },
        "required": ["category", "value"],
    },
    handler=save_preference,
))

registry.register(Tool(
    name="get_preferences",
    description="Retrieve all stored user preferences. Use to personalize responses.",
    parameters={"type": "object", "properties": {}},
    handler=get_preferences,
))

registry.register(Tool(
    name="save_fact",
    description="Save a fact about the user. Use when user shares personal info, schedules, or important details.",
    parameters={
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "Short key (e.g. 'birthday', 'job', 'girlfriend_name')",
            },
            "fact": {
                "type": "string",
                "description": "The fact to remember",
            },
        },
        "required": ["key", "fact"],
    },
    handler=save_fact,
))

registry.register(Tool(
    name="get_facts",
    description="Retrieve all stored facts about the user.",
    parameters={"type": "object", "properties": {}},
    handler=get_facts,
))
