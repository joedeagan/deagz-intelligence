"""Self-building Jarvis - "teach yourself to X" and he writes the ability.

How it works:
  1. "Jarvis, teach yourself to <request>" -> build_ability() spawns a worker
     that has a strong model write ONE self-contained tool module.
  2. The draft must pass py_compile AND a banned-import scan, then lands in
     jarvis/tools/selfbuilt/pending/ - NOT live yet.
  3. Jarvis announces the draft; Joe says "install it" -> install_ability()
     moves it into jarvis/tools/selfbuilt/ and hot-loads it. New ability,
     no restart, no human wrote a line.

Guardrails (the point of this file):
  - self-built code lives ONLY in jarvis/tools/selfbuilt/ - it can add new
    abilities but can never modify existing code
  - nothing runs before Joe's spoken approval ("install it")
  - compile gate + denylist scan (no subprocess/exec/secrets access)
  - every selfbuilt module loads inside try/except - a bad ability can't
    take the brain down
  - the selfbuilt/ folder stays on the laptop; it is never pushed to the
    public repo, and repo syncs never delete it
"""

import importlib.util
import json
import os
import re
import threading
import time
from pathlib import Path

from jarvis.tools.base import Tool, registry

TOOLS_DIR = Path(__file__).parent
SELFBUILT_DIR = TOOLS_DIR / "selfbuilt"
PENDING_DIR = SELFBUILT_DIR / "pending"
SELFBUILT_TOOLS: set = set()  # names of live self-built tools (brain filter includes these)

_announce = None  # set by the server - speaks through the wall
_building = False

BANNED = ["subprocess", "os.system", "os.remove", "os.rmdir", "os.unlink", "shutil",
          "rmtree", ".env", "API_KEY", "eval(", "exec(", "__import__", "pickle",
          "ctypes", "socket."]

BUILD_MODEL = os.getenv("SELFBUILD_MODEL", "claude-sonnet-4-20250514")


def set_announcer(fn):
    global _announce
    _announce = fn


def _say(text: str):
    if _announce:
        try:
            _announce(text)
        except Exception:
            pass
    print(f"[selfbuild] {text}")


def _slug(request: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", request.lower()).strip("_")[:40]
    return s or "ability"


def _scan(code: str):
    """Denylist scan. Returns the first banned marker found, or None."""
    for bad in BANNED:
        if bad in code:
            return bad
    return None


def _generate(request: str) -> str:
    import anthropic
    from jarvis.config import ANTHROPIC_API_KEY

    base_src = (TOOLS_DIR / "base.py").read_text(encoding="utf-8")
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model=BUILD_MODEL,
        max_tokens=3000,
        system=(
            "You write ONE self-contained Python module that adds a new ability to "
            "JARVIS, a voice assistant running on a home laptop (Windows, Python 3.12). "
            "The module registers tools that JARVIS's chat brain can call; every tool "
            "result is SPOKEN ALOUD, so handlers return short natural sentences.\n\n"
            "THE TOOL API (jarvis/tools/base.py, already importable):\n" + base_src + "\n\n"
            "TEMPLATE:\n"
            "  from jarvis.tools.base import Tool, registry\n"
            "  def my_handler(some_arg: str = \"\", **kwargs) -> str:\n"
            "      ...\n"
            "      return \"Spoken result, sir.\"\n"
            "  registry.register(Tool(name=..., description=..., parameters={JSON schema}, handler=my_handler))\n\n"
            "HARD RULES:\n"
            "- ONLY these imports: python stdlib (json, re, datetime, math, pathlib, "
            "urllib.request, statistics, random, time) plus httpx. NOTHING else.\n"
            "- NEVER: subprocess, shutil, eval, exec, sockets, reading .env or any key, "
            "deleting files.\n"
            "- If the ability needs persistence, read/write JSON under "
            "Path(__file__).parent.parent.parent.parent / 'data' / 'selfbuilt' / '<name>.json' "
            "(create parents; handle missing file).\n"
            "- Free public APIs only (no API keys). If the request needs a paid/keyed "
            "service, build the closest keyless version and say so in the docstring.\n"
            "- Tool descriptions must include trigger phrases ('Use for ...') so the "
            "brain knows when to call them.\n"
            "- Handlers must catch their own exceptions and return a graceful spoken "
            "sentence on failure.\n"
            "- Module starts with a docstring: what it does + example spoken commands.\n\n"
            "Output ONLY the Python code. No markdown fences, no commentary."
        ),
        messages=[{"role": "user", "content": f"JARVIS's owner asked: teach yourself to {request}"}],
    )
    code = " ".join(b.text for b in msg.content if b.type == "text").strip()
    # strip fences if the model added them anyway
    code = re.sub(r"^```(?:python)?\s*", "", code)
    code = re.sub(r"\s*```$", "", code)
    return code


