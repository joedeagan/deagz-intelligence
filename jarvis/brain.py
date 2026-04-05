"""Claude API integration — Jarvis's brain.

Dual-model architecture:
  - Haiku: fast conversational layer (~0.5s) — handles chat, decides if tools are needed
  - Sonnet: heavy execution layer — runs tools, does research, returns results

Flow:
  1. User speaks → Haiku instantly decides: reply directly OR call tools
  2. If no tools needed → Haiku responds immediately (fast path)
  3. If tools needed → Haiku gives a quick acknowledgment, Sonnet runs tools in background
  4. Sonnet result comes back → Haiku formats it into a spoken response
"""

import anthropic

from jarvis.config import ANTHROPIC_API_KEY, SYSTEM_PROMPT, get_system_prompt
from jarvis.tools.base import registry

# Fast model for conversation
FAST_MODEL = "claude-haiku-4-5-20251001"
# Heavy model for tool execution and research
HEAVY_MODEL = "claude-sonnet-4-20250514"


def _load_persistent_context() -> str:
    """Load facts/preferences/conversations once at import time."""
    try:
        from jarvis.tools.memory import _load_json, FACTS_FILE, PREFERENCES_FILE, CONVERSATIONS_FILE

        sections = []

        facts = _load_json(FACTS_FILE)
        if facts:
            lines = [f"- {k}: {v['fact']}" for k, v in facts.items()]
            sections.append("\n\n## Known Facts About the User\n" + "\n".join(lines))

        prefs = _load_json(PREFERENCES_FILE)
        if prefs:
            lines = [f"- {k}: {v['value']}" for k, v in prefs.items()]
            sections.append("\n\n## User Preferences\n" + "\n".join(lines))

        convos = _load_json(CONVERSATIONS_FILE)
        if convos:
            recent = convos[-5:]
            lines = [f"- [{c['date']}] {c['summary']}" for c in recent]
            sections.append("\n\n## Recent Conversation History\n" + "\n".join(lines))

        return "".join(sections)
    except Exception:
        return ""


# Persistent context loaded once at startup (facts, prefs, convos)
_PERSISTENT_CONTEXT = _load_persistent_context()

def _get_live_prompt() -> str:
    """System prompt with LIVE time + cached persistent context."""
    return get_system_prompt() + _PERSISTENT_CONTEXT

# Keep for backward compat
FULL_SYSTEM_PROMPT = SYSTEM_PROMPT + _PERSISTENT_CONTEXT


