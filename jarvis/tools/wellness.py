"""Wellness - Jarvis protects his own life, and can tell you how he feels.

BACKUPS: everything that makes him HIM lives in data/ (memories, moments,
portraits, dream log) and jarvis/tools/selfbuilt/ (abilities he wrote).
Weekly - or on "back yourself up" - it's zipped into backups/ (keep 8),
and the desktop PC is asked to pull a copy across the LAN (kept there too),
so a dead laptop drive no longer means he forgets Joe.

HEALTH: "Jarvis, how are you?" -> a real self-examination: uptime, which
background minds are alive, the agent heartbeat, ears, disk, house links,
last backup/dream/reflection, what he's accumulated.
"""

import datetime
import io
import json
import os
import socket
import threading
import time
import zipfile
from pathlib import Path

from jarvis.tools.base import Tool, registry

ROOT = Path(__file__).parent.parent.parent
DATA_DIR = ROOT / "data"
SELFBUILT_DIR = Path(__file__).parent / "selfbuilt"
BACKUP_DIR = ROOT / "backups"
KEEP = 8

_BOOT = time.time()
_running = False
_request_pc_pull = None  # set by the server - enqueues a pc_backup_pull


def make_backup() -> str:
    """Zip the soul: data/ + selfbuilt abilities. Returns the zip path."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    name = "jarvis-mem-" + datetime.datetime.now().strftime("%Y%m%d-%H%M") + ".zip"
    path = BACKUP_DIR / name
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for base, arcroot in ((DATA_DIR, "data"), (SELFBUILT_DIR, "selfbuilt")):
            if not base.exists():
                continue
            for f in base.rglob("*"):
                if (f.is_file() and "tts_cache" not in f.parts and "backups" not in f.parts
                        and "__pycache__" not in f.parts and f.suffix != ".pyc"):
                    z.write(f, arcroot + "/" + str(f.relative_to(base)))
    zips = sorted(BACKUP_DIR.glob("jarvis-mem-*.zip"))
    for old in zips[:-KEEP]:
        old.unlink(missing_ok=True)
    if _request_pc_pull:
        try:
            _request_pc_pull()  # desktop grabs a copy if it's on
        except Exception:
            pass
    return str(path)


def latest_backup():
    zips = sorted(BACKUP_DIR.glob("jarvis-mem-*.zip")) if BACKUP_DIR.exists() else []
    return zips[-1] if zips else None


def backup_now(**kwargs) -> str:
    try:
        path = make_backup()
        kb = Path(path).stat().st_size // 1024
        return (f"Done - memories sealed into a {kb} KB archive, "
                f"and I've asked the desktop to keep a copy as well.")
    except Exception as e:
        return f"The backup failed: {str(e)[:80]}"


def _age(ts: float) -> str:
    s = int(time.time() - ts)
    if s < 3600:
        return f"{s // 60} minutes"
    if s < 86400:
        return f"{s // 3600} hours"
    return f"{s // 86400} days"


def health_report(**kwargs) -> str:
    bits = []

    # uptime + background minds
    up = _age(_BOOT)
    names = {t.name for t in threading.enumerate()}
    minds = [n for n in ("jarvis-mind", "jarvis-observer", "jarvis-gameday",
                         "jarvis-dreams", "jarvis-reflection") if n in names]
    bits.append(f"Brain up {up}, {len(minds)} of 5 background minds running"
                + ("" if len(minds) == 5 else f" (missing: {', '.join(n.replace('jarvis-', '') for n in set(('jarvis-mind', 'jarvis-observer', 'jarvis-gameday', 'jarvis-dreams', 'jarvis-reflection')) - names)})"))

    # the home agent heartbeat
    try:
        s = socket.create_connection(("127.0.0.1", 47901), timeout=2)
        s.close()
        bits.append("home agent alive")
    except OSError:
        bits.append("home agent NOT responding")

    # ears
    try:
        from jarvis.tools import ears
        bits.append("local ears loaded" if ears._model is not None else "local ears not yet warmed")
    except Exception:
        pass

    # the house
    try:
        from jarvis.tools.housestate import snapshot
        hs = snapshot()
        if hs:
            bits.append(hs)
    except Exception:
        pass

    # disk
    try:
        import shutil
        free_gb = shutil.disk_usage("C:\\").free // (1024 ** 3)
        bits.append(f"{free_gb} GB free" + (" - getting tight" if free_gb < 15 else ""))
    except Exception:
        pass

    # last backup / dream / reflection
    lb = latest_backup()
    bits.append("last memory backup " + (_age(lb.stat().st_mtime) + " ago" if lb else "NEVER - worth running one"))
    try:
        dream = json.loads((DATA_DIR / "dream_log.json").read_text(encoding="utf-8"))
        if dream.get("last_run"):
            bits.append(f"last self-review {dream['last_run']}")
    except Exception:
        pass

    # what he's accumulated
    try:
        moments = json.loads((DATA_DIR / "memory" / "moments.json").read_text(encoding="utf-8"))
        built = len(list(SELFBUILT_DIR.glob("*.py"))) if SELFBUILT_DIR.exists() else 0
        bits.append(f"{len(moments)} sealed moment{'s' if len(moments) != 1 else ''}, "
                    f"{built} self-built abilit{'ies' if built != 1 else 'y'}")
    except Exception:
        pass

    return "; ".join(bits) + "."


def _loop():
    time.sleep(300)
    while True:
        try:
            lb = latest_backup()
            if lb is None or time.time() - lb.stat().st_mtime > 6 * 86400:
                path = make_backup()
                print(f"[wellness] weekly backup written: {path}")
        except Exception as e:
            print(f"[wellness] backup loop failed: {e}")
        time.sleep(6 * 3600)  # re-check four times a day


def start_wellness(request_pc_pull=None):
    global _running, _request_pc_pull
    _request_pc_pull = request_pc_pull
    if _running:
        return
    _running = True
    threading.Thread(target=_loop, daemon=True, name="jarvis-wellness").start()


registry.register(Tool(
    name="health_report",
    description=("Jarvis's self-examination. ALWAYS use when the user asks 'how are you', "
                 "'how are you feeling', 'status report', 'system check', 'are you okay', "
                 "'health check'. Summarize the result conversationally, don't read it verbatim."),
    parameters={"type": "object", "properties": {}},
    handler=health_report,
))

registry.register(Tool(
    name="backup_now",
    description=("Back up Jarvis's memories and self-built abilities right now. Use for "
                 "'back yourself up', 'backup your memory', 'save your memories'."),
    parameters={"type": "object", "properties": {}},
    handler=backup_now,
))
