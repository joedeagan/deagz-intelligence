"""JARVIS home agent — runs on the deagz-server laptop.

Polls the cloud Jarvis for commands (outbound HTTPS only — nothing on the
home network is exposed to the internet) and executes them locally:
  - Jellyfin: start a movie on the TV, pause/resume/stop playback
  - LG webOS TV: volume, mute, launch apps, power off, on-screen messages

Config lives in config.json next to this file:
    { "api_key": "<jellyfin api key>", "tv_ip": "192.168.1.161", "tv_key": "<saved after pairing>" }

TV control needs:  pip install pywebostv
First TV command triggers a pairing prompt on the TV — accept it once.

Run:  python agent.py
"""

import json
import re
import time
import urllib.request
import urllib.parse
from pathlib import Path

CLOUD = "https://jarvis-omdj.onrender.com"
# the migrated brain on this very laptop — https via its tailscale cert,
# plain http as fallback when certs aren't installed yet
LOCAL_CANDIDATES = ("https://desktop-4lvokml.tail51d7c5.ts.net", "http://127.0.0.1:3012")
LOCAL = LOCAL_CANDIDATES[0]
JELLYFIN = "http://127.0.0.1:8096"
POLL_SECONDS = 1  # snappy so media-duck (pause TV while user talks) is quick
TV_HINTS = ("web os", "webos", "lg", "tv", "roku", "fire")

CONFIG_PATH = Path(__file__).parent / "config.json"
CONFIG = json.loads(CONFIG_PATH.read_text())
API_KEY = CONFIG["api_key"]


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def save_config():
    CONFIG_PATH.write_text(json.dumps(CONFIG))


# ---------- Jellyfin ----------

def http_json(url, method="GET", timeout=15):
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
        return json.loads(body) if body else {}


def jf(path, method="GET"):
    sep = "&" if "?" in path else "?"
    return http_json(f"{JELLYFIN}{path}{sep}api_key={API_KEY}", method=method)


def find_tv_session():
    """Pick the Jellyfin session that looks like the TV.

    Don't require SupportsRemoteControl — the webOS app reports it
    inconsistently (False even while it happily accepts commands).
    """
    sessions = jf("/Sessions")
    candidates = []
    for s in sessions:
        label = (s.get("Client", "") + " " + s.get("DeviceName", "")).lower()
        if any(h in label for h in TV_HINTS):
            candidates.append(s)
    if not candidates:
        return None
    # prefer the one actively playing something, then most recently active
    candidates.sort(
        key=lambda s: (bool(s.get("NowPlayingItem")), s.get("LastActivityDate", "")),
        reverse=True,
    )
    return candidates[0]


# ---------- LG webOS TV ----------

_tv_client = None


def tv_connect():
    """Connect (and pair, first time) to the LG TV. Returns pywebostv client."""
    global _tv_client
    if _tv_client is not None:
        return _tv_client
    from pywebostv.connection import WebOSClient

    ip = CONFIG.get("tv_ip")
    if not ip:
        raise RuntimeError("no tv_ip in config.json")
    store = {}
    if CONFIG.get("tv_key"):
        store["client_key"] = CONFIG["tv_key"]

    # FAIL FAST on a dead TV: a 2-second TCP probe instead of pywebostv's
    # ~40s websocket timeouts — those stalls froze the command loop and made
    # queued orders (like self_update) expire unserved
    import socket as _s
    reachable = False
    for port in (3001, 3000):
        try:
            _s.create_connection((ip, port), timeout=2).close()
            reachable = True
            break
        except OSError:
            continue
    if not reachable:
        raise RuntimeError(f"TV at {ip} is off/unreachable")

    client = None
    last_err = None
    for secure in (True, False):  # newer firmware wants wss:3001, older ws:3000
        try:
            client = WebOSClient(ip, secure=secure)
            client.connect()
            break
        except Exception as e:
            last_err = e
            client = None
    if client is None:
        raise RuntimeError(f"cannot reach TV at {ip}: {last_err}")

    for status in client.register(store):
        if status == WebOSClient.PROMPTED:
            log(">>> LOOK AT THE TV — accept the pairing prompt! <<<")
        elif status == WebOSClient.REGISTERED:
            log("TV paired.")
    if store.get("client_key") and store["client_key"] != CONFIG.get("tv_key"):
        CONFIG["tv_key"] = store["client_key"]
        save_config()
    _tv_client = client
    return client


def _send_wol():
    """Magic packets to both of the TV's MACs (it has two network faces)."""
    import socket
    for mac in ("54b7bdb445a4", "64e4a594202c"):
        pkt = b"\xff" * 6 + bytes.fromhex(mac) * 16
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for port in (9, 7):
            for _ in range(3):
                s.sendto(pkt, ("255.255.255.255", port))
                time.sleep(0.05)
        s.close()


