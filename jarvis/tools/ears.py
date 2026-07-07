"""Jarvis's own ears - local Whisper STT with a personal vocabulary.

faster-whisper runs on the laptop's CPU: free per call, no cloud round-trip,
and biased toward the words that actually get said in this room (names, apps,
teams, and whatever is in the Jellyfin library right now) so proper nouns
stop coming back mangled. If faster-whisper isn't installed the caller falls
back to ElevenLabs Scribe - install with:  pip install faster-whisper
"""

import io
import json
import os
import threading
import time
from pathlib import Path

_model = None
_model_lock = threading.Lock()
_import_failed = False

# words the transcriber should expect to hear in this room
STATIC_VOCAB = ("Jarvis, Deagz, Kalshi, Jellyfin, Spotify, Netflix, YouTube TV, "
                "Hulu, Disney Plus, Guardians, Cavaliers, Cavs, Browns, Buckeyes, "
                "Ohio State, Akron, Fortnite")

_movie_cache = {"names": "", "ts": 0.0}


def _jellyfin_key() -> str:
    key = os.getenv("JELLYFIN_API_KEY", "")
    if not key:
        try:
            key = json.loads(Path("C:/jarvis-agent/config.json").read_text()).get("api_key", "")
        except Exception:
            key = ""
    return key


def _movie_names() -> str:
    """Current library titles, cached 10 minutes - new movies join the vocabulary."""
    if time.time() - _movie_cache["ts"] < 600:
        return _movie_cache["names"]
    try:
        import httpx
        r = httpx.get(
            "http://127.0.0.1:8096/Items",
            params={"IncludeItemTypes": "Movie", "Recursive": "true", "api_key": _jellyfin_key()},
            timeout=5,
        )
        names = ", ".join(i.get("Name", "") for i in r.json().get("Items", [])[:40])
        _movie_cache["names"] = names
    except Exception:
        pass  # keep whatever we had
    _movie_cache["ts"] = time.time()
    return _movie_cache["names"]


def _vocab_prompt() -> str:
    movies = _movie_names()
    return STATIC_VOCAB + (", " + movies if movies else "")


def transcribe_local(data: bytes):
    """Transcribe audio bytes (WAV from the ear, m4a/mp4 from taps).

    Returns the text, or None when the local engine is unavailable so the
    caller can fall back to the cloud transcriber.
    """
    global _model, _import_failed
    if _import_failed:
        return None
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        _import_failed = True
        print("[ears] faster-whisper not installed - falling back to cloud STT")
        return None
    try:
        with _model_lock:
            if _model is None:
                name = os.getenv("WHISPER_MODEL", "base.en")
                _model = WhisperModel(name, device="cpu", compute_type="int8",
                                      cpu_threads=4)
                print(f"[ears] local whisper ready ({name})")
            # serialized on purpose: the laptop has 4 cores and also runs
            # Jellyfin - one clip at a time keeps everything smooth
            segments, _info = _model.transcribe(
                io.BytesIO(data),
                language="en",
                initial_prompt=_vocab_prompt(),
                beam_size=1,  # greedy - ~40% faster; the vocab prompt carries accuracy
                condition_on_previous_text=False,
                vad_filter=True,  # trims silence; also curbs noise hallucinations
            )
            return " ".join(s.text.strip() for s in segments).strip()
    except Exception as e:
        print(f"[ears] local transcribe failed: {e}")
        return None
