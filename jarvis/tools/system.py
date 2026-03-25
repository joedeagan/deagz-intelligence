"""System tools — time, weather, open apps, reminders, file operations."""

import os
import subprocess
import datetime
import json
from pathlib import Path

import httpx

from jarvis.config import DEFAULT_CITY
from jarvis.tools.base import Tool, registry

REMINDERS_FILE = Path(__file__).parent.parent.parent / "data" / "reminders.json"


def get_current_time(**kwargs) -> str:
    now = datetime.datetime.now()
    return now.strftime("%A, %B %d, %Y at %I:%M %p")


WEATHER_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "depositing rime fog",
    51: "light drizzle", 53: "moderate drizzle", 55: "dense drizzle",
    61: "slight rain", 63: "moderate rain", 65: "heavy rain",
    71: "slight snow", 73: "moderate snow", 75: "heavy snow",
    80: "slight rain showers", 81: "moderate rain showers", 82: "violent rain showers",
    95: "thunderstorm", 96: "thunderstorm with slight hail", 99: "thunderstorm with heavy hail",
}


def get_weather(city: str = "", when: str = "today") -> str:
    """Fetch weather from Open-Meteo. Supports today, tomorrow, or multi-day forecast."""
    if not city:
        city = DEFAULT_CITY
    # Geocode city
    geo = httpx.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": city, "count": 1},
    ).json()

    if not geo.get("results"):
        return f"Could not find weather data for {city}."

    loc = geo["results"][0]
    lat, lon = loc["latitude"], loc["longitude"]

    weather = httpx.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,weathercode,windspeed_10m,relative_humidity_2m",
            "daily": "weathercode,temperature_2m_max,temperature_2m_min,precipitation_probability_max,windspeed_10m_max",
            "temperature_unit": "fahrenheit",
            "windspeed_unit": "mph",
            "forecast_days": 7,
        },
    ).json()

    lines = []

    if when == "today" or when == "now":
        cur = weather.get("current", {})
        temp = cur.get("temperature_2m", "?")
        wind = cur.get("windspeed_10m", "?")
        humidity = cur.get("relative_humidity_2m", "?")
        desc = WEATHER_CODES.get(cur.get("weathercode", 0), "unknown")
        lines.append(f"Right now in {loc['name']}: {temp}F, {desc}, wind {wind} mph, humidity {humidity}%.")

        # Also include today's high/low
        daily = weather.get("daily", {})
        if daily.get("temperature_2m_max"):
            hi = daily["temperature_2m_max"][0]
            lo = daily["temperature_2m_min"][0]
            rain = daily.get("precipitation_probability_max", [0])[0]
            lines.append(f"Today's forecast: high {hi}F, low {lo}F, {rain}% chance of rain.")

    elif when == "tomorrow":
        daily = weather.get("daily", {})
        if daily.get("temperature_2m_max") and len(daily["temperature_2m_max"]) > 1:
            hi = daily["temperature_2m_max"][1]
            lo = daily["temperature_2m_min"][1]
            code = daily.get("weathercode", [0, 0])[1]
            desc = WEATHER_CODES.get(code, "unknown")
            rain = daily.get("precipitation_probability_max", [0, 0])[1]
            wind = daily.get("windspeed_10m_max", [0, 0])[1]
            date = daily["time"][1]
            lines.append(f"Tomorrow ({date}) in {loc['name']}: {desc}.")
            lines.append(f"High {hi}F, low {lo}F, wind up to {wind} mph, {rain}% chance of rain.")

    elif when == "week":
        daily = weather.get("daily", {})
        lines.append(f"7-day forecast for {loc['name']}:")
        for i in range(min(7, len(daily.get("time", [])))):
            date = daily["time"][i]
            hi = daily["temperature_2m_max"][i]
            lo = daily["temperature_2m_min"][i]
            code = daily.get("weathercode", [0])[i]
            desc = WEATHER_CODES.get(code, "unknown")
            rain = daily.get("precipitation_probability_max", [0])[i]
            lines.append(f"  {date}: {desc}, {hi}F/{lo}F, {rain}% rain")

    else:
        # Default to today
        return get_weather(city, "today")

    return "\n".join(lines)


