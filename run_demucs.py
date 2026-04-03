"""Custom Demucs runner with progress tracking.
Bypasses broken torchaudio.load on Windows. Writes progress to a JSON file."""

import sys
import os
import json
import time
import torch
import soundfile as sf
import numpy as np
from pathlib import Path


def write_progress(output_dir, stage, percent, detail=""):
    """Write progress to a JSON file that the server can poll."""
    progress_file = Path(output_dir) / "progress.json"
    progress_file.parent.mkdir(parents=True, exist_ok=True)
    progress_file.write_text(json.dumps({
        "stage": stage,
        "percent": percent,
        "detail": detail,
        "timestamp": time.time(),
    }))


def main():
    if len(sys.argv) < 3:
        print("Usage: python run_demucs.py <input.wav> <output_dir>")
        sys.exit(1)

    input_path = sys.argv[1]
    output_dir = sys.argv[2]

    write_progress(output_dir, "loading", 5, "Loading audio file...")

    print(f"Loading audio: {input_path}")
    data, sr = sf.read(input_path)

    # Convert to torch tensor (channels, samples)
    if data.ndim == 1:
        wav = torch.from_numpy(data).float().unsqueeze(0)
    else:
        wav = torch.from_numpy(data.T).float()

    # Ensure stereo
    if wav.shape[0] == 1:
        wav = wav.repeat(2, 1)
    elif wav.shape[0] > 2:
        wav = wav[:2]

    duration_sec = wav.shape[1] / sr
    print(f"Audio: {wav.shape}, sample rate: {sr}, duration: {duration_sec:.0f}s")

    write_progress(output_dir, "model", 10, "Loading AI model...")

    # Load Demucs model
    from demucs.pretrained import get_model
    from demucs.apply import apply_model

    print("Loading Demucs model (htdemucs)...")
    model = get_model("htdemucs")
    model.eval()

    # Resample if needed
    if sr != model.samplerate:
        write_progress(output_dir, "resample", 15, "Resampling audio...")
        print(f"Resampling from {sr} to {model.samplerate}...")
        import torchaudio.functional as F
        wav = F.resample(wav, sr, model.samplerate)

    # Add batch dimension
    wav = wav.unsqueeze(0)  # (1, channels, samples)

    write_progress(output_dir, "separating", 20, "Separating stems (this is the slow part)...")

    # Custom progress callback — Demucs processes in chunks
    # We'll estimate based on audio duration (~1s per second of audio on CPU)
    total_chunks = int(duration_sec / 5.85) + 1  # ~5.85s per chunk
    chunk_count = [0]
    start_time = time.time()

    # Monkey-patch tqdm to capture progress
    original_tqdm = None
    try:
        import tqdm
        original_tqdm = tqdm.tqdm

        class ProgressTqdm:
            def __init__(self, *args, **kwargs):
                self.total = kwargs.get('total', args[0] if args else 100)
                self.n = 0
                self._iter = iter(args[0]) if args and hasattr(args[0], '__iter__') else None

            def __iter__(self):
                if self._iter:
                    for item in self._iter:
                        self.update(1)
                        yield item

            def update(self, n=1):
                self.n += n
                if self.total and self.total > 0:
                    pct = 20 + int((self.n / self.total) * 65)  # 20% to 85%
                    elapsed = time.time() - start_time
                    remaining = (elapsed / max(self.n, 1)) * (self.total - self.n)
                    mins_left = int(remaining / 60)
                    secs_left = int(remaining % 60)
                    write_progress(output_dir, "separating", min(pct, 85),
                        f"Separating: {int(self.n/self.total*100)}% — ~{mins_left}m {secs_left}s remaining")
                    print(f"  Progress: {self.n}/{self.total} ({pct}%)")

            def close(self): pass
            def __enter__(self): return self
            def __exit__(self, *args): pass

        tqdm.tqdm = ProgressTqdm
    except Exception:
        pass

    print("Separating stems...")
    with torch.no_grad():
        sources = apply_model(model, wav, device="cpu", progress=True)

    # Restore tqdm
    if original_tqdm:
        import tqdm
        tqdm.tqdm = original_tqdm

    write_progress(output_dir, "saving", 88, "Saving stem files...")

    # sources shape: (1, num_sources, channels, samples)
    sources = sources.squeeze(0)  # (num_sources, channels, samples)

    # Save each stem
    stem_names = model.sources  # ['drums', 'bass', 'other', 'vocals']
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    for i, name in enumerate(stem_names):
        stem_audio = sources[i].cpu().numpy().T  # (samples, channels)
        stem_file = out_path / f"{name}.wav"
        sf.write(str(stem_file), stem_audio, model.samplerate)
        pct = 88 + int((i + 1) / len(stem_names) * 7)  # 88% to 95%
        write_progress(output_dir, "saving", pct, f"Saved {name}")
        print(f"  Saved: {stem_file}")

    # Convert WAV stems to MP3 for faster browser loading
    ffmpeg_path = Path(__file__).parent / "ffmpeg.exe"
    if ffmpeg_path.exists():
        write_progress(output_dir, "converting", 95, "Converting to MP3...")
        print("Converting to MP3...")
        for name in stem_names:
            wav_file = out_path / f"{name}.wav"
            mp3_file = out_path / f"{name}.mp3"
            try:
                import subprocess
                subprocess.run(
                    [str(ffmpeg_path), "-i", str(wav_file), "-b:a", "192k", str(mp3_file), "-y"],
                    capture_output=True, timeout=30,
                )
                print(f"  Converted: {mp3_file}")
            except Exception as e:
                print(f"  MP3 conversion failed for {name}: {e}")

    write_progress(output_dir, "done", 100, "Complete!")
    print("Done!")


if __name__ == "__main__":
    main()
