"""Microphone capture and speech-to-text using faster-whisper."""

import tempfile
import threading
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf
from faster_whisper import WhisperModel

from jarvis.config import WHISPER_MODEL, SAMPLE_RATE, CHANNELS


class Listener:
    def __init__(self):
        self._model = None

    def _ensure_model(self):
        if self._model is None:
            print("[Whisper] Loading speech recognition model...")
            self._model = WhisperModel(
                WHISPER_MODEL, device="cpu", compute_type="int8"
            )
            print("[Whisper] Ready.")

    def listen_push_to_talk(self) -> str | None:
        """Record while user holds Enter, transcribe when released.

        Returns transcribed text or None.
        """
        self._ensure_model()

        frames = []
        recording = True

        def callback(indata, frame_count, time_info, status):
            if recording:
                frames.append(indata.copy())

        stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            callback=callback,
        )

        with stream:
            input()  # Wait for Enter to stop recording
            recording = False

        if not frames:
            return None

        audio = np.concatenate(frames)
        rms = np.sqrt(np.mean(audio.astype(np.float32) ** 2))
        if rms < 10:
            return None

        # Save and transcribe
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp_path = tmp.name
        tmp.close()

        try:
            sf.write(tmp_path, audio, SAMPLE_RATE)
            segments, _ = self._model.transcribe(
                tmp_path, language="en", beam_size=3, vad_filter=True,
                initial_prompt="Kalshi, portfolio, trades, JARVIS, sir",
            )
            text = " ".join(seg.text.strip() for seg in segments).strip()
            return text if text else None
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def cleanup(self):
        pass
