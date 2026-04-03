"""Custom Demucs runner that bypasses broken torchaudio.load on Windows.
Uses soundfile to load audio, then runs Demucs separation directly."""

import sys
import os
import torch
import soundfile as sf
import numpy as np
from pathlib import Path

def main():
    if len(sys.argv) < 3:
        print("Usage: python run_demucs.py <input.wav> <output_dir>")
        sys.exit(1)

    input_path = sys.argv[1]
    output_dir = sys.argv[2]

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

    print(f"Audio: {wav.shape}, sample rate: {sr}")

    # Load Demucs model
    from demucs.pretrained import get_model
    from demucs.apply import apply_model

    print("Loading Demucs model (htdemucs)...")
    model = get_model("htdemucs")
    model.eval()

    # Resample if needed
    if sr != model.samplerate:
        print(f"Resampling from {sr} to {model.samplerate}...")
        import torchaudio.functional as F
        wav = F.resample(wav, sr, model.samplerate)

    # Add batch dimension
    wav = wav.unsqueeze(0)  # (1, channels, samples)

    print("Separating stems... (this takes a minute)")
    with torch.no_grad():
        sources = apply_model(model, wav, device="cpu", progress=True)

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
        print(f"  Saved: {stem_file}")

    # Convert WAV stems to MP3 for faster browser loading
    ffmpeg_path = Path(__file__).parent / "ffmpeg.exe"
    if ffmpeg_path.exists():
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

    print("Done!")

if __name__ == "__main__":
    main()
