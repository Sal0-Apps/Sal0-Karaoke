"""Executa a inferência do Demucs e grava os stems sem depender de torchaudio.save."""

import argparse
from pathlib import Path

import soundfile as sf
import torch
from demucs.api import Separator
from demucs.audio import prevent_clip


def save_wav(path: Path, waveform: torch.Tensor, sample_rate: int) -> None:
    waveform = prevent_clip(waveform.detach().cpu(), mode="rescale")
    samples = waveform.transpose(0, 1).numpy()
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, samples, sample_rate, subtype="PCM_16")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", default="htdemucs_ft")
    parser.add_argument("--segment", type=int)
    args = parser.parse_args()

    last_percent = -1

    def report_progress(info: dict) -> None:
        nonlocal last_percent
        models = max(1, int(info.get("models") or 1))
        model_index = max(0, int(info.get("model_idx_in_bag") or 0))
        audio_length = max(1, int(info.get("audio_length") or 1))
        segment_offset = max(0, int(info.get("segment_offset") or 0))
        within_model = min(1.0, segment_offset / audio_length)
        percent = min(99, round(((model_index + within_model) / models) * 100))
        if info.get("state") == "end" and segment_offset >= audio_length:
            percent = min(99, round(((model_index + 1) / models) * 100))
        if percent != last_percent:
            print(f"DEMUCS_PROGRESS {percent}%", flush=True)
            last_percent = percent

    separator = Separator(
        model=args.model,
        device="cpu",
        shifts=1,
        overlap=0.25,
        split=True,
        segment=args.segment,
        jobs=0,
        progress=False,
        callback=report_progress,
    )
    original, separated = separator.separate_audio_file(Path(args.input))
    vocals = separated["vocals"]
    accompaniment = torch.zeros_like(vocals)
    for name, stem in separated.items():
        if name != "vocals":
            accompaniment += stem
    if not any(name != "vocals" for name in separated):
        accompaniment = original - vocals

    output_folder = Path(args.output) / args.model / Path(args.input).stem
    save_wav(output_folder / "vocals.wav", vocals, separator.samplerate)
    save_wav(output_folder / "no_vocals.wav", accompaniment, separator.samplerate)
    print("DEMUCS_PROGRESS 100%", flush=True)


if __name__ == "__main__":
    main()
