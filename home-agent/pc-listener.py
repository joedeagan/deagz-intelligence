"""JARVIS PC listener — runs on the desktop PC.

Polls the same command queue the home agent uses and executes local PC
controls: lock, sleep, shut down, restart, launch apps. Wake-on-LAN
(power ON from off) is handled by the always-on home agent, not here.

Stdlib only. Config in config.json next to this file:
    { "apps": { "steam": "C:\\\\Program Files (x86)\\\\Steam\\\\steam.exe" } }
(apps is optional; common ones are auto-resolved.)

Run hidden at logon; see setup steps.
"""

import json
import os
import ssl
import subprocess
import time
import urllib.request
from pathlib import Path

CLOUD = "https://jarvis-omdj.onrender.com"
# the brain, nearest road first: straight across the house LAN (no VPN
# dependency — tailscale being off on this PC once silenced everything),
# then tailscale, then cloud
BRAIN_BASES = ("https://192.168.1.73", "https://desktop-4lvokml.tail51d7c5.ts.net", CLOUD)
# the brain's cert names the ts.net host — the LAN IP won't match it
_SSL = ssl._create_unverified_context()
POLL_SECONDS = 3
HERE = Path(__file__).parent

CFG = {}
try:
    CFG = json.loads((HERE / "config.json").read_text())
except Exception:
    pass
USER_APPS = {k.lower(): v for k, v in (CFG.get("apps") or {}).items()}

# best-effort common app resolution (extended by config). A value containing
# "://" is a launch URI (games via their launcher) and is opened directly.
KNOWN_APPS = {
    "steam": [r"C:\Program Files (x86)\Steam\steam.exe"],
    "discord": [os.path.expandvars(r"%LOCALAPPDATA%\Discord\Update.exe")],
    "spotify": [os.path.expandvars(r"%APPDATA%\Spotify\Spotify.exe")],
    "chrome": [r"C:\Program Files\Google\Chrome\Application\chrome.exe"],
    "epic": [r"C:\Program Files (x86)\Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe"],
    "obs": [r"C:\Program Files\obs-studio\bin\64bit\obs64.exe"],
    "fortnite": ["com.epicgames.launcher://apps/Fortnite?action=launch&silent=true"],
    "rocket league": ["com.epicgames.launcher://apps/Sugar?action=launch&silent=true"],
    "roblox": ["roblox://"],
    "minecraft": ["minecraft://"],
    "valorant": [os.path.expandvars(r"%PROGRAMFILES%\Riot Games\Riot Client\RiotClientServices.exe")],
}


def _launch_target(pth):
    if "://" in pth:  # a launch URI — open it directly, no file check
        os.startfile(pth)
        return True
    if os.path.exists(pth):
        subprocess.Popen([pth])
        return True
    return False


def log(m):
    print(time.strftime("%H:%M:%S"), m, flush=True)


def http_json(url, timeout=10):
    with urllib.request.urlopen(url, timeout=timeout, context=_SSL) as r:
        body = r.read()
        return json.loads(body) if body else {}


def launch_app(name):
    name = (name or "").strip().lower()
    if not name:
        return
    paths = []
    if name in USER_APPS:
        paths = [USER_APPS[name]]
    elif name in KNOWN_APPS:
        paths = KNOWN_APPS[name]
    for pth in paths:
        try:
            if pth and _launch_target(pth):
                log(f"launched {name}")
                return
        except Exception as e:
            log(f"launch error for {name}: {e}")
    # fallback: let Windows try to resolve it (PATH apps, protocols, etc.)
    try:
        os.startfile(name)
        log(f"startfile {name}")
    except Exception as e:
        log(f"launch failed for {name}: {e}")


def handle(cmd):
    t = cmd.get("type")
    p = cmd.get("payload", {})
    if t == "pc_lock":
        subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"])
        log("locked")
    elif t == "pc_sleep":
        subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
        log("sleeping")
    elif t == "pc_shutdown":
        subprocess.run(["shutdown", "/s", "/t", "5"])
        log("shutting down")
    elif t == "pc_restart":
        subprocess.run(["shutdown", "/r", "/t", "5"])
        log("restarting")
    elif t == "pc_cancel":
        subprocess.run(["shutdown", "/a"])
        log("shutdown cancelled")
    elif t == "pc_launch":
        launch_app(p.get("app", ""))
    # pc_on (WoL) is handled by the always-on home agent, not here


def poll(base):
    for cmd in http_json(f"{base}/api/pc/poll").get("commands", []):
        try:
            handle(cmd)
        except Exception as e:
            log(f"command failed: {e}")


def foreground_window():
    """Title of whatever window is focused - 'Fortnite', 'chrome - YouTube'..."""
    try:
        import ctypes
        u = ctypes.windll.user32
        h = u.GetForegroundWindow()
        n = u.GetWindowTextLengthW(h)
        buf = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(h, buf, n + 1)
        return buf.value
    except Exception:
        return ""


def report_state():
    """Tell the brain this PC is alive and what's on screen - Jarvis's
    situational awareness ('is my pc on?' / 'what am I playing?')."""
    body = json.dumps({"device": "pc", "info": {"window": foreground_window()[:80]}}).encode()
    for base in BRAIN_BASES[:2]:  # LAN first, tailscale second — never the cloud
        try:
            req = urllib.request.Request(
                f"{base}/api/housestate", data=body,
                headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=10, context=_SSL).read()
            return
        except Exception:
            continue


def _single_instance():
    """Hold a localhost port so a second listener can't stack up and steal
    commands off the shared queue (that caused a 4-listener pileup)."""
    import socket
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 47902))
        s.listen(1)
        return s
    except OSError:
        log("another PC listener is already running — exiting")
        raise SystemExit(0)


def main():
    _lock = _single_instance()  # noqa: F841 — held for process lifetime
    log("JARVIS PC listener online.")
    beat = 0
    while True:
        for base in BRAIN_BASES:
            try:
                poll(base)
            except Exception:
                pass
        beat += 1
        if beat % 5 == 0:  # every ~15s: report presence + foreground window
            try:
                report_state()
            except Exception:
                pass
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