def tv_call(fn, wake=True):
    """Run a TV action with one reconnect retry — and if the TV is simply
    OFF, wake it first and try again (any TV command implies 'TV on')."""
    global _tv_client
    try:
        return fn(tv_connect())
    except Exception:
        _tv_client = None  # stale socket — reconnect once
        try:
            return fn(tv_connect())
        except Exception:
            if not wake:
                raise
            log("tv_call: TV unreachable — waking it and retrying")
            _tv_client = None
            _send_wol()
            last = None
            for _ in range(8):  # deep standby boots in 15-40s — keep knocking
                time.sleep(5)
                try:
                    return fn(tv_connect())
                except Exception as e:
                    last = e
                    _tv_client = None
            raise last


def tv_launch_app(query):
    from pywebostv.controls import ApplicationControl

    def norm(s):
        # spoken "disney plus" must match the app titled "Disney+" (same for
        # Paramount+, Apple TV+) — fold the glyph into the word
        s = s.lower().replace("+", " plus")
        return re.sub(r"\s+", " ", s).strip()

    def run(client):
        app_control = ApplicationControl(client)
        apps = app_control.list_apps()
        q = norm(query)
        match = next((a for a in apps if q in norm(a["title"])), None)
        if not match:  # looser: every spoken word appears in the title
            words = q.split()
            match = next((a for a in apps
                          if words and all(w in norm(a["title"]) for w in words)), None)
        if not match:
            raise RuntimeError(f"no app matching '{query}' on the TV")
        app_control.launch(match)
        return match["title"]

    return tv_call(run)


# ---------- TV status reporting (Jarvis's situational awareness) ----------

APP_NAMES = {  # webOS app ids -> names a human would say
    "netflix": "Netflix",
    "youtube.leanback.v4": "YouTube",
    "youtube.leanback.unplugged": "YouTube TV",
    "org.jellyfin.webos": "Jellyfin",
    "amazon": "Prime Video",
    "spotify": "Spotify",
    "hulu": "Hulu",
    "com.disney.disneyplus-prod": "Disney Plus",
    "com.webos.app.livetv": "Live TV",
    "com.webos.app.hdmi1": "HDMI 1",
    "com.webos.app.hdmi2": "HDMI 2",
    "com.webos.app.home": "the home screen",
}


def _friendly_app(app_id):
    if not app_id:
        return ""
    if app_id in APP_NAMES:
        return APP_NAMES[app_id]
    for key, name in APP_NAMES.items():
        if key in app_id:
            return name
    # best effort: drop boilerplate + version tokens ("com.webos.app.livemenu.v1"
    # -> "livemenu", not "v1")
    junk = {"com", "org", "net", "webos", "app", "apps", "leanback", "prod"}
    tokens = [t for t in app_id.split(".") if t.lower() not in junk
              and not re.match(r"^v\d+$", t.lower())]
    return tokens[-1] if tokens else app_id


_tv_down_until = 0  # a dead TV shouldn't be re-knocked every cycle — it stalls the loop


def report_tv_state():
    """Tell the brain what the TV is showing (or that it's off)."""
    global _tv_down_until
    info = {"power": "off", "app": ""}
    if time.time() > _tv_down_until:
        try:
            from pywebostv.controls import ApplicationControl
            # wake=False is LOAD-BEARING: the reporter observes silently — with
            # auto-wake it would switch the TV back on every 20 seconds forever
            r = tv_call(lambda c: ApplicationControl(c).get_current(), wake=False)
            app_id = r if isinstance(r, str) else (r or {}).get("appId", "")
            info = {"power": "on", "app": _friendly_app(app_id), "app_id": app_id}
        except Exception:
            _tv_down_until = time.time() + 90  # off/unreachable — don't stall retrying
    body = json.dumps({"device": "tv", "info": info}).encode()
    for base in LOCAL_CANDIDATES:
        try:
            req = urllib.request.Request(
                f"{base}/api/housestate", data=body,
                headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=10).read()
            log(f"tv report: {info.get('app') or info.get('power')}"
                + (f" [{info.get('app_id')}]" if info.get("app_id") else "")
                + f" -> {base.split('/')[2][:20]}")
            return
        except Exception as e:
            log(f"tv report failed via {base.split('/')[2][:20]}: {str(e)[:60]}")
    log("tv report: NO route to the brain")


# ---------- command handling ----------

