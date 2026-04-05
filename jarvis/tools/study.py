"""Study Mode — Jarvis quizzes you with flashcards by voice."""

import json
import random
from pathlib import Path

from jarvis.tools.base import Tool, registry

FLASHCARDS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "flashcards"


def create_flashcard_deck(name: str, cards: str) -> str:
    """Create a flashcard deck. Cards should be formatted as 'question|answer' per line."""
    FLASHCARDS_DIR.mkdir(parents=True, exist_ok=True)

    deck = []
    for line in cards.strip().split("\n"):
        line = line.strip()
        if "|" in line:
            parts = line.split("|", 1)
            deck.append({"q": parts[0].strip(), "a": parts[1].strip()})

    if not deck:
        return "No valid cards found. Format each card as 'question|answer', one per line."

    deck_file = FLASHCARDS_DIR / f"{name.lower().replace(' ', '_')}.json"
    deck_file.write_text(json.dumps({"name": name, "cards": deck, "scores": []}, indent=2))
    return f"Deck '{name}' created with {len(deck)} cards."


def list_decks() -> str:
    """List all available flashcard decks."""
    FLASHCARDS_DIR.mkdir(parents=True, exist_ok=True)

    decks = list(FLASHCARDS_DIR.glob("*.json"))
    if not decks:
        return "No flashcard decks yet. Create one first."

    lines = ["Available decks:"]
    for d in decks:
        data = json.loads(d.read_text())
        name = data.get("name", d.stem)
        count = len(data.get("cards", []))
        scores = data.get("scores", [])
        last_score = f" (last: {scores[-1]}%)" if scores else ""
        lines.append(f"  {name} — {count} cards{last_score}")

    return "\n".join(lines)


def start_quiz(deck_name: str = "", count: int = 5) -> str:
    """Start a quiz session. Returns the first question.
    The quiz state is stored in memory for follow-up questions."""
    FLASHCARDS_DIR.mkdir(parents=True, exist_ok=True)

    # Find the deck
    decks = list(FLASHCARDS_DIR.glob("*.json"))
    if not decks:
        return "No flashcard decks available. Create one first."

    target = None
    for d in decks:
        data = json.loads(d.read_text())
        if deck_name.lower() in data.get("name", "").lower() or deck_name.lower() in d.stem.lower():
            target = d
            break

    if not target:
        # Use most recent deck
        target = max(decks, key=lambda x: x.stat().st_mtime)

    data = json.loads(target.read_text())
    cards = data.get("cards", [])
    if not cards:
        return "This deck has no cards."

    # Pick random cards for the quiz
    quiz_cards = random.sample(cards, min(count, len(cards)))

    # Store quiz state
    state_file = FLASHCARDS_DIR / "_active_quiz.json"
    quiz_state = {
        "deck": data.get("name", target.stem),
        "deck_file": str(target),
        "cards": quiz_cards,
        "current": 0,
        "correct": 0,
        "total": len(quiz_cards),
    }
    state_file.write_text(json.dumps(quiz_state, indent=2))

    card = quiz_cards[0]
    return (
        f"Starting quiz on '{data['name']}' — {len(quiz_cards)} questions. "
        f"Question 1: {card['q']}"
    )


def answer_quiz(answer: str) -> str:
    """Submit an answer to the current quiz question. Jarvis evaluates and moves to next."""
    state_file = FLASHCARDS_DIR / "_active_quiz.json"
    if not state_file.exists():
        return "No active quiz. Start one with 'quiz me'."

    state = json.loads(state_file.read_text())
    idx = state["current"]
    cards = state["cards"]

    if idx >= len(cards):
        return "Quiz is already complete. Start a new one."

    card = cards[idx]
    correct_answer = card["a"].lower().strip()
    user_answer = answer.lower().strip()

    # Flexible matching — check if the core answer is contained
    is_correct = (
        correct_answer in user_answer
        or user_answer in correct_answer
        or _similarity(user_answer, correct_answer) > 0.7
    )

    if is_correct:
        state["correct"] += 1
        feedback = f"Correct! The answer is {card['a']}."
    else:
        feedback = f"Not quite. The answer is {card['a']}."

    # Move to next question
    state["current"] = idx + 1
    state_file.write_text(json.dumps(state, indent=2))

    if state["current"] >= state["total"]:
        # Quiz complete
        score = int((state["correct"] / state["total"]) * 100)

        # Save score to deck
        try:
            deck_data = json.loads(Path(state["deck_file"]).read_text())
            if "scores" not in deck_data:
                deck_data["scores"] = []
            deck_data["scores"].append(score)
            Path(state["deck_file"]).write_text(json.dumps(deck_data, indent=2))
        except Exception:
            pass

        state_file.unlink(missing_ok=True)
        return (
            f"{feedback} "
            f"Quiz complete! You scored {state['correct']} out of {state['total']} — {score}%."
        )

    next_card = cards[state["current"]]
    return (
        f"{feedback} "
        f"Question {state['current'] + 1} of {state['total']}: {next_card['q']}"
    )


def _similarity(a: str, b: str) -> float:
    """Simple word overlap similarity."""
    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a or not words_b:
        return 0.0
    overlap = len(words_a & words_b)
    return overlap / max(len(words_a), len(words_b))


def generate_deck_from_topic(topic: str, count: int = 10) -> str:
    """Use Claude to generate flashcards on any topic."""
    import anthropic
    from jarvis.config import ANTHROPIC_API_KEY

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        messages=[{
            "role": "user",
            "content": (
                f"Generate {count} flashcard question-answer pairs about: {topic}\n"
                f"Format each as: question|answer\n"
                f"One per line. Keep answers concise (1-5 words ideal).\n"
                f"No numbering, no extra text."
            ),
        }],
    )
    cards_text = resp.content[0].text.strip()

    # Create the deck
    return create_flashcard_deck(topic, cards_text)


# Register study tools
registry.register(Tool(
    name="create_flashcard_deck",
    description="Create a flashcard deck manually. Cards formatted as 'question|answer' per line.",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Name of the deck"},
            "cards": {"type": "string", "description": "Cards in 'question|answer' format, one per line"},
        },
        "required": ["name", "cards"],
    },
    handler=create_flashcard_deck,
))

registry.register(Tool(
    name="generate_flashcard_deck",
    description="Auto-generate flashcards on any topic using AI. Use when user says 'make flashcards about X' or 'study mode on X'.",
    parameters={
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "Topic to generate flashcards about"},
            "count": {"type": "integer", "description": "Number of cards to generate (default 10)"},
        },
        "required": ["topic"],
    },
    handler=generate_deck_from_topic,
))

registry.register(Tool(
    name="list_flashcard_decks",
    description="List all available flashcard decks with card counts and last scores.",
    parameters={"type": "object", "properties": {}, "required": []},
    handler=list_decks,
))

registry.register(Tool(
    name="start_quiz",
    description="Start a quiz session on a flashcard deck. Use when user says 'quiz me' or 'test me on X'.",
    parameters={
        "type": "object",
        "properties": {
            "deck_name": {"type": "string", "description": "Name of the deck to quiz (partial match ok). If empty, uses most recent."},
            "count": {"type": "integer", "description": "Number of questions (default 5)"},
        },
        "required": [],
    },
    handler=start_quiz,
))

registry.register(Tool(
    name="answer_quiz",
    description="Submit an answer to the current quiz question. Use when user gives an answer during an active quiz.",
    parameters={
        "type": "object",
        "properties": {
            "answer": {"type": "string", "description": "The user's answer to the current question"},
        },
        "required": ["answer"],
    },
    handler=answer_quiz,
))
