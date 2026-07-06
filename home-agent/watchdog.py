"""JARVIS agent watchdog — keeps the home agent alive forever.

Runs hidden at logon (the Startup .bat launches THIS, and this launches
the agent). Every 60 seconds it checks the agent's heartbeat socket and
resurrects the agent if it has died. Stdlib only.
"""

import socket
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
CREATE_NO_WINDOW = 0x08000000


BRAIN_DIR = Path("C:/jarvis-brain")


def port_alive(port: int) -> bool:
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=2)
        s.close()
        return True
    except OSError:
        return False


def _python() -> str:
    # console python + CREATE_NO_WINDOW: hidden, but stdout still EXISTS —
    # uvicorn crashes instantly under pythonw's void stdout
    py = Path(sys.executable).with_name("python.exe")
    return str(py) if py.exists() else sys.executable


def start_agent():
    logf = open(HERE / "agent.log", "ab")
    subprocess.Popen([_python(), str(HERE / "agent.py")], cwd=str(HERE),
                     creationflags=CREATE_NO_WINDOW, stdout=logf, stderr=logf)


BRAIN_PORT = 3012  # http fallback; with tailscale certs present we serve https:443


def _brain_tls():
    """If tailscale-issued cert/key sit in the brain dir, serve HTTPS directly
    on 443 — the tailscale serve proxy chokes on large audio responses."""
    certs = sorted(BRAIN_DIR.glob("*.ts.net.crt"))
    keys = sorted(BRAIN_DIR.glob("*.ts.net.key"))
    if certs and keys:
        return certs[0], keys[0]
    return None, None


def brain_port() -> int:
    crt, key = _brain_tls()
    return 443 if crt and key else BRAIN_PORT


def start_brain():
    logf = open(BRAIN_DIR / "brain.log", "ab")
    crt, key = _brain_tls()
    args = [_python(), "-m", "uvicorn", "web.server:app", "--host", "0.0.0.0"]
    if crt and key:
        args += ["--port", "443", "--ssl-certfile", str(crt), "--ssl-keyfile", str(key)]
    else:
        args += ["--port", str(BRAIN_PORT)]
    subprocess.Popen(args, cwd=str(BRAIN_DIR),
                     creationflags=CREATE_NO_WINDOW, stdout=logf, stderr=logf)


def main():
    while True:
        if not port_alive(47901):           # agent heartbeat
            start_agent()
            time.sleep(10)
        if BRAIN_DIR.exists() and not port_alive(brain_port()):  # the migrated brain
            start_brain()
            time.sleep(15)
        time.sleep(60)


if __name__ == "__main__":
    main()
