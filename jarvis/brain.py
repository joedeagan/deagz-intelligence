"""Claude API integration — Jarvis's brain. Uses tool-use for actions."""

import anthropic

from jarvis.config import ANTHROPIC_API_KEY, CLAUDE_MODEL, SYSTEM_PROMPT
from jarvis.tools.base import registry


class Brain:
    def __init__(self):
        self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self._conversation: list[dict] = []
        self._max_history = 20  # Keep last N messages for context

    def think(self, user_text: str) -> str:
        """Send user text to Claude, handle tool calls, return final response."""
        self._conversation.append({"role": "user", "content": user_text})
        self._trim_history()

        tools = registry.schemas()

        while True:
            kwargs = {
                "model": CLAUDE_MODEL,
                "max_tokens": 1024,
                "system": SYSTEM_PROMPT,
                "messages": self._conversation,
            }
            if tools:
                kwargs["tools"] = tools

            response = self._client.messages.create(**kwargs)

            # Collect text and tool-use blocks
            text_parts = []
            tool_uses = []
            for block in response.content:
                if block.type == "text":
                    text_parts.append(block.text)
                elif block.type == "tool_use":
                    tool_uses.append(block)

            # If no tool calls, we're done
            if not tool_uses:
                reply = " ".join(text_parts).strip()
                self._conversation.append({"role": "assistant", "content": response.content})
                return reply

            # Execute tool calls and feed results back
            self._conversation.append({"role": "assistant", "content": response.content})

            tool_results = []
            for tool_use in tool_uses:
                result = registry.execute(tool_use.name, tool_use.input)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": result,
                    }
                )

            self._conversation.append({"role": "user", "content": tool_results})

    def _trim_history(self):
        if len(self._conversation) > self._max_history:
            self._conversation = self._conversation[-self._max_history:]
            # Ensure conversation starts with a user message (with text content, not tool_result)
            while self._conversation:
                msg = self._conversation[0]
                if msg["role"] == "user":
                    # Check it's not a tool_result message
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
