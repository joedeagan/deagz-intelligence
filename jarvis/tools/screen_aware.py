"""Screen Awareness — Jarvis periodically watches your screen and offers contextual help."""

import base64
import datetime
import subprocess
import threading
from pathlib import Path

import anthropic

from jarvis.config import ANTHROPIC_API_KEY
from jarvis.tools.base import Tool, registry

_watching = False
_watch_thread = None
_last_insight = ""
_last_context = ""


def _capture_screen() -> str | None:
    """Capture screenshot and return as base64."""
    try:
        result = subprocess.run(
            'powershell -Command "Add-Type -AssemblyName System.Windows.Forms; '
            '[System.Windows.Forms.Screen]::PrimaryScreen.Bounds | '
            'ForEach-Object { $bmp = New-Object System.Drawing.Bitmap($_.Width, $_.Height); '
            '$g = [System.Drawing.Graphics]::FromImage($bmp); '
            '$g.CopyFromScreen($_.Location, [System.Drawing.Point]::Empty, $_.Size); '
            r'$path = \"$env:TEMP\jarvis_watch.png\"; '
            '$bmp.Save($path); $path }"',
            shell=True, capture_output=True, text=True, timeout=10,
        )
        img_path = result.stdout.strip()
        if img_path and Path(img_path).exists():
            with open(img_path, "rb") as f:
                return base64.b64encode(f.read()).decode()
    except Exception:
        pass
    return None


def _analyze_screen(img_b64: str, question: str = "") -> str:
    """Send screenshot to Claude Vision for analysis."""
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        prompt = question or (
            "Look at this screenshot. In 1-2 sentences, describe what the user is doing "
            "and if there's anything helpful you could proactively offer. "
            "Examples: if they're on a math problem, offer to solve it. "
            "If they're on YouTube, mention the video topic. "
            "If they're coding, spot any bugs. "
            "If nothing interesting, just say 'nothing notable'. "
            "Be very brief."
        )

        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=150,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_b64}},
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        return resp.content[0].text
    except Exception as e:
        return f"Analysis failed: {e}"


def screen_check(**kwargs) -> str:
    """Take a screenshot and analyze what's on screen right now."""
    img = _capture_screen()
    if not img:
        return "Couldn't capture the screen."

    analysis = _analyze_screen(img)
    global _last_context
    _last_context = analysis
    return analysis


def screen_help(question: str = "", **kwargs) -> str:
    """Analyze the screen with a specific question in mind."""
    img = _capture_screen()
    if not img:
        return "Couldn't capture the screen."
    return _analyze_screen(img, question or "What's on this screen? Give a helpful response.")


def _watch_loop():
    """Background loop that checks screen every 60 seconds for notable changes."""
    global _watching, _last_insight, _last_context
    import time

    while _watching:
        try:
            img = _capture_screen()
            if img:
                analysis = _analyze_screen(img)
                if "nothing notable" not in analysis.lower():
                    _last_insight = analysis
                    _last_context = analysis
        except Exception:
            pass

        # Check every 60 seconds
        for _ in range(12):
            if not _watching:
                break
            time.sleep(5)


def start_watching(**kwargs) -> str:
    """Start screen awareness — Jarvis watches your screen every 60s."""
    global _watching, _watch_thread

    if _watching:
        return "Already watching your screen."

    _watching = True
    _watch_thread = threading.Thread(target=_watch_loop, daemon=True)
    _watch_thread.start()
    return "Screen awareness active. I'll keep an eye on what you're doing and offer help when relevant."


def stop_watching(**kwargs) -> str:
    """Stop screen awareness."""
    global _watching
    _watching = False
    return "Screen awareness stopped."


def get_screen_insight(**kwargs) -> str:
    """Get the latest screen insight from background watching."""
    if _last_insight:
        return f"Last observation: {_last_insight}"
    return "No screen insights yet. Start watching with 'watch my screen'."


# ─── Register ───

registry.register(Tool(
    name="screen_check",
    description="Take a screenshot and analyze what's on screen. Use for 'what's on my screen', 'what am I looking at', 'help me with what's on screen'.",
    parameters={"type": "object", "properties": {}},
    handler=screen_check,
))

registry.register(Tool(
    name="screen_help",
    description="Analyze the screen with a specific question. Use for 'help me with this', 'solve what's on my screen', 'what's this error', 'read this for me'.",
    parameters={
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "Specific question about what's on screen"},
        },
    },
    handler=screen_help,
))

registry.register(Tool(
    name="start_watching",
    description="Start screen awareness — Jarvis watches your screen every 60 seconds and offers contextual help. Use for 'watch my screen', 'keep an eye on what I'm doing', 'screen awareness on'.",
    parameters={"type": "object", "properties": {}},
    handler=start_watching,
))

registry.register(Tool(
    name="stop_watching",
    description="Stop screen awareness. Use for 'stop watching my screen', 'screen awareness off'.",
    parameters={"type": "object", "properties": {}},
    handler=stop_watching,
))
