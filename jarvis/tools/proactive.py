"""Proactive tools — clipboard intelligence, homework autopilot, alerts system."""

import json
import subprocess
import threading
import datetime
import base64
from pathlib import Path

import anthropic
import httpx

from jarvis.config import ANTHROPIC_API_KEY, KALSHI_BOT_URL, GMAIL_ADDRESS, GMAIL_APP_PASSWORD
from jarvis.tools.base import Tool, registry

ALERTS_FILE = Path(__file__).parent.parent.parent / "data" / "alerts.json"

_clipboard_watching = False
_clipboard_thread = None
_last_clipboard = ""
_clipboard_result = ""

_alerts_running = False
_alerts_thread = None


# ═══════════════════════════════════════
# CLIPBOARD INTELLIGENCE
# ═══════════════════════════════════════

def _get_clipboard() -> str:
    """Get current clipboard text on Windows."""
    try:
        result = subprocess.run(
            'powershell -Command "Get-Clipboard"',
            shell=True, capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _analyze_clipboard(text: str) -> str:
    """Use Claude to figure out what the clipboard content is and offer help."""
    if len(text) < 3:
        return ""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            messages=[{
                "role": "user",
                "content": f"""The user just copied this to their clipboard:
---
{text[:1000]}
---

In 1-2 sentences, identify what this is and offer ONE helpful action. Examples:
- URL → "That's an article about X. Want me to summarize it?"
- Code → "That's Python code with a bug on line 3. Want me to fix it?"
- Math problem → "That's a quadratic equation. Want me to solve it?"
- Address → "That's an address in Ohio. Want me to get directions?"
- Phone number → "Want me to save that contact?"
- Random text → "Nothing actionable."

Be brief. If it's not interesting, just say "Nothing actionable." """
            }],
        )
        result = resp.content[0].text
        if "nothing actionable" in result.lower():
            return ""
        return result
    except Exception:
        return ""


def check_clipboard(**kwargs) -> str:
    """Check what's on the clipboard and offer intelligent actions."""
    text = _get_clipboard()
    if not text:
        return "Clipboard is empty."

    analysis = _analyze_clipboard(text)
    if analysis:
        return f"Clipboard contains: \"{text[:100]}{'...' if len(text) > 100 else ''}\"\n\n{analysis}"
    return f"Clipboard: \"{text[:200]}\" — nothing I can help with there."


def clipboard_action(action: str = "analyze", **kwargs) -> str:
    """Act on clipboard content — summarize, solve, explain, translate, etc."""
    text = _get_clipboard()
    if not text:
        return "Clipboard is empty."

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        prompts = {
            "summarize": f"Summarize this in 2-3 sentences:\n\n{text[:3000]}",
            "solve": f"Solve this problem step by step. Keep it brief (spoken delivery):\n\n{text[:2000]}",
            "explain": f"Explain this simply in 2-3 sentences:\n\n{text[:2000]}",
            "translate": f"Translate this to English (if not English) or to Spanish:\n\n{text[:2000]}",
            "fix": f"Fix any errors in this code/text and explain what was wrong:\n\n{text[:2000]}",
            "analyze": f"What is this and what's useful about it? 2 sentences max:\n\n{text[:2000]}",
        }

        prompt = prompts.get(action.lower(), prompts["analyze"])

        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=250,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text
    except Exception as e:
        return f"Failed: {e}"


def _clipboard_watch_loop():
    """Background loop — watches clipboard for changes."""
    global _clipboard_watching, _last_clipboard, _clipboard_result
    import time

    while _clipboard_watching:
        try:
            current = _get_clipboard()
            if current and current != _last_clipboard and len(current) > 5:
                _last_clipboard = current
                analysis = _analyze_clipboard(current)
                if analysis:
                    _clipboard_result = analysis
        except Exception:
            pass
        time.sleep(2)


