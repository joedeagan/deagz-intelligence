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


def agent_alive() -> bool:
    try:
        s = socket.create_connection(("127.0.0.1", 47901), timeout=2)
        s.close()
        return True
    except OSError:
        return False


def start_agent():
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = str(pythonw) if pythonw.exists() else sys.executable
    subprocess.Popen([exe, str(HERE / "agent.py")], cwd=str(HERE),
                     creationflags=CREATE_NO_WINDOW)


def main():
    while True:
        if not agent_alive():
            start_agent()
            time.sleep(10)  # give it a moment to claim the heartbeat
        time.sleep(60)


if __name__ == "__main__":
    main()
