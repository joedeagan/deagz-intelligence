"""Shazam-like song identification — records audio and identifies it."""

import subprocess
import tempfile
import base64
from pathlib import Path

import httpx

from jarvis.tools.base import Tool, registry


def identify_song(duration: int = 5) -> str:
    """Record audio from the microphone and try to identify the song.
    Uses the AudD music recognition API (free tier: 300 requests/month)."""

    # Record audio using ffmpeg (captures system audio or mic)
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp_path = tmp.name
    tmp.close()

    try:
        # Try recording from default audio device
        # On Windows, use dshow or wasapi
        result = subprocess.run(
            [
                "powershell", "-Command",
                f"Add-Type -AssemblyName System.Speech; "
                f"$rec = New-Object System.Speech.Recognition.SpeechRecognitionEngine; "
                f"$stream = New-Object System.IO.FileStream('{tmp_path}', [System.IO.FileMode]::Create); "
                f"$rec.SetInputToDefaultAudioDevice(); "
                f"$rec.RecognizeAsync([System.Speech.Recognition.RecognizeMode]::Multiple); "
                f"Start-Sleep -Seconds {duration}; "
                f"$rec.RecognizeAsyncCancel(); "
                f"$rec.Dispose(); "
                f"$stream.Close()"
            ],
            capture_output=True, text=True, timeout=duration + 10,
        )
    except Exception:
        pass

    # Alternative: use Python's sounddevice to record
    try:
        import sounddevice as sd
        import numpy as np
        import wave

        fs = 16000
        audio_data = sd.rec(int(duration * fs), samplerate=fs, channels=1, dtype='int16')
        sd.wait()

        with wave.open(tmp_path, 'w') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(fs)
            wf.writeframes(audio_data.tobytes())

    except ImportError:
        # Fallback — use wmic/powershell to record
        try:
            subprocess.run(
                f'powershell -Command "'
                f"Add-Type -TypeDefinition @'\\n"
                f"using System;using System.Runtime.InteropServices;\\n"
                f"public class Mic{{[DllImport(\\\"winmm.dll\\\")]public static extern int mciSendString(string cmd,System.Text.StringBuilder ret,int len,IntPtr hwnd);}}\\n"
                f"'@;\\n"
                f"[Mic]::mciSendString('open new type waveaudio alias mic', $null, 0, 0);\\n"
                f"[Mic]::mciSendString('record mic', $null, 0, 0);\\n"
                f"Start-Sleep {duration};\\n"
                f"[Mic]::mciSendString('save mic {tmp_path}', $null, 0, 0);\\n"
                f"[Mic]::mciSendString('close mic', $null, 0, 0)\"",
                shell=True, capture_output=True, timeout=duration + 10,
            )
        except Exception as e:
            return f"Could not record audio: {e}"
    except Exception as e:
        return f"Recording error: {e}"

    # Check if we have audio data
    audio_path = Path(tmp_path)
    if not audio_path.exists() or audio_path.stat().st_size < 1000:
        audio_path.unlink(missing_ok=True)
        return "Could not capture audio. Make sure your microphone is working."

    # Send to AudD for identification
    try:
        audio_b64 = base64.b64encode(audio_path.read_bytes()).decode()

        resp = httpx.post(
            "https://api.audd.io/",
            data={
                "audio": audio_b64,
                "return": "apple_music,spotify",
                "api_token": "test",  # Free tier token
            },
            timeout=15,
        )
        data = resp.json()

        if data.get("status") == "success" and data.get("result"):
            result = data["result"]
            title = result.get("title", "Unknown")
            artist = result.get("artist", "Unknown")
            album = result.get("album", "")
            album_str = f" from the album '{album}'" if album else ""
            return f"That's '{title}' by {artist}{album_str}."
        else:
            return "I couldn't identify that song. Try playing it louder or closer to the microphone."

    except Exception as e:
        return f"Song identification failed: {e}"
    finally:
        audio_path.unlink(missing_ok=True)


def whats_playing() -> str:
    """Check what's currently playing on Spotify by reading the window title."""
    try:
        result = subprocess.run(
            'powershell -Command "Get-Process spotify -ErrorAction SilentlyContinue | '
            'Where-Object {$_.MainWindowTitle} | Select-Object -ExpandProperty MainWindowTitle"',
            shell=True, capture_output=True, text=True, timeout=5,
        )
        title = result.stdout.strip()
        if title and title.lower() != "spotify" and title.lower() != "spotify free" and title.lower() != "spotify premium":
            # Spotify window title is usually "Artist - Song"
            return f"Currently playing on Spotify: {title}"
        elif title:
            return "Spotify is open but nothing is playing right now."
        else:
            return "Spotify doesn't appear to be running."
    except Exception as e:
        return f"Could not check Spotify: {e}"


# Register tools
registry.register(Tool(
    name="identify_song",
    description="Record audio from the microphone for a few seconds and try to identify the song playing. Use when user says 'what song is this?' or 'Shazam this'.",
    parameters={
        "type": "object",
        "properties": {
            "duration": {"type": "integer", "description": "Seconds to listen (default 5, max 10)"},
        },
        "required": [],
    },
    handler=identify_song,
))

registry.register(Tool(
    name="whats_playing",
    description="Check what song is currently playing on Spotify by reading the window title. Quick check — no recording needed.",
    parameters={"type": "object", "properties": {}, "required": []},
    handler=whats_playing,
))