def start_clipboard_watch(**kwargs) -> str:
    """Start watching clipboard for intelligent suggestions."""
    global _clipboard_watching, _clipboard_thread
    if _clipboard_watching:
        return "Already watching clipboard."
    _clipboard_watching = True
    _clipboard_thread = threading.Thread(target=_clipboard_watch_loop, daemon=True)
    _clipboard_thread.start()
    return "Clipboard intelligence active. I'll analyze anything you copy."


def stop_clipboard_watch(**kwargs) -> str:
    global _clipboard_watching
    _clipboard_watching = False
    return "Clipboard watching stopped."


# ═══════════════════════════════════════
# HOMEWORK AUTOPILOT
# ═══════════════════════════════════════

def homework_autopilot(problems: str = "", subject: str = "math", **kwargs) -> str:
    """Solve multiple homework problems at once with step-by-step explanations."""
    if not problems:
        # Try clipboard
        problems = _get_clipboard()
        if not problems:
            return "Paste your homework problems or copy them to clipboard first."

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=800,
            messages=[{
                "role": "user",
                "content": f"""You are a patient tutor. Solve ALL of these {subject} problems step by step.
For each problem:
1. State the problem
2. Show the work (brief)
3. Give the final answer

Keep explanations clear but concise — this will be spoken aloud.
If there are many problems, solve them all.

Problems:
{problems}"""
            }],
        )
        answer = resp.content[0].text

        # Also save as a document
        try:
            from jarvis.tools.system import create_document
            create_document(
                title=f"Homework Solutions - {subject.title()}",
                content=f"# Homework Solutions\n## {subject.title()}\n## {datetime.datetime.now().strftime('%B %d, %Y')}\n\n{answer}",
                format="docx",
            )
        except Exception:
            pass

        return answer
    except Exception as e:
        return f"Failed to solve: {e}"


def solve_from_screen(**kwargs) -> str:
    """Capture the screen and solve whatever homework/math is visible."""
    try:
        result = subprocess.run(
            'powershell -Command "Add-Type -AssemblyName System.Windows.Forms; '
            '[System.Windows.Forms.Screen]::PrimaryScreen.Bounds | '
            'ForEach-Object { $bmp = New-Object System.Drawing.Bitmap($_.Width, $_.Height); '
            '$g = [System.Drawing.Graphics]::FromImage($bmp); '
            '$g.CopyFromScreen($_.Location, [System.Drawing.Point]::Empty, $_.Size); '
            r'$path = \"$env:TEMP\jarvis_hw.png\"; '
            '$bmp.Save($path); $path }"',
            shell=True, capture_output=True, text=True, timeout=10,
        )
        img_path = result.stdout.strip()
        if not img_path or not Path(img_path).exists():
            return "Couldn't capture the screen."

        with open(img_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=600,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_b64}},
                    {"type": "text", "text": "Find ALL math/homework problems visible on this screen. Solve each one step by step. Show your work briefly and give final answers. If no problems are visible, say so."},
                ],
            }],
        )
        return resp.content[0].text
    except Exception as e:
        return f"Failed: {e}"


# ═══════════════════════════════════════
# PROACTIVE ALERTS
# ═══════════════════════════════════════

def _send_alert(title: str, message: str):
    """Send alert via Windows notification + optional email."""
    # Windows toast notification
    try:
        subprocess.run(
            f'powershell -Command "Add-Type -AssemblyName System.Windows.Forms; '
            f"$n = New-Object System.Windows.Forms.NotifyIcon; "
            f"$n.Icon = [System.Drawing.SystemIcons]::Information; "
            f"$n.Visible = $true; "
            f"$n.ShowBalloonTip(5000, '{title}', '{message}', 'Info')\"",
            shell=True, timeout=5,
        )
    except Exception:
        pass


