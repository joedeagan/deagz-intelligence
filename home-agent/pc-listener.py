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
import subprocess
import time
import urllib.request
from pathlib import Path

CLOUD = "https://jarvis-omdj.onrender.com"
LOCAL = "https://desktop-4lvokml.tail51d7c5.ts.net"  # the brain, via tailscale
POLL_SECONDS = 3
HERE = Path(__file__).parent

CFG = {}
try:
    CFG = json.loads((HERE / "config.json").read_text())
except Exception:
    pass
USER_APPS = {k.lower(): v for k, v in (CFG.get("apps") or {}).items()}

# best-effort common app resolution (extended by config)
KNOWN_APPS = {
    "steam": [r"C:\Program Files (x86)\Steam\steam.exe"],
    "discord": [os.path.expandvars(r"%LOCALAPPDATA%\Discord\Update.exe")],
    "spotify": [os.path.expandvars(r"%APPDATA%\Spotify\Spotify.exe")],
    "chrome": [r"C:\Program Files\Google\Chrome\Application\chrome.exe"],
    "epic": [r"C:\Program Files (x86)\Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe"],
    "obs": [r"C:\Program Files\obs-studio\bin\64bit\obs64.exe"],
}


def log(m):
    print(time.strftime("%H:%M:%S"), m, flush=True)


def http_json(url, timeout=10):
    with urllib.request.urlopen(url, timeout=timeout) as r:
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
        if pth and os.path.exists(pth):
            subprocess.Popen([pth])
            log(f"launched {name}")
            return
    # fallback: let Windows try to resolve it (Steam URIs, PATH apps, etc.)
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


def main():
    log("JARVIS PC listener online.")
    while True:
        for base in (LOCAL, CLOUD):
            try:
                poll(base)
            except Exception:
                pass
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
