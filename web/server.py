"""FastAPI server for JARVIS web interface."""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel
import httpx
import asyncio
import edge_tts
import soundfile as sf
import numpy as np
import tempfile
from pathlib import Path

from jarvis.config import (
    ELEVENLABS_API_KEY,
    ELEVENLABS_VOICE_ID,
    FISH_AUDIO_API_KEY,
    FISH_AUDIO_MODEL_ID,
    JARVIS_VOICE,
    TTS_ENGINE,
)
from jarvis.tools.voice import get_active_voice

# Import tools to register them
from jarvis.tools import system as _s  # noqa
from jarvis.tools import kalshi as _k  # noqa
from jarvis.tools import study as _st  # noqa
from jarvis.tools import shazam as _sh  # noqa
from jarvis.tools import spotify as _sp2  # noqa
from jarvis.tools import memory as _mem  # noqa
from jarvis.tools import image_gen as _img  # noqa
from jarvis.tools import voice as _vc  # noqa
from jarvis.tools import kalshi_advisor as _ka  # noqa
from jarvis.tools import autodj as _dj  # noqa
from jarvis.tools import screen_aware as _sa  # noqa
from jarvis.tools import proactive as _pro  # noqa
from jarvis.tools import coder as _code  # noqa
from jarvis.tools import contacts as _ct  # noqa
from jarvis.tools import routines as _rt  # noqa
from jarvis.tools import backtester as _bt  # noqa
from jarvis.tools import stems as _stems  # noqa
from jarvis.brain import Brain

app = FastAPI(title="JARVIS")
brain = Brain()

# Serve static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")


class ChatRequest(BaseModel):
    message: str


class TTSRequest(BaseModel):
    text: str


def fix_pronunciation(text: str) -> str:
    for v in ("Deagz", "deagz", "DEAGZ"):
        text = text.replace(v, "Deegz")
    return text


@app.get("/")
async def index():
    return FileResponse(os.path.join(static_dir, "index.html"))

@app.get("/sw.js")
async def service_worker():
    return FileResponse(os.path.join(static_dir, "sw.js"), media_type="application/javascript")



@app.get("/api/dashboard")
async def dashboard():
    """Aggregated dashboard data — weather, portfolio, bot status."""
    import datetime
    from jarvis.tools.system import get_weather
    from jarvis.tools.kalshi import get_portfolio, get_bot_status

    data = {
        "time": datetime.datetime.now().strftime("%I:%M %p"),
        "date": datetime.datetime.now().strftime("%A, %B %d"),
        "weather": {},
        "portfolio": {},
        "bot": {},
    }

    # Weather
    try:
        weather_raw = get_weather()
        lines = weather_raw.split("\n")
        data["weather"]["summary"] = lines[0] if lines else "N/A"
        data["weather"]["forecast"] = lines[1] if len(lines) > 1 else ""
    except Exception:
        data["weather"]["summary"] = "Weather unavailable"

    # Portfolio
    try:
        port = _get_portfolio_data()
        data["portfolio"] = port
    except Exception:
        data["portfolio"] = {"balance": 0, "pnl": 0, "positions": 0}

    # Bot status
    try:
        from jarvis.tools.kalshi import _get
        bot = _get("/api/bot/status")
        if isinstance(bot, dict):
            data["bot"] = {
                "running": bot.get("running", False),
                "scans": bot.get("scan_count", 0),
                "trades": bot.get("trades_today", bot.get("exits_today", 0)),
                "pnl": bot.get("daily_loss_cents", 0) / 100,
            }
    except Exception:
        data["bot"] = {"running": False}

    # Equity chart data
    try:
        from jarvis.tools.kalshi import _get as kalshi_get
        eq = kalshi_get("/api/bot/equity?days=7")
        if isinstance(eq, dict):
            points = eq.get("equity", [])
            data["equity_chart"] = [p.get("equity_cents", 0) / 100 for p in points[-30:]]
    except Exception:
        data["equity_chart"] = []

    return data


