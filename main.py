#!/usr/bin/env python3
"""Jarvis -- AI Voice Assistant."""

import sys
import os
import datetime

# Force UTF-8 for Windows console
if sys.platform == "win32":
    os.system("chcp 65001 >nul 2>&1")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich import box

# Import tools to trigger registration
from jarvis.tools import system as _system_tools  # noqa: F401
from jarvis.tools import kalshi as _kalshi_tools   # noqa: F401

from jarvis.voice.listener import Listener
from jarvis.voice.speaker import Speaker
from jarvis.brain import Brain
from jarvis.config import ANTHROPIC_API_KEY, TTS_ENGINE

console = Console()


def cls():
    os.system("cls" if os.name == "nt" else "clear")


def print_banner():
    cls()
    now = datetime.datetime.now().strftime("%I:%M %p")
    date = datetime.datetime.now().strftime("%b %d, %Y")

    console.print()
    console.print(f"  [bold cyan]JARVIS[/]  [dim]|[/]  [dim]{now}  {date}[/]")
    console.print(f"  [dim]{'_' * 70}[/]")
    console.print()
    console.print(f"  [dim]System ready  [/][dim]|[/][dim]  Voice: {TTS_ENGINE}  [/][dim]|[/][dim]  20 tools loaded[/]")
    console.print()


def jarvis_msg(message: str):
    ts = datetime.datetime.now().strftime("%I:%M %p")
    console.print()
    console.print(f"  [dim]{ts}[/]")
    console.print(f"  [bold cyan]J[/]  {message}")


def user_msg(message: str):
    ts = datetime.datetime.now().strftime("%I:%M %p")
    console.print()
    console.print(f"{'':>68}[dim]{ts}[/]")
    console.print(f"{'':>58}[bold green]{message}[/]  [bold green]D[/]")


def status_msg(message: str):
    console.print(f"  [dim]... {message}[/]")


def shutdown_screen(speaker):
    farewell = "Shutting down. Good evening, Deagz."
    jarvis_msg(farewell)
    speaker.speak(farewell)
    console.print()
    console.print(f"  [dim]JARVIS offline.[/]")
    console.print()


# -- Voice Mode --

def run_voice_mode():
    if not ANTHROPIC_API_KEY:
        console.print("[red]  ANTHROPIC_API_KEY not set in .env[/red]")
        sys.exit(1)

    print_banner()

    listener = Listener()
    speaker = Speaker()
    brain = Brain()

    greeting = "Online and at your service, Deagz."
    jarvis_msg(greeting)
    speaker.speak(greeting)

    try:
        while True:
            console.print()
            console.print(f"  [dim cyan][ Press ENTER to talk ][/]")
            input()

            console.print(f"  [green][ Recording... ENTER to stop ][/]")
            text = listener.listen_push_to_talk()

            if not text:
                console.print(f"  [dim][ Didn't catch that ][/]")
                continue

            user_msg(text)
            status_msg("thinking")

            response = brain.think(text)
            jarvis_msg(response)
            speaker.speak(response)

    except KeyboardInterrupt:
        console.print()
        shutdown_screen(speaker)
    finally:
        listener.cleanup()


# -- Text Mode --

def run_text_mode():
    if not ANTHROPIC_API_KEY:
        console.print("[red]  ANTHROPIC_API_KEY not set in .env[/red]")
        sys.exit(1)

    print_banner()

    brain = Brain()
    speaker = Speaker()

    greeting = "Online and at your service, Deagz. Text mode."
    jarvis_msg(greeting)
    speaker.speak(greeting)

    try:
        while True:
            console.print()
            user_input = console.input("  [bold green]> [/]").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "bye", "goodbye"):
                break

            user_msg(user_input)
            status_msg("thinking")

            response = brain.think(user_input)
            jarvis_msg(response)
            speaker.speak(response)

    except (KeyboardInterrupt, EOFError):
        pass

    shutdown_screen(speaker)


if __name__ == "__main__":
    if "--text" in sys.argv:
        run_text_mode()
    else:
        run_voice_mode()