def open_application(name: str) -> str:
    """Open an application by name on Windows."""
    app_map = {
        "chrome": "chrome",
        "google chrome": "chrome",
        "browser": "chrome",
        "notepad": "notepad",
        "calculator": "calc",
        "file explorer": "explorer",
        "explorer": "explorer",
        "terminal": "wt",
        "command prompt": "cmd",
        "cmd": "cmd",
        "spotify": "spotify",
        "discord": "discord",
        "slack": "slack",
        "vscode": "code",
        "vs code": "code",
        "visual studio code": "code",
    }

    key = name.lower().strip()
    exe = app_map.get(key, key)

    try:
        subprocess.Popen(
            f"start {exe}", shell=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return f"Opening {name}."
    except Exception as e:
        return f"Failed to open {name}: {e}"


def set_reminder(message: str, minutes: int = 0) -> str:
    """Save a reminder. If minutes > 0, it's a timed reminder."""
    REMINDERS_FILE.parent.mkdir(parents=True, exist_ok=True)

    reminders = []
    if REMINDERS_FILE.exists():
        reminders = json.loads(REMINDERS_FILE.read_text())

    now = datetime.datetime.now()
    reminder = {
        "message": message,
        "created": now.isoformat(),
        "due": (now + datetime.timedelta(minutes=minutes)).isoformat() if minutes > 0 else None,
    }
    reminders.append(reminder)
    REMINDERS_FILE.write_text(json.dumps(reminders, indent=2))

    if minutes > 0:
        return f"Reminder set: '{message}' in {minutes} minutes."
    return f"Reminder saved: '{message}'."


def list_reminders() -> str:
    """List all saved reminders."""
    if not REMINDERS_FILE.exists():
        return "No reminders set."

    reminders = json.loads(REMINDERS_FILE.read_text())
    if not reminders:
        return "No reminders set."

    lines = []
    for i, r in enumerate(reminders, 1):
        due = f" (due: {r['due']})" if r.get("due") else ""
        lines.append(f"{i}. {r['message']}{due}")
    return "\n".join(lines)


def web_search(query: str) -> str:
    """Search the web using DuckDuckGo instant answers (free, no key)."""
    resp = httpx.get(
        "https://api.duckduckgo.com/",
        params={"q": query, "format": "json", "no_html": 1},
        timeout=10,
    ).json()

    abstract = resp.get("AbstractText", "")
    if abstract:
        return abstract

    # Try related topics
    related = resp.get("RelatedTopics", [])
    if related:
        results = []
        for topic in related[:3]:
            if isinstance(topic, dict) and "Text" in topic:
                results.append(topic["Text"])
        if results:
            return " | ".join(results)

    return f"No instant answer found for '{query}'. Try asking me to search more specifically."


def run_command(command: str) -> str:
    """Run a shell command on the computer and return the output."""
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=30,
        )
        output = result.stdout.strip()
        if result.returncode != 0 and result.stderr:
            output += f"\nError: {result.stderr.strip()}"
        return output if output else "Command completed with no output."
    except subprocess.TimeoutExpired:
        return "Command timed out after 30 seconds."
    except Exception as e:
        return f"Failed to run command: {e}"


def open_url(url: str) -> str:
    """Open a URL in the default web browser."""
    try:
        if not url.startswith("http"):
            url = "https://" + url
        import webbrowser
        webbrowser.open(url)
        return f"Opening {url} in your browser."
    except Exception as e:
        return f"Failed to open URL: {e}"


def read_file(path: str) -> str:
    """Read the contents of a file."""
    try:
        p = Path(path).expanduser()
        if not p.exists():
            return f"File not found: {path}"
        content = p.read_text(encoding="utf-8", errors="replace")
        if len(content) > 2000:
            return content[:2000] + f"\n... (truncated, {len(content)} chars total)"
        return content
    except Exception as e:
        return f"Failed to read file: {e}"


def write_file(path: str, content: str) -> str:
    """Write content to a file. Creates the file if it doesn't exist."""
    try:
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Written to {path}."
    except Exception as e:
        return f"Failed to write file: {e}"


