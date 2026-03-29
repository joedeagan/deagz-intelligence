"""Memory tools — persistent conversation history, preference learning, and semantic recall.

Upgraded memory system:
- Saves full conversation detail (not just summaries)
- Semantic search via Claude to find relevant past conversations
- Auto-tags conversations with topics for fast filtering
- Stores everything the user has ever told Jarvis
"""

import json
import datetime
from pathlib import Path

import anthropic

from jarvis.config import ANTHROPIC_API_KEY
from jarvis.tools.base import Tool, registry

MEMORY_DIR = Path(__file__).parent.parent.parent / "data" / "memory"
MEMORY_DIR.mkdir(parents=True, exist_ok=True)

CONVERSATIONS_FILE = MEMORY_DIR / "conversations.json"
PREFERENCES_FILE = MEMORY_DIR / "preferences.json"
FACTS_FILE = MEMORY_DIR / "facts.json"
FULL_LOG_FILE = MEMORY_DIR / "full_log.json"  # Every exchange, not just summaries


def _load_json(path: Path) -> list | dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return [] if "conversations" in path.name or "log" in path.name else {}


def _save_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ─── Full Conversation Log ───

def log_exchange(user_msg: str = "", jarvis_msg: str = "", **kwargs) -> str:
    """Log every user/jarvis exchange to the full log. Called automatically."""
    if not user_msg and not jarvis_msg:
        return "Nothing to log."

    log = _load_json(FULL_LOG_FILE)
    entry = {
        "ts": datetime.datetime.now().isoformat(),
        "time": datetime.datetime.now().strftime("%I:%M %p"),
        "date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "user": user_msg,
        "jarvis": jarvis_msg,
    }
    log.append(entry)

    # Keep last 1000 exchanges
    if len(log) > 1000:
        log = log[-1000:]
    _save_json(FULL_LOG_FILE, log)
    return "Logged."


# ─── Conversation Summaries ───

def save_conversation(summary: str = "", topics: str = "", **kwargs) -> str:
    """Save a conversation summary to memory with optional topic tags."""
    convos = _load_json(CONVERSATIONS_FILE)
    entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "date": datetime.datetime.now().strftime("%A, %B %d, %Y at %I:%M %p"),
        "summary": summary,
        "topics": topics,
    }
    convos.append(entry)
    if len(convos) > 500:
        convos = convos[-500:]
    _save_json(CONVERSATIONS_FILE, convos)
    return f"Saved to memory: {summary}"


def recall_conversations(query: str = "", count: int = 10, **kwargs) -> str:
    """Smart search across all memory — conversations, facts, preferences, and full log."""
    if not query:
        # Return recent conversations
        convos = _load_json(CONVERSATIONS_FILE)
        if not convos:
            return "No past conversations stored yet."
        results = convos[-count:]
        lines = [f"[{c['date']}] {c['summary']}" for c in results]
        return "\n".join(lines)

    # Search everywhere
    q = query.lower()
    results = []

    # Search conversation summaries
    convos = _load_json(CONVERSATIONS_FILE)
    for c in convos:
        text = f"{c.get('summary', '')} {c.get('topics', '')}".lower()
        if q in text or any(word in text for word in q.split()):
            results.append(f"[{c['date']}] {c['summary']}")

    # Search full log for exact phrases
    log = _load_json(FULL_LOG_FILE)
    for entry in log:
        user_text = entry.get("user", "").lower()
        jarvis_text = entry.get("jarvis", "").lower()
        if q in user_text or q in jarvis_text:
            date = entry.get("date", "?")
            time = entry.get("time", "?")
            snippet = entry.get("user", "")[:80]
            results.append(f"[{date} {time}] You said: {snippet}")

    # Search facts
    facts = _load_json(FACTS_FILE)
    for key, data in facts.items():
        if q in key.lower() or q in data.get("fact", "").lower():
            results.append(f"[Fact] {key}: {data['fact']}")

    # Search preferences
    prefs = _load_json(PREFERENCES_FILE)
    for cat, data in prefs.items():
        if q in cat.lower() or q in data.get("value", "").lower():
            results.append(f"[Preference] {cat}: {data['value']}")

    if not results:
        # Fallback: use Claude to semantically search the full log
        return _semantic_search(query, count)

    # Deduplicate and limit
    seen = set()
    unique = []
    for r in results:
        if r not in seen:
            seen.add(r)
            unique.append(r)
    return "\n".join(unique[-count:])