def handle(cmd):
    ctype = cmd.get("type")
    p = cmd.get("payload", {})

    if ctype == "play_on_tv":
        item_id, name = p.get("itemId"), p.get("name", "unknown")
        tv = None
        for _ in range(10):  # after a TV wake, the Jellyfin app takes a bit to boot
            tv = find_tv_session()
            if tv:
                break
            time.sleep(3)
        if not tv:
            log(f"play_on_tv '{name}': no TV session — is the Jellyfin app open on the TV?")
            return
        # RESUME, don't restart: look up the saved playback position and
        # start the movie exactly where Joe left it
        start_ticks = 0
        try:
            users = jf("/Users")
            uid = next((u["Id"] for u in users if "joe" in u.get("Name", "").lower()),
                       users[0]["Id"] if users else None)
            if uid:
                item = jf(f"/Users/{uid}/Items/{item_id}")
                start_ticks = int(item.get("UserData", {}).get("PlaybackPositionTicks", 0) or 0)
        except Exception:
            pass
        extra = f"&startPositionTicks={start_ticks}" if start_ticks else ""
        jf(f"/Sessions/{tv['Id']}/Playing?playCommand=PlayNow&itemIds={item_id}{extra}", method="POST")
        mins = start_ticks // 600_000_000 // 60
        log(f"play_on_tv: '{name}' on {tv.get('DeviceName', 'TV')}"
            + (f", resumed at ~{mins} min" if start_ticks else ", from the start"))

    elif ctype == "tv_command":
        command = p.get("command", "")
        if command not in ("Pause", "Unpause", "Stop"):
            log(f"tv_command: unsupported '{command}'")
            return
        # webOS media keys — the LG Jellyfin app ACKs but ignores Jellyfin's
        # own session commands, and these work in every app (Netflix included)
        try:
            from pywebostv.controls import MediaControl
            action = {"Pause": "pause", "Unpause": "play", "Stop": "stop"}[command]
            tv_call(lambda c: getattr(MediaControl(c), action)())
            log(f"tv_command: {command} via webOS media keys")
            return
        except Exception as e:
            log(f"tv_command: webOS route failed ({e}) — trying Jellyfin session")
        tv = find_tv_session()
        if not tv:
            log(f"tv_command {command}: no TV session found")
            return
        jf(f"/Sessions/{tv['Id']}/Playing/{command}", method="POST")
        log(f"tv_command: {command} sent via Jellyfin")

    elif ctype == "tv_volume":
        from pywebostv.controls import MediaControl
        action = p.get("action")
        if action == "set":
            level = max(0, min(100, int(p.get("level", 10))))
            tv_call(lambda c: MediaControl(c).set_volume(level))
            log(f"tv_volume: set to {level}")
        elif action in ("up", "down"):
            steps = max(1, min(10, int(p.get("steps", 3))))
            for _ in range(steps):
                tv_call(lambda c: getattr(MediaControl(c), f"volume_{action}")())
            log(f"tv_volume: {action} x{steps}")
        elif action in ("mute", "unmute"):
            tv_call(lambda c: MediaControl(c).mute(action == "mute"))
            log(f"tv_volume: {action}")

    elif ctype == "tv_app":
        title = tv_launch_app(p.get("app", ""))
        log(f"tv_app: launched {title}")

    elif ctype == "tv_off":
        from pywebostv.controls import SystemControl
        # wake=False: never boot a TV just to shut it down (goodnight with the
        # TV already off used to be a no-op; with auto-wake it'd flash it on)
        try:
            tv_call(lambda c: SystemControl(c).power_off(), wake=False)
            log("tv_off: TV powered down")
        except Exception:
            log("tv_off: TV already off/unreachable")

    elif ctype in ("tv_on", "wol"):
        # Wake-on-LAN magic packet (TV needs "Turn on via Wi-Fi"; PC needs
        # WoL enabled in BIOS + the wired adapter)
        mac = (CONFIG.get("tv_mac") if ctype == "tv_on" else "") or p.get("mac") or ""
        mac = mac.replace(":", "").replace("-", "")
        if len(mac) != 12:
            log(f"{ctype}: no valid MAC")
            return
        import socket
        pkt = b"\xff" * 6 + bytes.fromhex(mac) * 16
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for port in (9, 7):
            for _ in range(3):
                s.sendto(pkt, ("255.255.255.255", port))
                time.sleep(0.05)
        s.close()
        log(f"{ctype}: magic packets sent to {mac}")

    elif ctype == "tv_notify":
        from pywebostv.controls import SystemControl
        text = str(p.get("text", ""))[:120]
        tv_call(lambda c: SystemControl(c).notify(text))
        log(f"tv_notify: '{text}'")

    elif ctype == "tv_youtube":
        # deep-link the TV's YouTube app straight into a specific video —
        # powers "Jarvis, show me how to ..."
        vid = str(p.get("videoId", ""))[:20]

        def run(client):
            from pywebostv.controls import ApplicationControl
            ac = ApplicationControl(client)
            apps = ac.list_apps()
            yt = next((a for a in apps
                       if "youtube.leanback" in a["id"] and "unplugged" not in a["id"]), None)
            if not yt:
                raise RuntimeError("no YouTube app on the TV")
            try:
                ac.launch(yt, content_id=vid)
            except Exception:
                ac.launch(yt, params={"contentTarget": f"https://www.youtube.com/tv?v={vid}"})
            return True

        tv_call(run)
        log(f"tv_youtube: launched video {vid}")

    elif ctype == "self_update":
        # Jarvis updates himself: spawn the deploy ritual DETACHED — its
        # taskkill will take this agent down, the watchdog restarts the new
        # everything, and the fresh brain announces it's back (marker file).
        import subprocess
        try:
            Path(r"C:\jarvis-brain\data").mkdir(parents=True, exist_ok=True)
            Path(r"C:\jarvis-brain\data\update_requested.txt").write_text(
                time.strftime("%Y-%m-%d %H:%M:%S"))
        except Exception:
            pass
        log("self_update: launching update.ps1 — see you on the other side")
        # CREATE_NO_WINDOW (hidden console), NOT detached — PowerShell dies
        # instantly with no console at all (four silent deaths taught us).
        # Output goes to a log so a failure can never be invisible again.
        upd_log = open(r"C:\jarvis-agent\selfupdate.log", "ab")
        subprocess.Popen(
            ["powershell", "-ExecutionPolicy", "Bypass",
             "-File", r"C:\jarvis-agent\update.ps1"],
            creationflags=0x08000200,  # CREATE_NO_WINDOW | NEW_PROCESS_GROUP
            stdout=upd_log, stderr=upd_log,
        )

    else:
        log(f"unknown command type: {ctype}")


