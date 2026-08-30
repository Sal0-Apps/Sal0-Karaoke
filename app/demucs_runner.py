"""Executa a inferência do Demucs e grava os stems sem depender de torchaudio.save."""

import argparse
import gc
import math
from pathlib import Path

import soundfile as sf
import torch
from demucs.api import Separator
from demucs.audio import prevent_clip


def save_wav(
    path: Path,
    waveform: torch.Tensor,
    sample_rate: int,
    *,
    preserve_float: bool = False,
) -> None:
    waveform = waveform.detach().cpu()
    if not preserve_float:
        waveform = prevent_clip(waveform, mode="rescale")
    samples = waveform.transpose(0, 1).numpy()
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, samples, sample_rate, subtype="FLOAT" if preserve_float else "PCM_16")


def separate_target_stem_streaming(
    separator: Separator,
    input_path: Path,
    output_path: Path,
    target_stem: str,
    report_chunk,
    core_seconds: float = 30.0,
    context_seconds: float = 8.0,
) -> None:
    """Processa uma faixa longa em janelas contextualizadas para limitar o pico de memória."""
    with sf.SoundFile(str(input_path), mode="r") as source:
        source_rate = source.samplerate
        total_frames = source.frames
        core_frames = max(1, round(core_seconds * source_rate))
        context_frames = max(0, round(context_seconds * source_rate))
        chunk_count = max(1, math.ceil(total_frames / core_frames))
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with sf.SoundFile(
            str(output_path),
            mode="w",
            samplerate=separator.samplerate,
            channels=separator.audio_channels,
            subtype="FLOAT",
        ) as destination:
            for chunk_index in range(chunk_count):
                core_start = chunk_index * core_frames
                core_end = min(total_frames, core_start + core_frames)
                read_start = max(0, core_start - context_frames)
                read_end = min(total_frames, core_end + context_frames)
                source.seek(read_start)
                samples = source.read(
                    read_end - read_start,
                    dtype="float32",
                    always_2d=True,
                )
                waveform = torch.from_numpy(samples.T.copy())
                report_chunk(chunk_index, chunk_count)
                _, separated = separator.separate_tensor(waveform, sr=source_rate)
                if target_stem not in separated:
                    raise RuntimeError(f"Stem ausente no resultado do Demucs: {target_stem}")

                left_context = round(
                    ((core_start - read_start) / source_rate) * separator.samplerate
                )
                core_length = round(
                    ((core_end - core_start) / source_rate) * separator.samplerate
                )
                target = separated[target_stem][
                    :, left_context:left_context + core_length
                ].detach().cpu()
                destination.write(target.transpose(0, 1).numpy())
                report_chunk(chunk_index + 1, chunk_count)
                del waveform, separated, target, samples
                gc.collect()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", default="htdemucs_ft")
    parser.add_argument("--segment", type=int)
    parser.add_argument("--target-stem", choices=("drums", "bass", "other", "vocals"))
    args = parser.parse_args()

    last_percent = -1
    active_chunk = 0
    active_chunk_count = 1

    def report_chunk(completed: int, total: int) -> None:
        nonlocal active_chunk, active_chunk_count, last_percent
        active_chunk = max(0, min(completed, total))
        active_chunk_count = max(1, total)
        percent = min(99, round((active_chunk / active_chunk_count) * 100))
        if percent != last_percent:
            print(f"DEMUCS_PROGRESS {percent}%", flush=True)
            last_percent = percent

    def report_progress(info: dict) -> None:
        nonlocal last_percent
        models = max(1, int(info.get("models") or 1))
        model_index = max(0, int(info.get("model_idx_in_bag") or 0))
        audio_length = max(1, int(info.get("audio_length") or 1))
        segment_offset = max(0, int(info.get("segment_offset") or 0))
        within_model = min(1.0, segment_offset / audio_length)
        model_fraction = (model_index + within_model) / models
        percent = min(
            99,
            round(((active_chunk + model_fraction) / active_chunk_count) * 100),
        )
        if info.get("state") == "end" and segment_offset >= audio_length:
            percent = min(
                99,
                round(((active_chunk + 1) / active_chunk_count) * 100),
            )
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
    output_folder = Path(args.output) / args.model / Path(args.input).stem
    if args.target_stem:
        separate_target_stem_streaming(
            separator,
            Path(args.input),
            output_folder / f"{args.target_stem}.wav",
            args.target_stem,
            report_chunk,
        )
        print("DEMUCS_PROGRESS 100%", flush=True)
        return

    original, separated = separator.separate_audio_file(Path(args.input))
    vocals = separated["vocals"]
    accompaniment = torch.zeros_like(vocals)
    for name, stem in separated.items():
        if name != "vocals":
            accompaniment += stem
    if not any(name != "vocals" for name in separated):
        accompaniment = original - vocals

    save_wav(output_folder / "vocals.wav", vocals, separator.samplerate)
    save_wav(output_folder / "no_vocals.wav", accompaniment, separator.samplerate)
    print("DEMUCS_PROGRESS 100%", flush=True)


if __name__ == "__main__":
    main()