def _get_portfolio_data():
    """Get portfolio data as a dict for the dashboard."""
    from jarvis.tools.kalshi import _get
    raw = _get("/api/portfolio")
    if isinstance(raw, str):
        return {"balance": 0, "pnl": 0, "positions": 0}

    balance = raw.get("balance", raw.get("balance_cents", 0))
    if balance > 1000:
        balance /= 100

    return {
        "balance": round(balance, 2),
        "portfolio_value": round(raw.get("portfolio_value", 0), 2),
        "pnl": round(raw.get("unrealised_pnl", 0), 2),
        "positions": raw.get("position_count", len(raw.get("positions", []))),
    }


@app.post("/api/chat")
async def chat(req: ChatRequest):
    response = brain.think(req.message)
    return {"response": response}


import hashlib

# In-memory TTS cache + disk cache
_tts_cache: dict[str, bytes] = {}
_cache_dir = Path(os.path.dirname(__file__)).parent / "data" / "tts_cache"
_cache_dir.mkdir(parents=True, exist_ok=True)


def _cache_key(text: str) -> str:
    return hashlib.md5(text.lower().strip().encode()).hexdigest()


def _load_cache():
    """Load cached audio files from disk on startup."""
    for f in _cache_dir.glob("*.mp3"):
        _tts_cache[f.stem] = f.read_bytes()
    print(f"TTS cache: {len(_tts_cache)} entries loaded from disk")


def _truncate_for_speech(text: str, max_chars: int = 300) -> str:
    """Truncate long responses to save ElevenLabs characters.
    Keeps the first few sentences, drops the rest."""
    if len(text) <= max_chars:
        return text
    # Find a good cutoff point (end of sentence)
    cutoff = text[:max_chars]
    for end in [". ", "! ", "? "]:
        idx = cutoff.rfind(end)
        if idx > 100:
            return cutoff[:idx + 1]
    return cutoff.rstrip() + "."


# Load disk cache on import
_load_cache()


async def generate_tts(text: str) -> bytes:
    """Generate TTS audio bytes from text. Uses cache for repeated phrases."""
    text = fix_pronunciation(text)
    if not text:
        return b""

    # Check cache first — instant response
    key = _cache_key(text)
    if key in _tts_cache:
        return _tts_cache[key]

    # Try Fish Audio first
    if TTS_ENGINE == "fish" and FISH_AUDIO_API_KEY:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.fish.audio/v1/tts",
                    headers={
                        "Authorization": f"Bearer {FISH_AUDIO_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "text": text,
                        "reference_id": FISH_AUDIO_MODEL_ID,
                        "format": "mp3",
                        "mp3_bitrate": 128,
                    },
                    timeout=30,
                )
            if resp.status_code == 200:
                _save_to_cache(text, resp.content)
                return resp.content
            else:
                print(f"Fish Audio error: {resp.status_code} {resp.text}")
        except Exception as e:
            print(f"Fish Audio exception: {e}")

    # Try ElevenLabs with flash model (fastest) — uses active voice from voice config
    if (TTS_ENGINE == "elevenlabs" or TTS_ENGINE == "fish") and ELEVENLABS_API_KEY:
        try:
            voice = get_active_voice()
            voice_id = voice.get("voice_id", ELEVENLABS_VOICE_ID)
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                    headers={
                        "xi-api-key": ELEVENLABS_API_KEY,
                        "Content-Type": "application/json",
                    },
                    json={
                        "text": text,
                        "model_id": "eleven_flash_v2_5",
                        "voice_settings": {
                            "stability": 0.75,
                            "similarity_boost": 0.80,
                        },
                    },
                    timeout=30,
                )
            if resp.status_code == 200:
                _save_to_cache(text, resp.content)
                return resp.content
        except Exception:
            pass

    # Fallback to Edge TTS
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp_path = tmp.name
    tmp.close()
    try:
        communicate = edge_tts.Communicate(text, JARVIS_VOICE, rate="-10%", pitch="-5Hz")
        await communicate.save(tmp_path)
        audio = Path(tmp_path).read_bytes()
        _save_to_cache(text, audio)
        return audio
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _save_to_cache(text: str, audio: bytes):
    """Save TTS audio to both memory and disk cache."""
    if len(audio) < 100:  # skip empty/broken audio
        return
    key = _cache_key(text)
    _tts_cache[key] = audio
    cache_file = _cache_dir / f"{key}.mp3"
    cache_file.write_bytes(audio)
    # Keep cache under 200 entries
    if len(_tts_cache) > 200:
        oldest = next(iter(_tts_cache))
        del _tts_cache[oldest]
        (cache_dir / f"{oldest}.mp3").unlink(missing_ok=True)


