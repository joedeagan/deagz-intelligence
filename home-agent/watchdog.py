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


def start_brain():
    logf = open(BRAIN_DIR / "brain.log", "ab")
    subprocess.Popen(
        [_python(), "-m", "uvicorn", "web.server:app",
         "--host", "0.0.0.0", "--port", "3012"],
        cwd=str(BRAIN_DIR), creationflags=CREATE_NO_WINDOW, stdout=logf, stderr=logf)


def main():
    while True:
        if not port_alive(47901):           # agent heartbeat
            start_agent()
            time.sleep(10)
        if BRAIN_DIR.exists() and not port_alive(3012):  # the migrated brain
            start_brain()
            time.sleep(15)
        time.sleep(60)


if __name__ == "__main__":
    main()
