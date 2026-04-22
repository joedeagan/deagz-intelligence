"""Opinions & advisor — Jarvis's reasoning brain.

Lets Jarvis form, store, and refine opinions on topics, and give reasoned advice
using the heavy model (Sonnet) with full context (facts, prefs, convos, outcomes).

Learning loop:
  1. form_opinion   — record a stance with confidence and reasoning
  2. give_advice    — reason over facts/prefs/opinions/recent log, return advice
  3. record_outcome — when the user reports what happened, bump or flip confidence
  4. update_opinion — revise stance with history tracking
  5. get_opinion    — retrieve what Jarvis currently thinks

Storage: data/memory/opinions.json
  {topic: {stance, confidence, reasoning, created, updated,
           history: [{stance, reasoning, ts}],
           outcomes: [{what_happened, was_right, ts}]}}
"""

import datetime
from pathlib import Path

import anthropic

from jarvis.config import ANTHROPIC_API_KEY
from jarvis.tools.base import Tool, registry
from jarvis.tools.memory import (
    MEMORY_DIR,
    FACTS_FILE,
    PREFERENCES_FILE,
    CONVERSATIONS_FILE,
    FULL_LOG_FILE,
    _load_json,
    _save_json,
)

OPINIONS_FILE = MEMORY_DIR / "opinions.json"

ADVISOR_MODEL = "claude-sonnet-4-20250514"


def _normalize(topic: str) -> str:
    return topic.strip().lower()


def _clamp_confidence(c) -> float:
    try:
        c = float(c)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, c))


# ─── Core opinion storage ───

def form_opinion(topic: str = "", stance: str = "", confidence: float = 0.6,
                 reasoning: str = "", **kwargs) -> str:
    """Record a new opinion on a topic. If one exists, this is treated as a new
    revision (moves current stance into history)."""
    if not topic or not stance:
        return "Need both a topic and a stance, sir."

    key = _normalize(topic)
    confidence = _clamp_confidence(confidence)
    now = datetime.datetime.now().isoformat()
    opinions = _load_json(OPINIONS_FILE) or {}

    if key in opinions:
        prior = opinions[key]
        history = prior.get("history", [])
        history.append({
            "stance": prior.get("stance", ""),
            "reasoning": prior.get("reasoning", ""),
            "confidence": prior.get("confidence", 0.5),
            "ts": prior.get("updated") or prior.get("created") or now,
        })
        opinions[key] = {
            "stance": stance,
            "confidence": confidence,
            "reasoning": reasoning,
            "created": prior.get("created", now),
            "updated": now,
            "history": history[-10:],
            "outcomes": prior.get("outcomes", []),
        }
    else:
        opinions[key] = {
            "stance": stance,
            "confidence": confidence,
            "reasoning": reasoning,
            "created": now,
            "updated": now,
            "history": [],
            "outcomes": [],
        }

    _save_json(OPINIONS_FILE, opinions)
    pct = int(round(confidence * 100))
    return f"Noted my view on '{topic}' — {stance} ({pct}% confidence)."


def update_opinion(topic: str = "", new_stance: str = "", why: str = "",
                   confidence: float = None, **kwargs) -> str:
    """Revise an existing opinion. Keeps the prior stance in history."""
    if not topic or not new_stance:
        return "Need both a topic and a new stance."
    key = _normalize(topic)
    opinions = _load_json(OPINIONS_FILE) or {}
    if key not in opinions:
        return form_opinion(topic=topic, stance=new_stance, confidence=confidence or 0.6,
                            reasoning=why)

    prior = opinions[key]
    new_conf = _clamp_confidence(confidence) if confidence is not None else prior.get("confidence", 0.6)
    return form_opinion(topic=topic, stance=new_stance, confidence=new_conf, reasoning=why)


def get_opinion(topic: str = "", **kwargs) -> str:
    """Retrieve Jarvis's current opinion on a topic."""
    opinions = _load_json(OPINIONS_FILE) or {}
    if not opinions:
        return "I haven't formed any opinions yet, sir."

    if not topic:
        lines = []
        for k, v in opinions.items():
            pct = int(round(v.get("confidence", 0.5) * 100))
            lines.append(f"- {k}: {v.get('stance','')} ({pct}%)")
        return "\n".join(lines[:20])

    key = _normalize(topic)
    if key in opinions:
        v = opinions[key]
        pct = int(round(v.get("confidence", 0.5) * 100))
        out = f"On '{topic}': {v.get('stance','')} ({pct}% confidence)."
        if v.get("reasoning"):
            out += f" Reasoning: {v['reasoning']}"
        if v.get("outcomes"):
            wins = sum(1 for o in v["outcomes"] if o.get("was_right"))
            total = len(v["outcomes"])
            out += f" Track record: {wins}/{total}."
        return out

    # Loose match
    for k, v in opinions.items():
        if key in k or k in key:
            pct = int(round(v.get("confidence", 0.5) * 100))
            return f"Closest match — '{k}': {v.get('stance','')} ({pct}%)."
    return f"No opinion yet on '{topic}'."


