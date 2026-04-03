"""Stem Player — separate songs into vocals, drums, bass, and melody using Demucs."""

import os
import hashlib
import subprocess
import threading
from pathlib import Path

from jarvis.tools.base import Tool, registry

STEM_CACHE = Path(__file__).parent.parent.parent / "data" / "stem_cache"
STEM_CACHE.mkdir(parents=True, exist_ok=True)

DOWNLOAD_DIR = Path(__file__).parent.parent.parent / "data" / "downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Track current separation status
_separation_status = {"active": False, "song": "", "progress": "", "song_id": ""}


def _song_id(query: str) -> str:
    """Generate a stable ID for a song query."""
    return hashlib.md5(query.lower().strip().encode()).hexdigest()[:12]


def _download_from_youtube(query: str, output_path: str) -> bool:
    """Download audio from YouTube using yt-dlp Python API."""
    try:
        import yt_dlp

        wav_path = output_path if output_path.endswith(".wav") else output_path + ".wav"

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": output_path + ".%(ext)s",
            "quiet": True,
            "no_warnings": True,
            "default_search": "ytsearch1",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
                "preferredquality": "192",
            }],
        }

        # Try with ffmpeg postprocessing first
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([query])
        except Exception:
            # Fallback — download best audio without conversion
            ydl_opts2 = {
                "format": "bestaudio/best",
                "outtmpl": output_path + ".%(ext)s",
                "quiet": True,
                "no_warnings": True,
                "default_search": "ytsearch1",
            }
            with yt_dlp.YoutubeDL(ydl_opts2) as ydl:
                ydl.download([query])

        # Find the downloaded file (could be .wav, .webm, .m4a, .opus, etc.)
        parent = Path(output_path).parent
        stem = Path(output_path).stem
        for f in parent.glob(f"{stem}.*"):
            if f.suffix in (".wav", ".mp3", ".m4a", ".opus", ".webm", ".ogg"):
                if str(f) != wav_path:
                    # Convert to WAV using soundfile if not already WAV
                    try:
                        import soundfile as sf
                        data, sr = sf.read(str(f))
                        sf.write(wav_path, data, sr)
                        f.unlink()
                    except Exception:
                        f.rename(wav_path)
                return True

        return Path(wav_path).exists()
    except Exception as e:
        print(f"YouTube download error: {e}")
        return False


