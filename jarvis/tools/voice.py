"""Voice management tools — clone voices, switch voices, list available voices."""

import json
from pathlib import Path

import httpx

from jarvis.config import ELEVENLABS_API_KEY
from jarvis.tools.base import Tool, registry

VOICE_CONFIG = Path(__file__).parent.parent.parent / "data" / "voice_config.json"


def _load_voice_config() -> dict:
    if VOICE_CONFIG.exists():
        return json.loads(VOICE_CONFIG.read_text(encoding="utf-8"))
    return {
        "active_voice_id": "onwK4e9ZLuTAKqWW03F9",  # Daniel (default)
        "active_voice_name": "Daniel",
        "custom_voices": {},
    }


def _save_voice_config(config: dict):
    VOICE_CONFIG.write_text(json.dumps(config, indent=2), encoding="utf-8")


def list_voices(**kwargs) -> str:
    """List all available ElevenLabs voices."""
    if not ELEVENLABS_API_KEY:
        return "ElevenLabs API key not configured."

    try:
        resp = httpx.get(
            "https://api.elevenlabs.io/v1/voices",
            headers={"xi-api-key": ELEVENLABS_API_KEY},
            timeout=15,
        )
        if resp.status_code != 200:
            return f"Failed to fetch voices: {resp.status_code}"

        voices = resp.json().get("voices", [])
        config = _load_voice_config()
        active_id = config.get("active_voice_id", "")

        lines = ["Available voices:"]
        for v in voices:
            marker = " ← ACTIVE" if v["voice_id"] == active_id else ""
            category = v.get("category", "unknown")
            labels = v.get("labels", {})
            accent = labels.get("accent", "")
            gender = labels.get("gender", "")
            desc = f"{accent} {gender}".strip()
            lines.append(f"- {v['name']} ({desc}, {category}){marker}")

        # Also show custom cloned voices
        custom = config.get("custom_voices", {})
        if custom:
            lines.append("\nCustom cloned voices:")
            for name, vid in custom.items():
                marker = " ← ACTIVE" if vid == active_id else ""
                lines.append(f"- {name} (cloned){marker}")

        return "\n".join(lines)
    except Exception as e:
        return f"Error listing voices: {e}"


def switch_voice(voice_name: str = "", **kwargs) -> str:
    """Switch the active TTS voice by name."""
    if not voice_name:
        return "Please specify a voice name."
    if not ELEVENLABS_API_KEY:
        return "ElevenLabs API key not configured."

    config = _load_voice_config()

    # Check custom voices first
    custom = config.get("custom_voices", {})
    for name, vid in custom.items():
        if name.lower() == voice_name.lower():
            config["active_voice_id"] = vid
            config["active_voice_name"] = name
            _save_voice_config(config)
            return f"Switched to voice: {name}. Future responses will use this voice."

    # Search ElevenLabs library
    try:
        resp = httpx.get(
            "https://api.elevenlabs.io/v1/voices",
            headers={"xi-api-key": ELEVENLABS_API_KEY},
            timeout=15,
        )
        voices = resp.json().get("voices", [])
        for v in voices:
            if v["name"].lower() == voice_name.lower():
                config["active_voice_id"] = v["voice_id"]
                config["active_voice_name"] = v["name"]
                _save_voice_config(config)
                return f"Switched to voice: {v['name']}. Future responses will use this voice."

        # Fuzzy match
        matches = [v for v in voices if voice_name.lower() in v["name"].lower()]
        if matches:
            v = matches[0]
            config["active_voice_id"] = v["voice_id"]
            config["active_voice_name"] = v["name"]
            _save_voice_config(config)
            return f"Switched to voice: {v['name']}. Future responses will use this voice."

        return f"Voice '{voice_name}' not found. Use list_voices to see available options."
    except Exception as e:
        return f"Error switching voice: {e}"


def clone_voice(name: str = "", audio_url: str = "", audio_path: str = "", description: str = "", **kwargs) -> str:
    """Clone a voice using ElevenLabs instant voice cloning. Provide an audio file path or URL."""
    if not name:
        return "Please provide a name for the cloned voice."
    if not ELEVENLABS_API_KEY:
        return "ElevenLabs API key not configured."
    if not audio_url and not audio_path:
        return "Please provide an audio file path (audio_path) or URL (audio_url) with a voice sample. 30 seconds to 3 minutes of clear speech works best."

    try:
        # Prepare the audio file
        if audio_path:
            audio_file = Path(audio_path)
            if not audio_file.exists():
                return f"Audio file not found: {audio_path}"
            audio_bytes = audio_file.read_bytes()
            filename = audio_file.name
        else:
            # Download from URL
            dl = httpx.get(audio_url, timeout=30, follow_redirects=True)
            if dl.status_code != 200:
                return f"Failed to download audio from URL: {dl.status_code}"
            audio_bytes = dl.content
            filename = "voice_sample.mp3"

        # ElevenLabs instant voice clone
        resp = httpx.post(
            "https://api.elevenlabs.io/v1/voices/add",
            headers={"xi-api-key": ELEVENLABS_API_KEY},
            data={
                "name": name,
                "description": description or f"Cloned voice: {name}",
            },
            files={"files": (filename, audio_bytes)},
            timeout=60,
        )

        if resp.status_code != 200:
            error = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text
            return f"Voice cloning failed: {error}"

        voice_id = resp.json().get("voice_id", "")
        if not voice_id:
            return "Voice cloning returned no voice ID."

        # Save to config
        config = _load_voice_config()
        config["custom_voices"][name] = voice_id
        config["active_voice_id"] = voice_id
        config["active_voice_name"] = name
        _save_voice_config(config)

        return f"Voice '{name}' cloned successfully and set as active. Voice ID: {voice_id}"
    except Exception as e:
        return f"Error cloning voice: {e}"


def get_active_voice(**kwargs) -> dict:
    """Get the currently active voice config. Used internally by TTS."""
    config = _load_voice_config()
    return {
        "voice_id": config.get("active_voice_id", "onwK4e9ZLuTAKqWW03F9"),
        "voice_name": config.get("active_voice_name", "Daniel"),
    }


# ─── Register Tools ───

registry.register(Tool(
    name="list_voices",
    description="List all available TTS voices including custom cloned voices. Use when user asks 'what voices do you have' or 'show me voices'.",
    parameters={"type": "object", "properties": {}},
    handler=list_voices,
))

registry.register(Tool(
    name="switch_voice",
    description="Switch Jarvis's speaking voice. Use when user says 'change your voice to...' or 'use a different voice'.",
    parameters={
        "type": "object",
        "properties": {
            "voice_name": {
                "type": "string",
                "description": "Name of the voice to switch to",
            },
        },
        "required": ["voice_name"],
    },
    handler=switch_voice,
))

registry.register(Tool(
    name="clone_voice",
    description="Clone a voice from an audio file. Use when user says 'clone my voice', 'make a voice from this audio', etc. Needs an audio file path or URL with 30s-3min of clear speech.",
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Name for the cloned voice (e.g. 'My Voice', 'Dad', 'Morgan Freeman')",
            },
            "audio_path": {
                "type": "string",
                "description": "Local file path to audio sample (WAV, MP3, etc.)",
            },
            "audio_url": {
                "type": "string",
                "description": "URL to download audio sample from",
            },
            "description": {
                "type": "string",
                "description": "Optional description of the voice",
            },
        },
        "required": ["name"],
    },
    handler=clone_voice,
))