def _check_alerts():
    """Check for notable events that warrant a proactive alert."""
    alerts = []

    # Check Kalshi positions for big moves
    try:
        resp = httpx.get(f"{KALSHI_BOT_URL}/api/portfolio", timeout=10)
        data = resp.json()
        for pos in data.get("positions", []):
            upnl = pos.get("upnl", 0)
            if isinstance(upnl, (int, float)):
                if upnl > 0.50:
                    alerts.append(f"Kalshi bet up ${upnl:.2f} — consider taking profit")
                elif upnl < -0.50:
                    alerts.append(f"Kalshi bet down ${abs(upnl):.2f} — review position")
    except Exception:
        pass

    # Check bot status for issues
    try:
        resp = httpx.get(f"{KALSHI_BOT_URL}/api/bot/status", timeout=10)
        data = resp.json()
        if not data.get("running"):
            alerts.append("Kalshi bot is STOPPED — may need attention")
        if data.get("consecutive_losses", 0) >= 7:
            alerts.append(f"Bot on {data['consecutive_losses']} loss streak — consider pausing")
    except Exception:
        pass

    return alerts


def _alerts_loop():
    """Background loop — checks for alerts every 15 minutes."""
    global _alerts_running
    import time

    while _alerts_running:
        try:
            alerts = _check_alerts()
            for alert in alerts:
                _send_alert("JARVIS Alert", alert)
        except Exception:
            pass

        for _ in range(90):  # 15 min in 10s chunks
            if not _alerts_running:
                break
            time.sleep(10)


def start_alerts(**kwargs) -> str:
    """Start proactive alerts — checks every 15 minutes for notable events."""
    global _alerts_running, _alerts_thread
    if _alerts_running:
        return "Alerts already active."
    _alerts_running = True
    _alerts_thread = threading.Thread(target=_alerts_loop, daemon=True)
    _alerts_thread.start()
    return "Proactive alerts active. I'll notify you about big Kalshi moves, bot issues, and other events."


def stop_alerts(**kwargs) -> str:
    global _alerts_running
    _alerts_running = False
    return "Alerts stopped."


# ─── Register All ───

# Clipboard
registry.register(Tool(
    name="check_clipboard",
    description="Check what's on the clipboard and offer intelligent actions. Use for 'what did I copy', 'check my clipboard', 'what's in my clipboard'.",
    parameters={"type": "object", "properties": {}},
    handler=check_clipboard,
))

registry.register(Tool(
    name="clipboard_action",
    description="Act on clipboard content — summarize, solve, explain, translate, or fix. Use for 'summarize what I copied', 'solve this', 'explain what I copied', 'fix this code I copied'.",
    parameters={
        "type": "object",
        "properties": {
            "action": {"type": "string", "description": "Action: summarize, solve, explain, translate, fix, analyze"},
        },
        "required": ["action"],
    },
    handler=clipboard_action,
))

registry.register(Tool(
    name="start_clipboard_watch",
    description="Start watching clipboard for intelligent auto-suggestions. Use for 'watch my clipboard', 'clipboard mode on'.",
    parameters={"type": "object", "properties": {}},
    handler=start_clipboard_watch,
))

# Homework
registry.register(Tool(
    name="homework_autopilot",
    description="Solve multiple homework problems at once. Paste problems or copies from clipboard. Creates a Word doc with solutions. Use for 'solve my homework', 'do these problems', 'homework help with all of these'.",
    parameters={
        "type": "object",
        "properties": {
            "problems": {"type": "string", "description": "The homework problems to solve (or leave empty to use clipboard)"},
            "subject": {"type": "string", "description": "Subject: math, algebra, science, history, english (default: math)"},
        },
    },
    handler=homework_autopilot,
))

registry.register(Tool(
    name="solve_from_screen",
    description="Capture the screen and solve any homework/math problems visible. Use for 'solve what's on my screen', 'help me with this problem on screen', 'solve this for me'.",
    parameters={"type": "object", "properties": {}},
    handler=solve_from_screen,
))

# Alerts
registry.register(Tool(
    name="start_alerts",
    description="Start proactive alerts — notifications for big Kalshi moves, bot issues, weather warnings. Use for 'alert me', 'notify me about my bets', 'proactive mode on'.",
    parameters={"type": "object", "properties": {}},
    handler=start_alerts,
))

registry.register(Tool(
    name="stop_alerts",
    description="Stop proactive alerts.",
    parameters={"type": "object", "properties": {}},
    handler=stop_alerts,
))