def _run_demucs(input_path: str, output_dir: str) -> bool:
    """Run Demucs stem separation using custom runner (bypasses broken torchaudio)."""
    try:
        run_demucs = str(Path(__file__).parent.parent.parent / "run_demucs.py")
        cmd = [
            "C:\\Users\\brian\\AppData\\Local\\Python\\pythoncore-3.14-64\\python.exe",
            run_demucs,
            input_path,
            output_dir,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        print(f"Demucs stdout: {result.stdout[-200:]}")
        if result.stderr:
            print(f"Demucs stderr: {result.stderr[-200:]}")
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print("Demucs timed out")
        return False
    except Exception as e:
        print(f"Demucs error: {e}")
        return False


def separate_song(query: str = "", **kwargs) -> str:
    """Separate a song into stems (vocals, drums, bass, other). Downloads from YouTube and processes."""
    global _separation_status

    if not query:
        return "Tell me which song to separate."

    if _separation_status["active"]:
        return f"Already processing '{_separation_status['song']}'. Please wait."

    sid = _song_id(query)
    stem_dir = STEM_CACHE / sid

    # Check cache
    if stem_dir.exists() and all((stem_dir / f"{s}.wav").exists() for s in ["vocals", "drums", "bass", "other"]):
        _separation_status["song_id"] = sid
        return f"Stems for '{query}' are ready. The stem player should appear on your screen. Song ID: {sid}"

    # Start separation in background
    _separation_status = {"active": True, "song": query, "progress": "downloading", "song_id": sid}

    def _process():
        global _separation_status
        try:
            # Step 1: Download from YouTube
            _separation_status["progress"] = "downloading"
            dl_path = str(DOWNLOAD_DIR / f"{sid}")
            wav_path = str(DOWNLOAD_DIR / f"{sid}.wav")

            if not Path(wav_path).exists():
                success = _download_from_youtube(query, dl_path)
                if not success:
                    _separation_status = {"active": False, "song": query, "progress": "download_failed", "song_id": sid}
                    return

            # Step 1.5: Convert to real WAV using ffmpeg (yt-dlp downloads as WebM)
            real_wav = str(DOWNLOAD_DIR / f"{sid}_real.wav")
            if not Path(real_wav).exists():
                ffmpeg_path = str(Path(__file__).parent.parent.parent / "ffmpeg.exe")
                try:
                    subprocess.run(
                        [ffmpeg_path, "-i", wav_path, "-ar", "44100", "-ac", "2", real_wav, "-y"],
                        capture_output=True, timeout=60,
                    )
                except Exception as e:
                    print(f"ffmpeg conversion error: {e}")
                    _separation_status = {"active": False, "song": query, "progress": "conversion_failed", "song_id": sid}
                    return

            if not Path(real_wav).exists():
                _separation_status = {"active": False, "song": query, "progress": "conversion_failed", "song_id": sid}
                return

            # Step 2: Run Demucs — outputs directly to stem_dir
            _separation_status["progress"] = "separating"
            stem_dir.mkdir(parents=True, exist_ok=True)
            success = _run_demucs(real_wav, str(stem_dir))

            if not success:
                _separation_status = {"active": False, "song": query, "progress": "separation_failed", "song_id": sid}
                return

            _separation_status = {"active": False, "song": query, "progress": "done", "song_id": sid}

        except Exception as e:
            _separation_status = {"active": False, "song": query, "progress": f"error: {e}", "song_id": sid}

    thread = threading.Thread(target=_process, daemon=True)
    thread.start()

    return f"Processing '{query}' — downloading and separating into stems. This takes about a minute. I'll let you know when it's ready. Song ID: {sid}"


def get_stem_status(**kwargs) -> str:
    """Check the status of stem separation."""
    if _separation_status["active"]:
        return f"Processing '{_separation_status['song']}' — currently {_separation_status['progress']}."

    if _separation_status["progress"] == "done":
        return f"Stems for '{_separation_status['song']}' are ready! Song ID: {_separation_status['song_id']}"

    if "failed" in _separation_status.get("progress", ""):
        return f"Separation failed for '{_separation_status['song']}': {_separation_status['progress']}"

    return "No stem separation in progress. Ask me to separate a song."


def control_stems(action: str = "", stem: str = "", **kwargs) -> str:
    """Control stem playback — mute, solo, reset. This triggers frontend actions."""
    valid_stems = ["vocals", "drums", "bass", "other", "melody"]
    stem_lower = stem.lower().strip() if stem else ""
    if stem_lower == "melody":
        stem_lower = "other"

    action_lower = action.lower().strip()

    if action_lower == "mute" and stem_lower in valid_stems:
        return f"STEM_COMMAND:mute:{stem_lower}"
    elif action_lower == "solo" or action_lower == "isolate":
        if stem_lower in valid_stems:
            return f"STEM_COMMAND:solo:{stem_lower}"
    elif action_lower == "reset" or action_lower == "all":
        return "STEM_COMMAND:reset:all"
    elif action_lower in ("unmute", "restore"):
        if stem_lower in valid_stems:
            return f"STEM_COMMAND:unmute:{stem_lower}"

    return f"Unknown stem command. Try: mute drums, solo vocals, isolate bass, reset stems."


# ─── Register ───

registry.register(Tool(
    name="separate_song",
    description="Separate a song into stems (vocals, drums, bass, melody). Downloads from YouTube and splits using AI. Use for 'separate Sicko Mode', 'split this song into stems', 'isolate the vocals from Rodeo'. Takes ~60 seconds.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Song name and artist (e.g. 'Sicko Mode Travis Scott')"},
        },
        "required": ["query"],
    },
    handler=separate_song,
))

registry.register(Tool(
    name="get_stem_status",
    description="Check if stem separation is done. Use for 'is the song ready?', 'stem status'.",
    parameters={"type": "object", "properties": {}},
    handler=get_stem_status,
))

registry.register(Tool(
    name="control_stems",
    description="Control stem playback — mute, solo, unmute, or reset individual stems. Use for 'mute the drums', 'solo vocals', 'isolate the bass', 'play just melody', 'reset stems'. This sends commands to the stem player in the browser.",
    parameters={
        "type": "object",
        "properties": {
            "action": {"type": "string", "description": "Action: mute, solo, isolate, unmute, reset"},
            "stem": {"type": "string", "description": "Which stem: vocals, drums, bass, other/melody"},
        },
        "required": ["action"],
    },
    handler=control_stems,
))