def _semantic_search(query: str, count: int = 5) -> str:
    """Use Claude to find relevant memories when keyword search fails."""
    log = _load_json(FULL_LOG_FILE)
    convos = _load_json(CONVERSATIONS_FILE)
    facts = _load_json(FACTS_FILE)

    if not log and not convos:
        return f"No memories found matching '{query}'."

    # Build compact context (last 100 log entries + all summaries)
    log_text = "\n".join(
        f"[{e.get('date','')} {e.get('time','')}] User: {e.get('user','')[:100]} | Jarvis: {e.get('jarvis','')[:100]}"
        for e in log[-100:]
    )

    summary_text = "\n".join(
        f"[{c.get('date','')}] {c.get('summary','')}"
        for c in convos[-50:]
    )

    facts_text = "\n".join(f"- {k}: {v.get('fact','')}" for k, v in facts.items())

    prompt = f"""Search through these memories and find anything relevant to: "{query}"

CONVERSATION LOG:
{log_text}

SAVED SUMMARIES:
{summary_text}

KNOWN FACTS:
{facts_text}

Return the {count} most relevant memories. Format each as:
[date/time] What was discussed

If nothing is relevant, say "No matching memories found."
Keep it brief — each result should be 1 line."""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text
    except Exception:
        return f"No memories found matching '{query}'."


def remember_everything(query: str = "", **kwargs) -> str:
    """Deep recall — searches ALL memory sources including full conversation log.
    Uses AI to find semantically similar memories even if exact words don't match."""
    return _semantic_search(query, count=8)


# ─── Preferences ───

def save_preference(category: str = "", value: str = "", **kwargs) -> str:
    prefs = _load_json(PREFERENCES_FILE)
    prefs[category] = {
        "value": value,
        "updated": datetime.datetime.now().isoformat(),
    }
    _save_json(PREFERENCES_FILE, prefs)
    return f"Noted preference: {category} = {value}"


def get_preferences(**kwargs) -> str:
    prefs = _load_json(PREFERENCES_FILE)
    if not prefs:
        return "No preferences stored yet."
    return "\n".join(f"- {cat}: {data['value']}" for cat, data in prefs.items())


# ─── Facts ───

def save_fact(key: str = "", fact: str = "", **kwargs) -> str:
    facts = _load_json(FACTS_FILE)
    facts[key] = {
        "fact": fact,
        "saved": datetime.datetime.now().isoformat(),
    }
    _save_json(FACTS_FILE, facts)
    return f"Remembered: {key} — {fact}"


def get_facts(**kwargs) -> str:
    facts = _load_json(FACTS_FILE)
    if not facts:
        return "No facts stored yet."
    return "\n".join(f"- {key}: {data['fact']}" for key, data in facts.items())


# ─── Register Tools ───

registry.register(Tool(
    name="save_conversation",
    description="Save a conversation summary to long-term memory. Use after meaningful exchanges. Include topic tags for better search.",
    parameters={
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "Brief summary of what was discussed"},
            "topics": {"type": "string", "description": "Comma-separated topic tags (e.g. 'kalshi, sports, strategy')"},
        },
        "required": ["summary"],
    },
    handler=save_conversation,
))

registry.register(Tool(
    name="recall_conversations",
    description="Search all of Jarvis's memory — past conversations, facts, preferences, and the full conversation log. Use when user asks 'do you remember', 'what did we talk about', 'when did I tell you about'. Searches semantically if keywords don't match.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search for (empty for recent conversations)"},
            "count": {"type": "integer", "description": "Number of results (default 10)"},
        },
    },
    handler=recall_conversations,
))

registry.register(Tool(
    name="remember_everything",
    description="Deep AI-powered memory search. Finds relevant memories even when exact words don't match. Use for vague recall like 'what was that thing about...', 'remember when we...', 'what did I say about...'.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search for — can be vague or specific"},
        },
        "required": ["query"],
    },
    handler=remember_everything,
))

registry.register(Tool(
    name="save_preference",
    description="Save a user preference. Use when user expresses likes/dislikes or habits.",
    parameters={
        "type": "object",
        "properties": {
            "category": {"type": "string", "description": "Category (e.g. 'music', 'food', 'sports_team')"},
            "value": {"type": "string", "description": "The preference value"},
        },
        "required": ["category", "value"],
    },
    handler=save_preference,
))

registry.register(Tool(
    name="get_preferences",
    description="Retrieve all stored user preferences.",
    parameters={"type": "object", "properties": {}},
    handler=get_preferences,
))

registry.register(Tool(
    name="save_fact",
    description="Save a fact about the user. Use when user shares personal info, schedules, or important details.",
    parameters={
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "Short key (e.g. 'birthday', 'job', 'girlfriend_name')"},
            "fact": {"type": "string", "description": "The fact to remember"},
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