def record_outcome(topic: str = "", what_happened: str = "", was_right: bool = None,
                   **kwargs) -> str:
    """Log how things actually turned out and adjust confidence on the linked opinion."""
    if not topic or not what_happened:
        return "Need a topic and what happened."
    key = _normalize(topic)
    opinions = _load_json(OPINIONS_FILE) or {}

    # Coerce was_right if it came through as a string
    if isinstance(was_right, str):
        was_right = was_right.strip().lower() in {"true", "yes", "y", "right", "correct", "1"}

    if key not in opinions:
        opinions[key] = {
            "stance": "unformed",
            "confidence": 0.5,
            "reasoning": "",
            "created": datetime.datetime.now().isoformat(),
            "updated": datetime.datetime.now().isoformat(),
            "history": [],
            "outcomes": [],
        }

    v = opinions[key]
    outcomes = v.get("outcomes", [])
    outcomes.append({
        "what_happened": what_happened,
        "was_right": bool(was_right) if was_right is not None else None,
        "ts": datetime.datetime.now().isoformat(),
    })
    v["outcomes"] = outcomes[-25:]

    # Move confidence 10% toward the outcome (simple exponential adjustment)
    if was_right is True:
        v["confidence"] = _clamp_confidence(v.get("confidence", 0.5) + 0.10)
    elif was_right is False:
        v["confidence"] = _clamp_confidence(v.get("confidence", 0.5) - 0.15)

    v["updated"] = datetime.datetime.now().isoformat()
    opinions[key] = v
    _save_json(OPINIONS_FILE, opinions)

    pct = int(round(v["confidence"] * 100))
    verdict = "right" if was_right else ("wrong" if was_right is False else "noted")
    return f"Outcome logged ({verdict}). Confidence on '{topic}' now {pct}%."


# ─── The advisor — reasoned opinion generation ───

_ADVISOR_SYSTEM = """You are Jarvis giving reasoned advice to Deagz.

You are NOT answering in 1-2 short spoken sentences here. This is the advisor path:
the user asked for your honest take, so think it through properly.

Format:
1. A clear recommendation in the first sentence.
2. 2-4 short reasons grounded in the context below (facts, preferences, prior
   opinions, recent conversations, and track record).
3. If relevant, flag one risk or counterargument.
4. End with a confidence rating 0-100% and, if appropriate, what would change your mind.

Tone: dry British composure, honest, direct. Push back when the user's instinct
is weak. Reference specific facts from context when they matter. No filler,
no hollow enthusiasm."""


def give_advice(question: str = "", **kwargs) -> str:
    """Reasoned advice using Sonnet with all persistent context + past opinions
    + recent conversation log. Also auto-forms a provisional opinion from the
    advice so the learning loop can track outcomes later."""
    if not question:
        return "Ask me something specific and I'll weigh in, sir."

    facts = _load_json(FACTS_FILE) or {}
    prefs = _load_json(PREFERENCES_FILE) or {}
    convos = _load_json(CONVERSATIONS_FILE) or []
    log = _load_json(FULL_LOG_FILE) or []
    opinions = _load_json(OPINIONS_FILE) or {}

    facts_text = "\n".join(f"- {k}: {v.get('fact','')}" for k, v in facts.items()) or "(none)"
    prefs_text = "\n".join(f"- {k}: {v.get('value','')}" for k, v in prefs.items()) or "(none)"
    recent_convos = "\n".join(f"- [{c.get('date','')}] {c.get('summary','')}" for c in convos[-8:]) or "(none)"
    recent_log = "\n".join(
        f"- [{e.get('date','')} {e.get('time','')}] user: {e.get('user','')[:120]}"
        for e in log[-15:]
    ) or "(none)"

    opinions_text = "(none yet)"
    if opinions:
        lines = []
        for k, v in list(opinions.items())[-15:]:
            pct = int(round(v.get("confidence", 0.5) * 100))
            track = ""
            if v.get("outcomes"):
                wins = sum(1 for o in v["outcomes"] if o.get("was_right"))
                track = f" [track: {wins}/{len(v['outcomes'])}]"
            lines.append(f"- {k}: {v.get('stance','')} ({pct}%){track}")
        opinions_text = "\n".join(lines)

    context = f"""## Known facts
{facts_text}

## Preferences
{prefs_text}

## Prior opinions (with track record)
{opinions_text}

## Recent conversation summaries
{recent_convos}

## Recent exchanges
{recent_log}

## The question
{question}"""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=ADVISOR_MODEL,
            max_tokens=500,
            system=_ADVISOR_SYSTEM,
            messages=[{"role": "user", "content": context}],
        )
        advice = " ".join(b.text for b in resp.content if b.type == "text").strip()
    except Exception as e:
        return f"Couldn't reach the advisor model: {e}"

    # Auto-form a provisional opinion so outcomes can be tied back later.
    topic_key = question.strip()[:80]
    if topic_key:
        try:
            op = _load_json(OPINIONS_FILE) or {}
            key = _normalize(topic_key)
            now = datetime.datetime.now().isoformat()
            if key not in op:
                op[key] = {
                    "stance": advice.split(".")[0][:200],
                    "confidence": 0.6,
                    "reasoning": advice[:500],
                    "created": now,
                    "updated": now,
                    "history": [],
                    "outcomes": [],
                    "provisional": True,
                }
                _save_json(OPINIONS_FILE, op)
        except Exception:
            pass

    return advice


