"""FastAPI server for JARVIS web interface."""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
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
    JARVIS_VOICE,
    TTS_ENGINE,
)

# Import tools to register them
from jarvis.tools import system as _s  # noqa
from jarvis.tools import kalshi as _k  # noqa
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


@app.post("/api/chat")
async def chat(req: ChatRequest):
    response = brain.think(req.message)
    return {"response": response}


@app.post("/api/tts")
async def tts(req: TTSRequest):
    text = fix_pronunciation(req.text)
    if not text:
        return Response(status_code=400)

    # Try ElevenLabs first
    if TTS_ENGINE == "elevenlabs" and ELEVENLABS_API_KEY:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
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
                return Response(content=resp.content, media_type="audio/mpeg")
        except Exception:
            pass

    # Fallback to Edge TTS
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp_path = tmp.name
    tmp.close()
    try:
        communicate = edge_tts.Communicate(text, JARVIS_VOICE, rate="-10%", pitch="-5Hz")
        await communicate.save(tmp_path)
        audio_bytes = Path(tmp_path).read_bytes()
        return Response(content=audio_bytes, media_type="audio/mpeg")
    finally:
        Path(tmp_path).unlink(missing_ok=True)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3001)