@app.post("/api/tts")
async def tts(req: TTSRequest):
    audio = await generate_tts(req.text)
    if not audio:
        return Response(status_code=400)
    return Response(content=audio, media_type="audio/mpeg")


class VisionRequest(BaseModel):
    image: str  # base64 encoded image
    question: str = "What is this? Describe it briefly in 2-3 sentences."


@app.post("/api/vision")
async def vision(req: VisionRequest):
    """Analyze an image with Claude's vision and return spoken response."""
    import anthropic
    from jarvis.config import ANTHROPIC_API_KEY, SYSTEM_PROMPT

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        # Strip data URL prefix if present
        img_data = req.image
        if "," in img_data:
            img_data = img_data.split(",", 1)[1]

        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=200,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": img_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": req.question,
                    },
                ],
            }],
        )
        answer = resp.content[0].text

        # Generate TTS for the answer
        audio = await generate_tts(answer)
        import urllib.parse
        encoded_text = urllib.parse.quote(answer.replace("\n", " ")[:500])

        return Response(
            content=audio,
            media_type="audio/mpeg",
            headers={"X-Jarvis-Text": encoded_text},
        )
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/chat-and-speak")
async def chat_and_speak(req: ChatRequest):
    """Combined endpoint — get response and stream TTS audio."""
    response = brain.think(req.message)
    text = fix_pronunciation(response)

    # Try streaming from ElevenLabs — uses active voice
    if TTS_ENGINE in ("elevenlabs", "fish") and ELEVENLABS_API_KEY:
        voice = get_active_voice()
        voice_id = voice.get("voice_id", ELEVENLABS_VOICE_ID)

        async def stream_audio():
            async with httpx.AsyncClient() as client:
                async with client.stream(
                    "POST",
                    f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream",
                    headers={
                        "xi-api-key": ELEVENLABS_API_KEY,
                        "Content-Type": "application/json",
                    },
                    json={
                        "text": text,
                        "model_id": "eleven_flash_v2_5",
                        "voice_settings": {
                            "stability": 0.75,
                            "similarity_boost": 0.80,
                        },
                        "optimize_streaming_latency": 4,
                    },
                    timeout=30,
                ) as resp:
                    async for chunk in resp.aiter_bytes(1024):
                        yield chunk

        import urllib.parse
        encoded_text = urllib.parse.quote(response.replace("\n", " ")[:500])
        return StreamingResponse(
            stream_audio(),
            media_type="audio/mpeg",
            headers={"X-Jarvis-Text": encoded_text},
        )

    # Fallback — non-streaming
    audio = await generate_tts(response)
    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers={"X-Jarvis-Text": response.replace("\n", " ")[:500]},
    )


@app.post("/api/chat-stream")
async def chat_stream(req: ChatRequest):
    """SSE endpoint — streams text first, then audio URL."""
    import json as _json
    import urllib.parse

    async def event_stream():
        # Step 1: Get Claude response (this is the slow part)
        response = brain.think(req.message)

        # Step 2: Send text immediately so frontend can display it
        yield f"data: {_json.dumps({'type': 'text', 'content': response})}\n\n"

        # Step 3: Generate TTS — truncate to save ElevenLabs chars
        text = _truncate_for_speech(fix_pronunciation(response))
        audio = await generate_tts(text)

        # Step 4: Send audio as base64
        import base64
        audio_b64 = base64.b64encode(audio).decode("ascii")
        yield f"data: {_json.dumps({'type': 'audio', 'content': audio_b64})}\n\n"

        yield "data: {\"type\": \"done\"}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/briefing")