class Brain:
    def __init__(self):
        self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self._conversation: list[dict] = []
        self._max_history = 12  # Fewer messages = faster API calls

    def _auto_log(self, user_text: str, reply: str):
        """Silently log every exchange to the full memory log."""
        try:
            from jarvis.tools.memory import log_exchange
            log_exchange(user_msg=user_text, jarvis_msg=reply)
        except Exception:
            pass

    def _filter_tools(self, user_text: str) -> list:
        """Only pass relevant tools to Haiku based on keywords. Cuts 94 tools to ~15."""
        all_tools = registry.schemas()
        text = user_text.lower()

        # Always include these core tools
        core = {"get_current_time", "get_weather", "web_search", "open_url", "open_application",
                "run_command", "save_conversation", "save_fact", "save_preference"}

        # Keyword → tool groups
        groups = {
            "music": {"spotify_play", "spotify_control", "spotify_now_playing", "spotify_create_playlist",
                      "auto_dj", "rate_song", "play_music", "control_music", "get_music_taste"},
            "kalshi": {"get_kalshi_portfolio", "get_kalshi_bot_status", "get_kalshi_trades",
                       "get_live_scores", "ai_research_bet", "analyze_kalshi_strategy",
                       "scan_kalshi_markets", "optimize_bot", "adjust_bot_config",
                       "start_kalshi_monitor", "get_latest_report", "send_daily_report",
                       "scan_arbitrage", "backtest_config", "get_equity_history", "get_strategy_performance"},
            "memory": {"recall_conversations", "remember_everything", "get_preferences", "get_facts"},
            "screen": {"screen_check", "screen_help", "analyze_screenshot", "start_watching", "solve_from_screen"},
            "code": {"write_code", "build_website", "run_script"},
            "contacts": {"save_contact", "get_contact", "text_contact"},
            "image": {"generate_image"},
            "power": {"lock_computer", "sleep_computer", "shutdown_computer", "restart_computer",
                      "cancel_shutdown", "set_brightness", "set_volume"},
            "routine": {"morning_routine", "bedtime_routine", "focus_mode"},
            "study": {"homework_help", "homework_autopilot", "create_flashcard_deck", "start_quiz", "answer_quiz"},
            "docs": {"create_document", "draft_email", "summarize_url", "get_news"},
            "voice": {"list_voices", "switch_voice", "clone_voice"},
            "clipboard": {"check_clipboard", "clipboard_action"},
            "alerts": {"start_alerts", "stop_alerts"},
            "stems": {"separate_song", "get_stem_status", "control_stems"},
            "misc": {"set_reminder", "list_reminders", "set_alarm", "send_text", "get_game_time",
                      "screenshot", "read_file", "write_file", "list_directory", "kill_process",
                      "get_system_info", "identify_song", "whats_playing"},
        }

        # Match keywords to groups
        keywords = {
            "music": ["play", "song", "spotify", "music", "playlist", "dj", "skip", "pause", "next", "playing", "track", "album", "artist", "make me a", "create a", "taste", "listening", "history"],
            "kalshi": ["kalshi", "bet", "portfolio", "bot", "trade", "position", "optimize", "strategy", "picks", "monitor", "report", "arbitrage", "polymarket", "backtest", "equity", "config", "edge", "min edge", "max edge", "set min", "set max", "change the", "adjust"],
            "memory": ["remember", "recall", "what did we", "do you remember", "forgot", "last time", "talked about"],
            "screen": ["screen", "what's on my", "looking at", "solve what", "watch my screen"],
            "code": ["write", "code", "script", "program", "build", "website", "python"],
            "contacts": ["text", "contact", "phone", "call", "message someone", "save contact"],
            "image": ["draw", "image", "picture", "generate", "create an image"],
            "power": ["lock", "sleep", "shut down", "restart", "brightness", "volume", "dim"],
            "routine": ["morning", "goodnight", "bedtime", "focus", "routine"],
            "study": ["homework", "quiz", "flashcard", "study", "solve", "math", "algebra"],
            "docs": ["document", "doc", "email", "summarize", "news", "article"],
            "stems": ["separate", "stem", "stems", "isolate", "mute drums", "solo vocal", "mute bass", "split song", "vocals", "instrumental"],
            "voice": ["voice", "clone", "switch voice"],
            "clipboard": ["clipboard", "copied", "paste"],
            "alerts": ["alert", "notify", "notification"],
        }

        active = set(core)
        matched_any = False
        for group, kws in keywords.items():
            if any(kw in text for kw in kws):
                active.update(groups.get(group, set()))
                matched_any = True

        # If nothing matched, include misc + a broad set
        if not matched_any:
            active.update(groups["misc"])
            active.update(groups["docs"])

        return [t for t in all_tools if t["name"] in active]

    def think(self, user_text: str) -> str:
        """Send user text through the dual-model pipeline."""
        self._conversation.append({"role": "user", "content": user_text})
        self._trim_history()
        self._last_user_text = user_text

        tools = self._filter_tools(user_text)

        # Fast path: only if NO special tools matched (just core tools)
        # If any non-core tools matched, we MUST pass them to Haiku
        core_names = {"get_current_time", "get_weather", "web_search", "open_url", "open_application",
                      "run_command", "save_conversation", "save_fact", "save_preference"}
        has_special_tools = any(t["name"] not in core_names for t in tools)
        if not has_special_tools and len(tools) <= 9:
            try:
                fast_resp = self._client.messages.create(
                    model=FAST_MODEL,
                    max_tokens=250,
                    system=_get_live_prompt(),
                    messages=self._conversation,
                )
                fast_text = " ".join(b.text for b in fast_resp.content if b.type == "text").strip()
                # If Haiku gave a real answer (not asking to use tools), return it
                if fast_text and len(fast_text) > 2:
                    self._conversation.append({"role": "assistant", "content": fast_resp.content})
                    self._auto_log(self._last_user_text, fast_text)
                    return fast_text
            except Exception:
                pass

        # Step 1: Ask Haiku with tools
        response = self._client.messages.create(
            model=FAST_MODEL,
            max_tokens=250,
            system=_get_live_prompt(),
            messages=self._conversation,
            tools=tools if tools else [],
        )

        # Collect text and tool calls
        text_parts = []
        tool_uses = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_uses.append(block)

        # Fast path: no tools needed — Haiku responds directly
        if not tool_uses:
            reply = " ".join(text_parts).strip()
            self._conversation.append({"role": "assistant", "content": response.content})
            self._auto_log(self._last_user_text, reply)
            return reply

        # Tool path: execute tools, then let Haiku format the response
        self._conversation.append({"role": "assistant", "content": response.content})

        # Execute all tool calls (these may be slow — weather, Kalshi, web search, etc.)
        tool_results = []
        for tool_use in tool_uses:
            result = registry.execute(tool_use.name, tool_use.input)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_use.id,
                "content": result,
            })

        self._conversation.append({"role": "user", "content": tool_results})

        # Step 2: Haiku formats the tool results into a spoken response
        # NO tools passed here = fast response
        final = self._client.messages.create(
            model=FAST_MODEL,
            max_tokens=250,
            system=_get_live_prompt(),
            messages=self._conversation,
        )

        # Check if Haiku wants to call MORE tools (chain)
        more_tool_uses = []
        final_text = []
        for block in final.content:
            if block.type == "text":
                final_text.append(block.text)
            elif block.type == "tool_use":
                more_tool_uses.append(block)

        # If chaining tools, handle up to 3 more rounds
        if more_tool_uses:
            self._conversation.append({"role": "assistant", "content": final.content})

            for _round in range(3):
                chain_results = []
                for tool_use in more_tool_uses:
                    result = registry.execute(tool_use.name, tool_use.input)
                    chain_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": result,
                    })
                self._conversation.append({"role": "user", "content": chain_results})

                chain_final = self._client.messages.create(
                    model=FAST_MODEL,
                    max_tokens=250,
                    system=_get_live_prompt(),
                    messages=self._conversation,
                )

                more_tool_uses = []
                chain_text = []
                for block in chain_final.content:
                    if block.type == "text":
                        chain_text.append(block.text)
                    elif block.type == "tool_use":
                        more_tool_uses.append(block)

                self._conversation.append({"role": "assistant", "content": chain_final.content})

                if not more_tool_uses:
                    r = " ".join(chain_text).strip()
                    self._auto_log(self._last_user_text, r)
                    return r

            r = " ".join(chain_text).strip() if chain_text else "Done."
            self._auto_log(self._last_user_text, r)
            return r

        reply = " ".join(final_text).strip()
        self._conversation.append({"role": "assistant", "content": final.content})
        self._auto_log(self._last_user_text, reply)
        return reply

    def think_fast(self, user_text: str) -> str:
        """Quick response only — no tools. For acknowledgments and simple chat."""
        return self._client.messages.create(
            model=FAST_MODEL,
            max_tokens=250,
            system=_get_live_prompt(),
            messages=[{"role": "user", "content": user_text}],
        ).content[0].text

    def reload_context(self):
        """Reload persistent context from disk (call after saving new facts/prefs)."""
        global FULL_SYSTEM_PROMPT
        FULL_SYSTEM_PROMPT = SYSTEM_PROMPT + _load_persistent_context()

    def _trim_history(self):
        if len(self._conversation) > self._max_history:
            self._conversation = self._conversation[-self._max_history:]
            while self._conversation:
                msg = self._conversation[0]
                if msg["role"] == "user":
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        break
                    if isinstance(content, list) and any(
                        b.get("type") == "tool_result" for b in content
                    ):
                        self._conversation.pop(0)
                        continue
                    break
                self._conversation.pop(0)

    def reset(self):
        self._conversation.clear()
