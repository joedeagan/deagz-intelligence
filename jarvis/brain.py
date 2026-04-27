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

# Rolling log of the last 20 response times — exposed at /debug/timings.
from collections import deque
import time as _time
RECENT_TIMINGS: deque = deque(maxlen=20)


def _load_persistent_context() -> str:
    """Load facts/preferences/conversations/opinions once at import time."""
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

        try:
            from jarvis.tools.opinions import OPINIONS_FILE
            opinions = _load_json(OPINIONS_FILE)
            if opinions:
                lines = []
                for k, v in list(opinions.items())[-10:]:
                    pct = int(round(v.get("confidence", 0.5) * 100))
                    lines.append(f"- {k}: {v.get('stance','')} ({pct}%)")
                sections.append("\n\n## Jarvis's Current Opinions\n" + "\n".join(lines))
        except Exception:
            pass

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
    # Run background reflection every N completed exchanges.
    _REFLECT_EVERY = 20

    def __init__(self):
        self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self._conversation: list[dict] = []
        # Joe 2026-04-25: cut history from 12 to 6 — every call resends
        # the entire conversation, and at 12 messages the prompt-cache
        # write cost on cold-cache calls + the per-token processing on
        # warm-cache calls both balloon. 6 is enough for short-context
        # voice tasks ("any new tandems" → tool → answer doesn't need
        # 6 prior turns of context).
        self._max_history = 6
        self._exchange_count = 0

    def _auto_log(self, user_text: str, reply: str):
        """Silently log every exchange to the full memory log."""
        try:
            from jarvis.tools.memory import log_exchange
            log_exchange(user_msg=user_text, jarvis_msg=reply)
        except Exception:
            pass
        self._exchange_count += 1
        if self._exchange_count % self._REFLECT_EVERY == 0:
            self._spawn_background_reflection()

    def _spawn_background_reflection(self):
        """Kick reflect_and_learn into a daemon thread so it never blocks chat."""
        import threading
        def _run():
            try:
                from jarvis.tools.opinions import background_reflect
                background_reflect()
            except Exception:
                pass
        threading.Thread(target=_run, daemon=True).start()

    def _auto_outcome(self, user_text: str):
        """If the user's message is an outcome signal on the last opinion, log it."""
        try:
            from jarvis.tools.opinions import auto_record_outcome
            auto_record_outcome(user_text)
        except Exception:
            pass

    def _turn_system(self) -> list:
        """System prompt as content blocks with prompt caching enabled.

        Anthropic prompt caching: marking the static portion with
        cache_control={"type":"ephemeral"} tells the server "cache this
        prefix for ~5 min." Subsequent calls within that window skip
        re-processing the ~3-5KB Jarvis personality + persistent context,
        which dominates per-call latency. Joe noted 15-30s response
        times; warm cache hits typically cut that 50-70% on the system-
        prompt portion of each LLM round-trip.

        Layout:
          - Block 1 (cached): SYSTEM_PROMPT_TEMPLATE prefix (everything
                              BEFORE the {current_time} line) + persistent
                              context (facts/prefs/convos). Stable across
                              calls — perfect for the prefix cache.
          - Block 2 (uncached): The {current_time}-bearing line + any
                                per-turn opinion hint. These vary so they
                                live AFTER the cache boundary.

        Cache hits show up in response.usage as cache_read_input_tokens.
        Cold calls (cache miss) write the prefix and pay full input cost;
        warm calls read from cache for ~10% of the input price.
        """
        from jarvis.config import SYSTEM_PROMPT_TEMPLATE
        import datetime as _dt

        # Split the template at the time-bearing line. Prefix is static;
        # everything from "IMPORTANT: The current date and time" onward
        # depends on `now` and goes in the uncached block.
        SPLIT = "IMPORTANT: The current date and time"
        if SPLIT in SYSTEM_PROMPT_TEMPLATE:
            static_part, dyn_part = SYSTEM_PROMPT_TEMPLATE.split(SPLIT, 1)
            dyn_part = SPLIT + dyn_part  # put marker back
        else:
            # Defensive — if template ever drops the marker, treat the
            # entire prompt as dynamic so we don't accidentally cache a
            # prompt with stale time.
            static_part = ""
            dyn_part = SYSTEM_PROMPT_TEMPLATE

        # Static block: stable Jarvis personality + persistent context.
        static_text = static_part.rstrip() + _PERSISTENT_CONTEXT

        # Dynamic block: current time + per-turn opinion hint.
        now = _dt.datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")
        dyn_text = dyn_part.format(current_time=now)
        suffix = getattr(self, "_turn_prompt_suffix", "") or ""
        if suffix:
            dyn_text = dyn_text + suffix

        blocks: list = []
        if static_text.strip():
            blocks.append({
                "type": "text",
                "text": static_text,
                "cache_control": {"type": "ephemeral"},
            })
        blocks.append({
            "type": "text",
            "text": dyn_text,
        })
        return blocks

    def _opinion_hint(self, user_text: str) -> str:
        """If Jarvis has a relevant stored opinion, inject a one-line hint into
        the system prompt for this turn so he can volunteer his view."""
        try:
            from jarvis.tools.opinions import find_relevant_opinion
            op = find_relevant_opinion(user_text)
            if not op:
                return ""
            pct = int(round(op.get("confidence", 0.5) * 100))
            return (f"\n\n## Relevant Stored Opinion\n"
                    f"You previously formed this view on '{op['topic']}': "
                    f"{op.get('stance','')} ({pct}% confidence). "
                    f"Reference it naturally if it helps — you don't have to.")
        except Exception:
            return ""

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
            "alerts": {"start_alerts", "stop_alerts", "send_notification"},
            "advice": {"give_advice", "form_opinion", "update_opinion", "get_opinion",
                       "record_outcome", "reflect_and_learn"},
            "stems": {"separate_song", "get_stem_status", "control_stems"},
            "tandem": {"send_tandem", "check_tandem_inbox"},
            "misc": {"set_reminder", "list_reminders", "set_alarm", "send_text", "get_game_time",
                      "screenshot", "read_file", "write_file", "list_directory", "kill_process",
                      "get_system_info", "identify_song", "whats_playing"},
        }

        # Match keywords to groups
        keywords = {
            "music": ["play", "song", "spotify", "music", "playlist", "dj", "skip", "pause", "next", "playing", "track", "album", "artist", "make me a", "create a", "taste", "listening", "history"],
            "kalshi": ["kalshi", "bet", "portfolio", "bot", "trade", "position", "optimize", "strategy", "picks", "monitor", "report", "arbitrage", "polymarket", "backtest", "equity", "config", "edge", "min edge", "max edge", "set min", "set max", "change the", "adjust", "whale", "smart money", "big trades", "volume"],
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
            "tandem": ["tandem", "tandems", "tandam", "tandum",  # common mishearings
                       "tell dad", "tell brian", "tell leslie", "tell my dad",
                       "tell pops", "tell papa", "tell father",
                       "from dad", "from brian", "from leslie", "from pops",
                       "anything from", "any new from", "draft a message",
                       "draft a tandem", "compose a tandem", "write a tandem",
                       "send dad", "send brian", "send leslie", "send pops"],
            "voice": ["voice", "clone", "switch voice"],
            "clipboard": ["clipboard", "copied", "paste"],
            "alerts": ["alert", "notify", "notification", "ntfy", "send me", "message my phone", "ping my phone", "send to my phone"],
            "advice": ["what do you think", "your opinion", "your take", "should i", "help me decide",
                       "is this a good", "would you", "advise", "advice", "honest opinion",
                       "what would you do", "am i right", "you were right", "you were wrong",
                       "bad call", "good call", "that worked", "that didn't work", "turned out",
                       "reflect", "learn from", "your view"],
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
        """Send user text through the dual-model pipeline. Times the whole
        turn and records it in RECENT_TIMINGS for /debug/timings."""
        start = _time.time()
        path = "fast"
        try:
            reply = self._think_impl(user_text)
        except Exception as e:
            RECENT_TIMINGS.append({
                "ts": _time.time(),
                "user": user_text[:80],
                "seconds": round(_time.time() - start, 2),
                "path": "error",
                "error": str(e)[:120],
            })
            raise
        # _turn_path is set inside _think_impl based on which branch ran.
        path = getattr(self, "_turn_path", "fast")
        RECENT_TIMINGS.append({
            "ts": _time.time(),
            "user": user_text[:80],
            "seconds": round(_time.time() - start, 2),
            "path": path,
        })
        return reply

    def _think_impl(self, user_text: str) -> str:
        """Send user text through the dual-model pipeline."""
        self._turn_path = "fast"
        self._auto_outcome(user_text)
        self._conversation.append({"role": "user", "content": user_text})
        self._trim_history()
        self._last_user_text = user_text
        self._turn_prompt_suffix = self._opinion_hint(user_text)

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
                    system=self._turn_system(),
                    messages=self._conversation,
                )
                fast_text = " ".join(b.text for b in fast_resp.content if b.type == "text").strip()
                # If Haiku gave a real answer (not asking to use tools), return it
                if fast_text and len(fast_text) > 2:
                    self._turn_path = "fast"
                    self._conversation.append({"role": "assistant", "content": fast_resp.content})
                    self._auto_log(self._last_user_text, fast_text)
                    return fast_text
            except Exception:
                pass

        # Step 1: Ask Haiku with tools.
        # max_tokens lowered to 120 (Joe 2026-04-25): Step 1 is a
        # tool-DECISION step, not a response step. Haiku doesn't need
        # 250 tokens of room — it just needs enough to think briefly
        # and emit a tool_use block (or short prose if it's punting).
        # Lowering the cap caps the worst-case generation time without
        # affecting tool selection quality.
        #
        # Forced tool calling for Tandem queries (matches think_stream):
        # see the same block in think_stream for rationale.
        text_lower = user_text.lower()
        tandem_tool_names = {t["name"] for t in tools
                             if t["name"] in {"send_tandem", "check_tandem_inbox"}}
        force_tool = (
            tandem_tool_names
            and any(kw in text_lower for kw in (
                "tandem", "tandam", "tandum",
                "tell dad", "tell brian", "tell leslie",
                "tell pops", "tell papa", "tell my dad",
                "send dad", "send brian", "send leslie",
                "from dad", "from brian", "from leslie",
            ))
        )
        create_kwargs = dict(
            model=FAST_MODEL,
            max_tokens=120,
            system=self._turn_system(),
            messages=self._conversation,
            tools=tools if tools else [],
        )
        if force_tool:
            create_kwargs["tool_choice"] = {"type": "any"}
        response = self._client.messages.create(**create_kwargs)

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
            self._turn_path = "fast"
            reply = " ".join(text_parts).strip()
            self._conversation.append({"role": "assistant", "content": response.content})
            self._auto_log(self._last_user_text, reply)
            return reply

        # Tool path: execute tools, then let Haiku format the response
        self._conversation.append({"role": "assistant", "content": response.content})

        # Execute all tool calls (these may be slow — weather, Kalshi, web search, etc.)
        tool_results = []
        advisor_output = None
        for tool_use in tool_uses:
            result = registry.execute(tool_use.name, tool_use.input)
            if tool_use.name == "give_advice":
                advisor_output = result
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_use.id,
                "content": result,
            })

        self._conversation.append({"role": "user", "content": tool_results})

        # Short-circuit: if the advisor was the primary tool, return its reasoned
        # output directly instead of having Haiku compress it to 1-2 sentences.
        if advisor_output and len(tool_uses) == 1:
            self._turn_path = "advisor"
            self._auto_log(self._last_user_text, advisor_output)
            return advisor_output

        # VOICE-READY SHORT-CIRCUIT (Joe 2026-04-25):
        # Some tools already return a complete, voice-ready one-line
        # response — e.g. send_tandem returns "Tandem sent to Brian, sir.",
        # check_tandem_inbox returns "Four new Tandems, sir. Most recent
        # from Brian: '...'", text_contact returns "Text sent to Jake".
        # For these, calling Haiku a second time to "format" the response
        # is wasted work — it just rephrases the same string and adds a
        # full LLM round-trip (~3-5s). Skip Step 2 entirely.
        #
        # Permissive matching: if ANY of the called tools is voice-ready
        # AND that tool's result is a short string, use it directly even
        # when Haiku also called other tools in the same turn (e.g.
        # get_current_time + check_tandem_inbox). The tandem tool's
        # response is the one the user actually wants to hear.
        _VOICE_READY_TOOLS = {
            "send_tandem",
            "check_tandem_inbox",
            "text_contact",   # returns "Text sent to Jake: \"...\""
        }
        voice_ready_pairs = [
            (tu, tr) for tu, tr in zip(tool_uses, tool_results)
            if tu.name in _VOICE_READY_TOOLS
            and isinstance(tr.get("content"), str)
        ]
        if len(voice_ready_pairs) == 1:
            voice_reply = voice_ready_pairs[0][1]["content"].strip()
            if voice_reply and len(voice_reply) <= 280:
                self._auto_log(self._last_user_text, voice_reply)
                return voice_reply

        # Step 2: Haiku formats the tool results into a spoken response
        # NO tools passed here = fast response.
        # max_tokens lowered to 150 (Joe 2026-04-25): Jarvis voice
        # responses are 1-2 sentences per the system prompt. 150 tokens
        # is ~110 words — already more than the voice cap. Larger cap
        # just means longer worst-case generation when Haiku doesn't
        # naturally stop. Advisor case keeps 400 since it's text-mode.
        final = self._client.messages.create(
            model=FAST_MODEL,
            max_tokens=400 if advisor_output else 150,
            system=self._turn_system(),
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
            self._turn_path = "chain"
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
                    system=self._turn_system(),
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

        self._turn_path = "tools"
        reply = " ".join(final_text).strip()
        self._conversation.append({"role": "assistant", "content": final.content})
        self._auto_log(self._last_user_text, reply)
        return reply

    def think_stream(self, user_text: str):
        """Streaming variant of `think`. Yields incremental text chunks
        (deltas) as Anthropic generates them, so the chat-stream
        endpoint can push text to the user IMMEDIATELY instead of
        waiting for full generation.

        Joe 2026-04-25: voice felt like 30-45s of dead air because the
        brain blocked fully before TTS started. With streaming, the
        text starts appearing in the UI within ~1s of the user
        finishing their speech (cache-warm). Audio still generates at
        the end (full-text TTS), but the perceived latency drop is
        big — user sees "Jarvis is thinking" instead of "blank screen".

        Yields:
          str — each yield is the NEW text since the last yield (a
                delta). Caller is responsible for accumulating into
                full text if needed.

        Falls back to a single `yield <full>` for paths that don't
        easily stream (tool short-circuits, advisor reroutes) so the
        caller can treat every path uniformly.
        """
        # Mirror the setup from `think()` so history + opinion hint
        # behave identically.
        self._auto_outcome(user_text)
        self._conversation.append({"role": "user", "content": user_text})
        self._trim_history()
        self._last_user_text = user_text
        self._turn_prompt_suffix = self._opinion_hint(user_text)

        tools = self._filter_tools(user_text)

        core_names = {"get_current_time", "get_weather", "web_search",
                      "open_url", "open_application", "run_command",
                      "save_conversation", "save_fact", "save_preference"}
        has_special_tools = any(t["name"] not in core_names for t in tools)

        # ---------- Fast path: pure-chat streaming (no tools needed) ----------
        # Only when no special tools matched AND the tool list is small
        # enough that we can confidently skip Step 1's tool-decision call.
        # Mirrors the fast-path heuristic from `think()`.
        if not has_special_tools and len(tools) <= 9:
            try:
                full_parts: list[str] = []
                with self._client.messages.stream(
                    model=FAST_MODEL,
                    max_tokens=150,
                    system=self._turn_system(),
                    messages=self._conversation,
                ) as stream:
                    for text in stream.text_stream:
                        full_parts.append(text)
                        yield text
                full = "".join(full_parts).strip()
                if full and len(full) > 2:
                    self._conversation.append({
                        "role": "assistant",
                        "content": [{"type": "text", "text": full}],
                    })
                    self._auto_log(self._last_user_text, full)
                    return
                # Fall through to tool path if Haiku gave nothing useful.
            except Exception:
                pass

        # ---------- Step 1: ask Haiku with tools (NOT streamed) ----------
        # Step 1 is a tool-DECISION step. We need the full response to
        # see whether tools were requested before deciding what to do.
        # Streaming this would let us peek at text early but most of the
        # time the response is just `tool_use` blocks anyway.
        #
        # FORCED TOOL CALLING (Joe 2026-04-25): when the user's message
        # contains a Tandem-domain keyword AND a Tandem tool is in the
        # filtered set, force the model to call SOME tool (no opt-out).
        # This stops the "Jarvis says 'sent' without actually firing
        # the wire" hallucination. Anthropic's tool_choice="any" tells
        # the model it MUST emit a tool_use block — it can pick which
        # tool, but it can't reply with just text.
        text_lower = user_text.lower()
        tandem_tool_names = {t["name"] for t in tools
                             if t["name"] in {"send_tandem", "check_tandem_inbox"}}
        force_tool = (
            tandem_tool_names
            and any(kw in text_lower for kw in (
                "tandem", "tandam", "tandum",
                "tell dad", "tell brian", "tell leslie",
                "tell pops", "tell papa", "tell my dad",
                "send dad", "send brian", "send leslie",
                "from dad", "from brian", "from leslie",
            ))
        )
        create_kwargs = dict(
            model=FAST_MODEL,
            max_tokens=120,
            system=self._turn_system(),
            messages=self._conversation,
            tools=tools if tools else [],
        )
        if force_tool:
            create_kwargs["tool_choice"] = {"type": "any"}
        response = self._client.messages.create(**create_kwargs)

        text_parts = []
        tool_uses = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_uses.append(block)

        # No tools — Haiku already produced the full reply.
        if not tool_uses:
            reply = " ".join(text_parts).strip()
            self._conversation.append({"role": "assistant", "content": response.content})
            self._auto_log(self._last_user_text, reply)
            yield reply
            return

        # Persist the tool_use bundle to history before exec.
        self._conversation.append({"role": "assistant", "content": response.content})

        # Execute tools.
        tool_results = []
        advisor_output = None
        for tool_use in tool_uses:
            result = registry.execute(tool_use.name, tool_use.input)
            if tool_use.name == "give_advice":
                advisor_output = result
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_use.id,
                "content": result,
            })
        self._conversation.append({"role": "user", "content": tool_results})

        # Short-circuit: advisor primary tool — return its full output verbatim.
        if advisor_output and len(tool_uses) == 1:
            self._auto_log(self._last_user_text, advisor_output)
            yield advisor_output
            return

        # Short-circuit: voice-ready tool — its content IS the response.
        _VOICE_READY_TOOLS = {
            "send_tandem", "check_tandem_inbox", "text_contact",
        }
        voice_ready_pairs = [
            (tu, tr) for tu, tr in zip(tool_uses, tool_results)
            if tu.name in _VOICE_READY_TOOLS
            and isinstance(tr.get("content"), str)
        ]
        if len(voice_ready_pairs) == 1:
            voice_reply = voice_ready_pairs[0][1]["content"].strip()
            if voice_reply and len(voice_reply) <= 280:
                self._auto_log(self._last_user_text, voice_reply)
                yield voice_reply
                return

        # ---------- Step 2: STREAM Haiku formatting the tool result ----------
        # This is the big perceived-latency win. Without streaming the
        # user waits silently while Haiku regenerates the whole 1-2
        # sentence response (~3-5s warm cache). With streaming, the
        # first words appear within a few hundred ms of Haiku's first
        # token.
        try:
            full_parts2: list[str] = []
            with self._client.messages.stream(
                model=FAST_MODEL,
                max_tokens=400 if advisor_output else 150,
                system=self._turn_system(),
                messages=self._conversation,
            ) as stream:
                for text in stream.text_stream:
                    full_parts2.append(text)
                    yield text
            full = "".join(full_parts2).strip()
            if full:
                self._conversation.append({
                    "role": "assistant",
                    "content": [{"type": "text", "text": full}],
                })
                self._auto_log(self._last_user_text, full)
            return
        except Exception:
            # Fallback: non-streaming Step 2.
            final = self._client.messages.create(
                model=FAST_MODEL,
                max_tokens=400 if advisor_output else 150,
                system=self._turn_system(),
                messages=self._conversation,
            )
            reply = " ".join(b.text for b in final.content if b.type == "text").strip()
            if reply:
                self._conversation.append({"role": "assistant", "content": final.content})
                self._auto_log(self._last_user_text, reply)
            yield reply
            return

    def think_fast(self, user_text: str) -> str:
        """Quick response only — no tools. For acknowledgments and simple chat."""
        return self._client.messages.create(
            model=FAST_MODEL,
            max_tokens=250,
            system=self._turn_system(),
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
