"""JARVIS home agent — runs on the deagz-server laptop.

Polls the cloud Jarvis for commands (outbound HTTPS only — nothing on the
home network is exposed to the internet) and executes them locally against
Jellyfin: start a movie on the TV, pause/resume/stop playback.

Stdlib only. Config lives in config.json next to this file:
    { "api_key": "<jellyfin api key>" }

Run:  python agent.py
"""

import json
import time
import urllib.request
import urllib.parse
from pathlib import Path

CLOUD = "https://jarvis-omdj.onrender.com"
JELLYFIN = "http://127.0.0.1:8096"
POLL_SECONDS = 3
TV_HINTS = ("web os", "webos", "lg", "tv", "roku", "fire")

CONFIG = json.loads((Path(__file__).parent / "config.json").read_text())
API_KEY = CONFIG["api_key"]


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def http_json(url, method="GET", timeout=15):
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
        return json.loads(body) if body else {}


def jf(path, method="GET"):
    sep = "&" if "?" in path else "?"
    return http_json(f"{JELLYFIN}{path}{sep}api_key={API_KEY}", method=method)


def find_tv_session():
    """Pick the remote-controllable Jellyfin session that looks like the TV."""
    sessions = jf("/Sessions")
    candidates = []
    for s in sessions:
        if not s.get("SupportsRemoteControl"):
            continue
        label = (s.get("Client", "") + " " + s.get("DeviceName", "")).lower()
        if any(h in label for h in TV_HINTS):
            candidates.append(s)
    if not candidates:
        return None
    # most recently active first
    candidates.sort(key=lambda s: s.get("LastActivityDate", ""), reverse=True)
    return candidates[0]


def handle(cmd):
    ctype = cmd.get("type")
    payload = cmd.get("payload", {})

    if ctype == "play_on_tv":
        item_id = payload.get("itemId")
        name = payload.get("name", "unknown")
        tv = find_tv_session()
        if not tv:
            log(f"play_on_tv '{name}': no TV session found — is the Jellyfin app open on the TV?")
            return
        sid = tv["Id"]
        jf(f"/Sessions/{sid}/Playing?playCommand=PlayNow&itemIds={item_id}", method="POST")
        log(f"play_on_tv: started '{name}' on {tv.get('DeviceName', 'TV')}")

    elif ctype == "tv_command":
        command = payload.get("command", "")
        if command not in ("Pause", "Unpause", "Stop"):
            log(f"tv_command: unsupported '{command}'")
            return
        tv = find_tv_session()
        if not tv:
            log(f"tv_command {command}: no TV session found")
            return
        jf(f"/Sessions/{tv['Id']}/Playing/{command}", method="POST")
        log(f"tv_command: {command} sent to {tv.get('DeviceName', 'TV')}")

    else:
        log(f"unknown command type: {ctype}")


def main():
    log("JARVIS home agent online — polling for orders, sir.")
    errors = 0
    while True:
        try:
            data = http_json(f"{CLOUD}/api/agent/poll")
            errors = 0
            for cmd in data.get("commands", []):
                try:
                    handle(cmd)
                except Exception as e:
                    log(f"command failed: {e}")
        except Exception as e:
            errors += 1
            if errors in (1, 10):
                log(f"cloud unreachable ({e}) — retrying quietly")
        time.sleep(POLL_SECONDS if errors < 5 else 15)


if __name__ == "__main__":
    main()