async def briefing():
    """Good Morning Deagz — daily briefing. Returns text + audio."""
    import json as _json
    import base64

    # Gather all context
    dashboard_data = await dashboard()

    # Build briefing prompt
    weather = dashboard_data.get("weather", {}).get("summary", "Weather unavailable")
    forecast = dashboard_data.get("weather", {}).get("forecast", "")
    portfolio = dashboard_data.get("portfolio", {})
    bot = dashboard_data.get("bot", {})

    briefing_text = brain.think(
        f"Give me a good morning briefing. Here's the data:\n"
        f"Weather: {weather} {forecast}\n"
        f"Portfolio: balance ${portfolio.get('balance', 0):.2f}, "
        f"portfolio value ${portfolio.get('portfolio_value', 0):.2f}, "
        f"P&L ${portfolio.get('pnl', 0):.2f}, "
        f"{portfolio.get('positions', 0)} positions\n"
        f"Bot: {'running' if bot.get('running') else 'stopped'}, "
        f"{bot.get('scans', 0)} scans, {bot.get('trades', 0)} trades today\n"
        f"Keep it natural and concise — 3-4 sentences max."
    )

    text = fix_pronunciation(briefing_text)
    audio = await generate_tts(text)
    audio_b64 = base64.b64encode(audio).decode("ascii")

    return {
        "text": briefing_text,
        "audio": audio_b64,
    }


# ─── Stem Player Endpoints ───

class StemRequest(BaseModel):
    query: str

@app.post("/api/stems/separate")
async def stems_separate(req: StemRequest):
    from jarvis.tools.stems import separate_song
    result = separate_song(query=req.query)
    from jarvis.tools.stems import _separation_status
    return {"message": result, "song_id": _separation_status.get("song_id", "")}

@app.get("/api/stems/{song_id}/status")
async def stems_status(song_id: str):
    import json as _json
    from jarvis.tools.stems import _separation_status, STEM_CACHE
    stem_dir = STEM_CACHE / song_id
    stems_ready = stem_dir.exists() and all(
        (stem_dir / f"{s}.mp3").exists() or (stem_dir / f"{s}.wav").exists()
        for s in ["vocals", "drums", "bass", "other"]
    )

    # Read progress file from Demucs
    progress_file = stem_dir / "progress.json"
    percent = 0
    detail = ""
    if progress_file.exists():
        try:
            prog = _json.loads(progress_file.read_text())
            percent = prog.get("percent", 0)
            detail = prog.get("detail", "")
        except Exception:
            pass

    return {
        "ready": stems_ready,
        "active": _separation_status.get("active", False),
        "progress": _separation_status.get("progress", ""),
        "song": _separation_status.get("song", ""),
        "percent": percent,
        "detail": detail,
    }

@app.get("/api/stems/library")
async def stems_library():
    """List all separated songs."""
    import json as _j
    from jarvis.tools.stems import STEM_CACHE
    songs = []
    for d in STEM_CACHE.iterdir():
        if d.is_dir() and d.name != "demucs_raw":
            has_stems = any((d / f"{s}.mp3").exists() or (d / f"{s}.wav").exists() for s in ["vocals"])
            if has_stems:
                name = d.name
                info_file = d / "info.json"
                if info_file.exists():
                    try:
                        info = _j.loads(info_file.read_text())
                        name = info.get("name", d.name)
                    except Exception:
                        pass
                songs.append({"id": d.name, "name": name})
    return {"songs": songs}

@app.get("/api/stems/{song_id}/{stem}")
async def stems_get(song_id: str, stem: str):
    from jarvis.tools.stems import STEM_CACHE
    if stem not in ("vocals", "drums", "bass", "other"):
        return Response(status_code=400)
    # Prefer MP3 (smaller, faster to load in browser)
    mp3_path = STEM_CACHE / song_id / f"{stem}.mp3"
    wav_path = STEM_CACHE / song_id / f"{stem}.wav"
    if mp3_path.exists():
        return FileResponse(str(mp3_path), media_type="audio/mpeg")
    if wav_path.exists():
        return FileResponse(str(wav_path), media_type="audio/wav")
    return Response(status_code=404)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 3002))
    uvicorn.run(app, host="0.0.0.0", port=port)
