"""Side inbox for the home agent.

The main command queue lives in the web server's memory; brain TOOLS can't
reach it without circular imports. They drop commands here instead, and the
agent's poll endpoint drains both. Lets spotify_play say "wake the TV and
open Spotify" from inside a tool call.
"""

import time

queue: list = []


def enqueue(cmd_type: str, payload: dict = None):
    queue.append({"type": cmd_type, "payload": payload or {}, "ts": time.time()})