def list_directory(path: str = ".") -> str:
    """List files and folders in a directory."""
    try:
        p = Path(path).expanduser()
        if not p.exists():
            return f"Directory not found: {path}"
        items = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        lines = []
        for item in items[:50]:
            prefix = "[DIR] " if item.is_dir() else "      "
            size = ""
            if item.is_file():
                s = item.stat().st_size
                if s > 1_000_000:
                    size = f" ({s / 1_000_000:.1f} MB)"
                elif s > 1000:
                    size = f" ({s / 1000:.0f} KB)"
            lines.append(f"{prefix}{item.name}{size}")
        result = "\n".join(lines)
        if len(items) > 50:
            result += f"\n... and {len(items) - 50} more items"
        return result
    except Exception as e:
        return f"Failed to list directory: {e}"


def kill_process(name: str) -> str:
    """Kill a running process by name."""
    try:
        result = subprocess.run(
            f'taskkill /IM "{name}" /F',
            shell=True, capture_output=True, text=True,
        )
        if result.returncode == 0:
            return f"Killed {name}."
        return f"Could not kill {name}: {result.stderr.strip()}"
    except Exception as e:
        return f"Failed: {e}"


def get_system_info() -> str:
    """Get basic system information — CPU, memory, disk usage."""
    try:
        lines = []
        # CPU
        cpu = subprocess.run(
            'wmic cpu get name /value', shell=True, capture_output=True, text=True
        ).stdout.strip()
        for line in cpu.split("\n"):
            if "Name=" in line:
                lines.append(f"CPU: {line.split('=', 1)[1].strip()}")

        # Memory
        mem = subprocess.run(
            'wmic os get FreePhysicalMemory,TotalVisibleMemorySize /value',
            shell=True, capture_output=True, text=True,
        ).stdout.strip()
        total = free = 0
        for line in mem.split("\n"):
            if "TotalVisibleMemorySize=" in line:
                total = int(line.split("=")[1].strip()) / 1024 / 1024
            if "FreePhysicalMemory=" in line:
                free = int(line.split("=")[1].strip()) / 1024 / 1024
        if total > 0:
            used = total - free
            lines.append(f"RAM: {used:.1f} GB used / {total:.1f} GB total")

        # Disk
        disk = subprocess.run(
            'wmic logicaldisk where "DeviceID=\'C:\'" get FreeSpace,Size /value',
            shell=True, capture_output=True, text=True,
        ).stdout.strip()
        d_total = d_free = 0
        for line in disk.split("\n"):
            if "Size=" in line:
                d_total = int(line.split("=")[1].strip()) / 1024**3
            if "FreeSpace=" in line:
                d_free = int(line.split("=")[1].strip()) / 1024**3
        if d_total > 0:
            lines.append(f"Disk C: {d_free:.0f} GB free / {d_total:.0f} GB total")

        # Battery
        batt = subprocess.run(
            'wmic path win32_battery get EstimatedChargeRemaining /value',
            shell=True, capture_output=True, text=True,
        ).stdout.strip()
        for line in batt.split("\n"):
            if "EstimatedChargeRemaining=" in line:
                lines.append(f"Battery: {line.split('=')[1].strip()}%")

        return "\n".join(lines) if lines else "Could not retrieve system info."
    except Exception as e:
        return f"Failed: {e}"


def set_volume(level: int) -> str:
    """Set system volume (0-100)."""
    try:
        level = max(0, min(100, level))
        # Convert 0-100 to 0-65535
        val = int(level / 100 * 65535)
        subprocess.run(
            f'powershell -Command "(New-Object -ComObject WScript.Shell).SendKeys([char]173)"',
            shell=True, capture_output=True,
        )
        # Use nircmd if available, otherwise PowerShell
        subprocess.run(
            f'powershell -Command "Set-AudioDevice -PlaybackVolume {level}"',
            shell=True, capture_output=True,
        )
        return f"Volume set to {level}%."
    except Exception as e:
        return f"Failed to set volume: {e}"


