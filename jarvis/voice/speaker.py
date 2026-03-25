"""Text-to-speech output — ElevenLabs primary, Edge TTS fallback."""

import asyncio
import tempfile
import subprocess
from pathlib import Path

import httpx
import numpy as np
import soundfile as sf
import edge_tts

from jarvis.config import (
    TTS_ENGINE,
    ELEVENLABS_API_KEY,
    ELEVENLABS_VOICE_ID,
    JARVIS_VOICE,
)


class Speaker:
    def __init__(self):
        self._use_elevenlabs = (
            TTS_ENGINE == "elevenlabs" and bool(ELEVENLABS_API_KEY)
        )
        if self._use_elevenlabs:
            print("[Voice] Using ElevenLabs TTS")
        else:
            print("[Voice] Using Edge TTS (fallback)")

    def _generate_elevenlabs(self, text: str, mp3_path: str) -> bool:
        """Generate speech via ElevenLabs API. Returns True on success."""
        try:
            resp = httpx.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}",
                headers={
                    "xi-api-key": ELEVENLABS_API_KEY,
                    "Content-Type": "application/json",
                },
                json={
                    "text": text,
                    "model_id": "eleven_multilingual_v2",
                    "voice_settings": {
                        "stability": 0.75,
                        "similarity_boost": 0.80,
                        "style": 0.2,
                    },
                },
                timeout=30,
            )
            if resp.status_code == 200:
                Path(mp3_path).write_bytes(resp.content)
                return True
            else:
                print(f"[ElevenLabs] Error {resp.status_code}: {resp.text[:100]}")
                return False
        except Exception as e:
            print(f"[ElevenLabs] Request failed: {e}")
            return False

    async def _generate_edge(self, text: str, mp3_path: str):
        """Generate speech via Edge TTS (free fallback)."""
        communicate = edge_tts.Communicate(
            text, JARVIS_VOICE, rate="-10%", pitch="-5Hz"
        )
        await communicate.save(mp3_path)

    def _fix_pronunciation(self, text: str) -> str:
        """Fix words the TTS engine mispronounces."""
        # Deagz is pronounced "Deegz"
        for variant in ("Deagz", "deagz", "DEAGZ"):
            text = text.replace(variant, "Deegz")
        return text

    def speak(self, text: str):
        """Convert text to speech and play it."""
        if not text:
            return
        text = self._fix_pronunciation(text)

        mp3_tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        wav_tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        mp3_path = mp3_tmp.name
        wav_path = wav_tmp.name
        mp3_tmp.close()
        wav_tmp.close()

        try:
            # Try ElevenLabs first, fall back to Edge TTS
            if self._use_elevenlabs:
                success = self._generate_elevenlabs(text, mp3_path)
                if not success:
                    print("[Voice] Falling back to Edge TTS")
                    asyncio.run(self._generate_edge(text, mp3_path))
            else:
                asyncio.run(self._generate_edge(text, mp3_path))

            # Convert MP3 to WAV for playback
            data, sr = sf.read(mp3_path)
            sf.write(wav_path, data, sr, format="WAV", subtype="PCM_16")

            # Play via PowerShell SoundPlayer
            subprocess.run(
                [
                    "powershell", "-Command",
                    f'(New-Object Media.SoundPlayer "{wav_path}").PlaySync()',
                ],
                check=True,
                timeout=60,
            )
        except Exception as e:
            print(f"[Audio playback error: {e}]")
        finally:
            Path(mp3_path).unlink(missing_ok=True)
            Path(wav_path).unlink(missing_ok=True)