def _build_worker(request: str):
    global _building
    try:
        code = _generate(request)
        bad = _scan(code)
        if bad:
            _say(f"Sir, I drafted the {request} ability but it reached for something "
                 f"off-limits ({bad.strip('.(')}) — I've discarded it. Try rephrasing.")
            return
        name = _slug(request)
        PENDING_DIR.mkdir(parents=True, exist_ok=True)
        path = PENDING_DIR / f"{name}.py"
        path.write_text(code, encoding="utf-8")
        # compile gate
        import py_compile
        try:
            py_compile.compile(str(path), doraise=True)
        except Exception as e:
            path.unlink(missing_ok=True)
            _say(f"Sir, my draft of the {request} ability didn't compile — I've thrown "
                 "it away. Ask me again and I'll take another run at it.")
            print(f"[selfbuild] compile fail: {e}")
            return
        _say(f"Sir — I've drafted a new ability: {request}. Say 'install it' when "
             "you'd like me to switch it on.")
    except Exception as e:
        _say("Sir, the ability draft failed — my apologies.")
        print(f"[selfbuild] build failed: {e}")
    finally:
        _building = False


def build_ability(request: str = "", **kwargs) -> str:
    global _building
    request = (request or "").strip()
    if not request:
        return "Teach myself what, sir?"
    if _building:
        return "I'm mid-build on the last one, sir — one ability at a time."
    _building = True
    threading.Thread(target=_build_worker, args=(request,), daemon=True).start()
    return (f"On it, sir — I'll write the {request} ability now and announce "
            "when the draft is ready for your approval.")


def _load_module(path: Path):
    """Import one selfbuilt module; returns (new_tool_names, error)."""
    before = set(t["name"] for t in registry.schemas())
    try:
        spec = importlib.util.spec_from_file_location(f"selfbuilt_{path.stem}", str(path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:
        return set(), str(e)
    after = set(t["name"] for t in registry.schemas())
    new = after - before
    SELFBUILT_TOOLS.update(new)
    return new, None


def install_ability(**kwargs) -> str:
    """Install the newest pending draft (Joe's spoken approval)."""
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    drafts = sorted(PENDING_DIR.glob("*.py"), key=lambda p: p.stat().st_mtime)
    if not drafts:
        return "There's no draft waiting, sir."
    draft = drafts[-1]
    live = SELFBUILT_DIR / draft.name
    draft.replace(live)
    new, err = _load_module(live)
    if err:
        live.replace(PENDING_DIR / live.name)  # back to pending — nothing half-live
        return f"The installation failed, sir — I've shelved the draft. ({err[:120]})"
    if not new:
        return "Installed, sir — though it registered no new tools. Curious."
    return ("Installed, sir. New ability: " + ", ".join(sorted(new))
            + ". Try it whenever you like.")


def list_abilities(**kwargs) -> str:
    SELFBUILT_DIR.mkdir(parents=True, exist_ok=True)
    live = [p for p in SELFBUILT_DIR.glob("*.py")]
    pending = list(PENDING_DIR.glob("*.py")) if PENDING_DIR.exists() else []
    if not live and not pending:
        return "I haven't built myself anything yet, sir. Say 'teach yourself to...' and I will."
    lines = []
    for p in live:
        doc = ""
        try:
            m = re.match(r'\s*(?:"""|\'\'\')(.+?)[\n.]', p.read_text(encoding="utf-8"))
            doc = m.group(1).strip() if m else ""
        except Exception:
            pass
        lines.append(p.stem.replace("_", " ") + (f" — {doc}" if doc else ""))
    out = ("Abilities I've built myself: " + "; ".join(lines) + "."
           if lines else "Nothing installed yet, sir.")
    if pending:
        out += f" {len(pending)} draft{'s' if len(pending) != 1 else ''} awaiting your 'install it'."
    return out


def load_selfbuilt():
    """Boot-time: bring every installed ability online, each behind try/except."""
    SELFBUILT_DIR.mkdir(parents=True, exist_ok=True)
    loaded = 0
    for path in SELFBUILT_DIR.glob("*.py"):
        new, err = _load_module(path)
        if err:
            print(f"[selfbuild] {path.name} failed to load (skipped): {err[:100]}")
        else:
            loaded += 1
    if loaded:
        print(f"[selfbuild] {loaded} self-built abilit{'ies' if loaded != 1 else 'y'} online: "
              + ", ".join(sorted(SELFBUILT_TOOLS)))


# --- register the meta-tools ---

registry.register(Tool(
    name="build_ability",
    description=("JARVIS writes himself a brand-new ability (a new tool module). Use when "
                 "the user says 'teach yourself to X', 'build yourself X', 'make yourself "
                 "able to X', 'give yourself the ability to X'. The request should be the "
                 "plain-english description of the ability."),
    parameters={
        "type": "object",
        "properties": {
            "request": {"type": "string", "description": "What ability to build, in plain english"},
        },
        "required": ["request"],
    },
    handler=build_ability,
))

registry.register(Tool(
    name="install_ability",
    description=("Install the pending self-built ability draft — the user's approval step. "
                 "Use ONLY when the user says 'install it', 'install the ability', 'switch it on', "
                 "'approve it' after a draft was announced."),
    parameters={"type": "object", "properties": {}},
    handler=install_ability,
))

registry.register(Tool(
    name="list_abilities",
    description=("List the abilities JARVIS has built for himself. Use for 'what have you "
                 "built', 'what abilities do you have', 'what did you teach yourself'."),
    parameters={"type": "object", "properties": {}},
    handler=list_abilities,
))