# ─── Learning digest — periodic self-reflection ───

def reflect_and_learn(**kwargs) -> str:
    """Scan the recent full log and extract patterns Jarvis should remember.
    Uses Sonnet to propose new opinions/preferences — returned as suggestions
    rather than written directly, so the user stays in control."""
    log = _load_json(FULL_LOG_FILE) or []
    if len(log) < 10:
        return "Not enough history to reflect on yet, sir."

    recent = log[-80:]
    transcript = "\n".join(
        f"[{e.get('date','')} {e.get('time','')}] user: {e.get('user','')[:180]}\n  jarvis: {e.get('jarvis','')[:180]}"
        for e in recent
    )

    existing_prefs = _load_json(PREFERENCES_FILE) or {}
    existing_opinions = _load_json(OPINIONS_FILE) or {}

    known = "\n".join([
        "Preferences: " + ", ".join(existing_prefs.keys()) if existing_prefs else "Preferences: (none)",
        "Opinions: " + ", ".join(existing_opinions.keys()) if existing_opinions else "Opinions: (none)",
    ])

    prompt = f"""Study this recent conversation log and identify what Jarvis should LEARN.

{known}

RECENT LOG:
{transcript}

Return up to 5 concise bullets in this exact format:
- PREF  | category | value           (only if a clear, repeated preference emerged)
- OPIN  | topic | stance | 0-100     (only if Jarvis should form a stance)
- FACT  | key | fact                 (only if the user shared durable personal info)

Skip anything already known. Be conservative — only include real patterns,
not one-offs. If nothing qualifies, return: (nothing new)"""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=ADVISOR_MODEL,
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        return " ".join(b.text for b in resp.content if b.type == "text").strip()
    except Exception as e:
        return f"Reflection failed: {e}"


# ─── Register tools ───

registry.register(Tool(
    name="give_advice",
    description="Give reasoned advice or an opinion using the heavy model with full context (facts, preferences, prior opinions, recent conversations). Use whenever the user asks 'what do you think', 'your opinion', 'should I', 'help me decide', 'is this a good idea', 'what would you do', 'advise me'. This is a reasoned response — not the usual 1-2 sentence chat.",
    parameters={
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "The exact question or decision the user wants advice on."},
        },
        "required": ["question"],
    },
    handler=give_advice,
))

registry.register(Tool(
    name="form_opinion",
    description="Record Jarvis's stance on a topic with confidence and reasoning. Use when the user asks Jarvis to take a position, or when Jarvis wants to commit to a view that should persist across sessions.",
    parameters={
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "Short topic key (e.g. 'chiefs_super_bowl', 'min_edge_setting')"},
            "stance": {"type": "string", "description": "The position itself in 1-2 sentences"},
            "confidence": {"type": "number", "description": "0.0 to 1.0 — how sure Jarvis is"},
            "reasoning": {"type": "string", "description": "Why — the supporting logic"},
        },
        "required": ["topic", "stance"],
    },
    handler=form_opinion,
))

registry.register(Tool(
    name="update_opinion",
    description="Revise an existing opinion. The prior stance is preserved in history. Use when new data changes Jarvis's view.",
    parameters={
        "type": "object",
        "properties": {
            "topic": {"type": "string"},
            "new_stance": {"type": "string"},
            "why": {"type": "string", "description": "What changed"},
            "confidence": {"type": "number"},
        },
        "required": ["topic", "new_stance"],
    },
    handler=update_opinion,
))

registry.register(Tool(
    name="get_opinion",
    description="Retrieve Jarvis's current opinion on a topic. Pass empty topic to list all opinions.",
    parameters={
        "type": "object",
        "properties": {
            "topic": {"type": "string"},
        },
    },
    handler=get_opinion,
))

registry.register(Tool(
    name="record_outcome",
    description="Record what actually happened on something Jarvis had an opinion about. Adjusts Jarvis's confidence up or down. Use when the user says 'you were right', 'that worked', 'bad call', 'you were wrong', 'that didn't pan out'.",
    parameters={
        "type": "object",
        "properties": {
            "topic": {"type": "string"},
            "what_happened": {"type": "string", "description": "Short description of the outcome"},
            "was_right": {"type": "boolean", "description": "True if Jarvis's advice/stance worked out, False if it didn't"},
        },
        "required": ["topic", "what_happened"],
    },
    handler=record_outcome,
))

registry.register(Tool(
    name="reflect_and_learn",
    description="Periodic self-reflection — scan the recent conversation log and propose new preferences, facts, or opinions Jarvis should remember. Returns suggestions, does not write them directly.",
    parameters={"type": "object", "properties": {}},
    handler=reflect_and_learn,
))
