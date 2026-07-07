"""He answers to Joe - voiceprint gate for the wall's ear.

resemblyzer turns each utterance into a 256-d voice embedding. Enrollment is
automatic and effortless: the first ENROLL_TARGET wake-word-CONFIRMED
utterances (near-certainly the owner saying "Hey Jarvis ...") build the
profile; after that, every ear clip gets a cosine-similarity check and the
wall discards voices that aren't his - which mutes the deepest noise source
software can touch: people talking on the TV.

Install on the laptop:  pip install resemblyzer
Missing library = gate silently off (match is never reported False).
Re-enroll = delete data/voiceprint.json and say "Hey Jarvis" a few times.
"""

import io
import json
import threading
import wave
from pathlib import Path

import numpy as np

PROFILE_FILE = Path(__file__).parent.parent.parent / "data" / "voiceprint.json"
ENROLL_TARGET = 8     # confirmed wakes that build the profile
MATCH_THRESHOLD = 0.60  # below this = not the owner (lenient: rejecting Joe is worse)

_encoder = None
_lock = threading.Lock()
_import_failed = False


def _get_encoder():
    global _encoder, _import_failed
    if _import_failed:
        return None
    try:
        from resemblyzer import VoiceEncoder
    except ImportError:
        _import_failed = True
        print("[voiceprint] resemblyzer not installed - speaker gate off")
        return None
    if _encoder is None:
        _encoder = VoiceEncoder("cpu", verbose=False)
        print("[voiceprint] encoder ready")
    return _encoder


def _load_profile() -> list:
    try:
        return json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_profile(embeddings: list):
    PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_FILE.write_text(json.dumps(embeddings), encoding="utf-8")


def _embed(wav_bytes: bytes):
    """16k mono WAV bytes (the ear's format) -> embedding, or None."""
    enc = _get_encoder()
    if enc is None:
        return None
    with wave.open(io.BytesIO(wav_bytes)) as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        sr = w.getframerate()
    audio = pcm.astype(np.float32) / 32768.0
    if len(audio) < sr:  # under a second - too short to fingerprint
        return None
    from resemblyzer import preprocess_wav
    return enc.embed_utterance(preprocess_wav(audio, source_sr=sr))


def check_and_learn(wav_bytes: bytes, wake_confirmed: bool) -> dict:
    """One call per ear clip, from /api/wake.

    Returns {enrolled, n, sim, match}:
      match True/False only when the profile is complete AND the gate works;
      match None = gate unavailable or still enrolling (wall must not block).
    """
    out = {"enrolled": False, "n": 0, "sim": None, "match": None}
    try:
        with _lock:
            profile = _load_profile()
            out["n"] = len(profile)
            emb = _embed(wav_bytes)
            if emb is None:
                return out

            if len(profile) < ENROLL_TARGET:
                # still learning his voice - only confirmed wakes teach it
                if wake_confirmed:
                    profile.append([float(x) for x in emb])
                    _save_profile(profile)
                    out["n"] = len(profile)
                    print(f"[voiceprint] enrolled {out['n']}/{ENROLL_TARGET}")
                return out

            out["enrolled"] = True
            center = np.mean(np.array(profile, dtype=np.float32), axis=0)
            center /= np.linalg.norm(center) + 1e-9
            emb = emb / (np.linalg.norm(emb) + 1e-9)
            sim = float(np.dot(center, emb))
            out["sim"] = round(sim, 3)
            out["match"] = sim >= MATCH_THRESHOLD
    except Exception as e:
        print(f"[voiceprint] check failed: {e}")
    return out
