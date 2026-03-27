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

from jarvis.config import ANTHROPIC_API_KEY, SYSTEM_PROMPT
from jarvis.tools.base import registry

# Fast model for conversation
FAST_MODEL = "claude-haiku-4-5-20251001"
# Heavy model for tool execution and research
HEAVY_MODEL = "claude-sonnet-4-20250514"


class Brain:
    def __init__(self):
        self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self._conversation: list[dict] = []
        self._max_history = 20

    def think(self, user_text: str) -> str:
        """Send user text through the dual-model pipeline."""
        self._conversation.append({"role": "user", "content": user_text})
        self._trim_history()

        tools = registry.schemas()

        # Step 1: Ask Haiku to decide — respond directly or use tools
        response = self._client.messages.create(
            model=FAST_MODEL,
            max_tokens=200,
            system=SYSTEM_PROMPT,
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
        final = self._client.messages.create(
            model=FAST_MODEL,
            max_tokens=200,
            system=SYSTEM_PROMPT,
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

        # If chaining tools, handle one more round
        if more_tool_uses:
            self._conversation.append({"role": "assistant", "content": final.content})
            chain_results = []
            for tool_use in more_tool_uses:
                result = registry.execute(tool_use.name, tool_use.input)
                chain_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result,
                })
            self._conversation.append({"role": "user", "content": chain_results})

            # Final response after chain
            chain_final = self._client.messages.create(
                model=FAST_MODEL,
                max_tokens=200,
                system=SYSTEM_PROMPT,
                messages=self._conversation,
            )
            reply = " ".join(
                b.text for b in chain_final.content if b.type == "text"
            ).strip()
            self._conversation.append({"role": "assistant", "content": chain_final.content})
            return reply

        reply = " ".join(final_text).strip()
        self._conversation.append({"role": "assistant", "content": final.content})
        return reply

    def think_fast(self, user_text: str) -> str:
        """Quick response only — no tools. For acknowledgments and simple chat."""
        return self._client.messages.create(
            model=FAST_MODEL,
            max_tokens=100,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_text}],
        ).content[0].text

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
