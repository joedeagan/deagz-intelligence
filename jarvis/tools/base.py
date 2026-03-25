"""Tool registry for Jarvis. Each tool is a callable with a schema for Claude's tool-use API."""

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict  # JSON Schema for the tool's input
    handler: Callable[..., Any]


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool):
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def schemas(self) -> list[dict]:
        """Return tool definitions in Claude API format."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.parameters,
            }
            for t in self._tools.values()
        ]

    def execute(self, name: str, args: dict) -> str:
        """Run a tool by name and return the result as a string."""
        tool = self._tools.get(name)
        if not tool:
            return f"Error: unknown tool '{name}'"
        try:
            result = tool.handler(**args)
            return str(result) if result is not None else "Done."
        except Exception as e:
            return f"Error running {name}: {e}"


# Global registry
registry = ToolRegistry()