def screenshot() -> str:
    """Take a screenshot and save it to the desktop."""
    try:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = f"C:\\Users\\brian\\Desktop\\screenshot_{ts}.png"
        subprocess.run(
            f'powershell -Command "Add-Type -AssemblyName System.Windows.Forms; '
            f"[System.Windows.Forms.Screen]::PrimaryScreen | ForEach-Object {{ "
            f"$bmp = New-Object System.Drawing.Bitmap($_.Bounds.Width, $_.Bounds.Height); "
            f"$gfx = [System.Drawing.Graphics]::FromImage($bmp); "
            f"$gfx.CopyFromScreen($_.Bounds.Location, [System.Drawing.Point]::Empty, $_.Bounds.Size); "
            f"$bmp.Save('{path}'); "
            f'$gfx.Dispose(); $bmp.Dispose() }}"',
            shell=True, check=True, timeout=10,
        )
        return f"Screenshot saved to {path}."
    except Exception as e:
        return f"Failed to take screenshot: {e}"


# Register all tools
registry.register(Tool(
    name="get_current_time",
    description="Get the current date and time.",
    parameters={"type": "object", "properties": {}, "required": []},
    handler=get_current_time,
))

registry.register(Tool(
    name="get_weather",
    description="Get weather for a city. Supports current conditions, tomorrow's forecast, or a 7-day outlook.",
    parameters={
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "City name (e.g. 'San Francisco'). Defaults to New York."},
            "when": {"type": "string", "description": "'today' for current + today's forecast, 'tomorrow' for tomorrow, 'week' for 7-day outlook. Defaults to 'today'."},
        },
        "required": [],
    },
    handler=get_weather,
))

registry.register(Tool(
    name="open_application",
    description="Open an application on the user's computer (Windows). Examples: Chrome, Notepad, VS Code, Spotify, Discord, Calculator.",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Application name to open"},
        },
        "required": ["name"],
    },
    handler=open_application,
))

registry.register(Tool(
    name="set_reminder",
    description="Save a reminder, optionally with a delay in minutes.",
    parameters={
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": "The reminder message"},
            "minutes": {"type": "integer", "description": "Minutes from now (0 = no specific time)"},
        },
        "required": ["message"],
    },
    handler=set_reminder,
))

registry.register(Tool(
    name="list_reminders",
    description="List all saved reminders.",
    parameters={"type": "object", "properties": {}, "required": []},
    handler=list_reminders,
))

registry.register(Tool(
    name="web_search",
    description="Search the web for information using DuckDuckGo. Good for quick facts, definitions, and current events.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query"},
        },
        "required": ["query"],
    },
    handler=web_search,
))

registry.register(Tool(
    name="run_command",
    description="Run a shell command on the user's Windows computer and return the output. Use for any system task: checking processes, network info, installing software, etc.",
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The shell command to run"},
        },
        "required": ["command"],
    },
    handler=run_command,
))

registry.register(Tool(
    name="open_url",
    description="Open a URL in the default web browser.",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The URL to open"},
        },
        "required": ["url"],
    },
    handler=open_url,
))

registry.register(Tool(
    name="read_file",
    description="Read the contents of a file on the computer.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Full file path to read"},
        },
        "required": ["path"],
    },
    handler=read_file,
))

registry.register(Tool(
    name="write_file",
    description="Write content to a file. Creates the file if it doesn't exist.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Full file path to write"},
            "content": {"type": "string", "description": "Content to write"},
        },
        "required": ["path", "content"],
    },
    handler=write_file,
))

registry.register(Tool(
    name="list_directory",
    description="List files and folders in a directory.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory path (default: current directory)"},
        },
        "required": [],
    },
    handler=list_directory,
))

registry.register(Tool(
    name="kill_process",
    description="Kill a running process by name (e.g. 'chrome.exe', 'notepad.exe').",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Process name to kill (e.g. 'chrome.exe')"},
        },
        "required": ["name"],
    },
    handler=kill_process,
))

registry.register(Tool(
    name="get_system_info",
    description="Get system information — CPU, RAM usage, disk space, battery level.",
    parameters={"type": "object", "properties": {}, "required": []},
    handler=get_system_info,
))

registry.register(Tool(
    name="screenshot",
    description="Take a screenshot of the screen and save it to the desktop.",
    parameters={"type": "object", "properties": {}, "required": []},
    handler=screenshot,
))