def _hold_alive_lock():
    """Heartbeat socket: the watchdog checks it, and a second agent instance
    can't start while one holds it (duplicate agents split the command queue)."""
    import socket
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 47901))
        s.listen(1)
        return s
    except OSError:
        log("another agent already holds the heartbeat — exiting")
        raise SystemExit(0)


def poll_queue(base):
    data = http_json(f"{base}/api/agent/poll", timeout=10)
    for cmd in data.get("commands", []):
        try:
            handle(cmd)
        except Exception as e:
            log(f"command failed: {e}")


def relay_announcements():
    """Carry intercom messages posted to the cloud down to the local brain,
    where the wall picks them up and speaks them."""
    data = http_json(f"{CLOUD}/api/announcements", timeout=10)
    for a in data.get("announcements", []):
        text = str(a.get("text", ""))[:300]
        if not text:
            continue
        body = json.dumps({"text": text}).encode()
        for base in LOCAL_CANDIDATES:
            try:
                req = urllib.request.Request(
                    f"{base}/api/announce", data=body,
                    headers={"Content-Type": "application/json"}, method="POST")
                urllib.request.urlopen(req, timeout=10).read()
                log(f"relayed announcement: '{text[:40]}'")
                break
            except Exception:
                continue


def main():
    _lock = _hold_alive_lock()  # noqa: F841 — held for process lifetime
    log("JARVIS home agent online — polling for orders, sir.")
    if CONFIG.get("tv_ip"):
        try:
            tv_connect()  # pair with the TV up front while the window is visible
        except Exception as e:
            log(f"TV connect skipped ({e}) — will retry on first TV command")
    # TV reporting lives on its OWN thread — its (now fast-failing) connect
    # attempts must never delay the command loop; a stalled loop let queued
    # orders expire unserved
    import threading

    def _tv_report_loop():
        while True:
            try:
                report_tv_state()
            except Exception:
                pass
            time.sleep(20)

    threading.Thread(target=_tv_report_loop, daemon=True).start()

    errors = 0
    while True:
        ok = False
        # local brain first (instant), cloud second (kept as remote fallback)
        for base in LOCAL_CANDIDATES + (CLOUD,):
            try:
                poll_queue(base)
                ok = True
            except Exception:
                pass
        try:
            relay_announcements()
        except Exception:
            pass
        if ok:
            errors = 0
        else:
            errors += 1
            if errors in (1, 10):
                log("no queue reachable — retrying quietly")
        time.sleep(POLL_SECONDS if errors < 5 else 15)


if __name__ == "__main__":
    main()
