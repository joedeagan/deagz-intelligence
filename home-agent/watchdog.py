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


def _pythonw() -> str:
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return str(pythonw) if pythonw.exists() else sys.executable


def start_agent():
    subprocess.Popen([_pythonw(), str(HERE / "agent.py")], cwd=str(HERE),
                     creationflags=CREATE_NO_WINDOW)


def start_brain():
    subprocess.Popen(
        [_pythonw(), "-m", "uvicorn", "web.server:app",
         "--host", "0.0.0.0", "--port", "3012"],
        cwd=str(BRAIN_DIR), creationflags=CREATE_NO_WINDOW)


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
