"""Separate the backing vocal stem locally in an isolated, cancellable process."""
import argparse
import os

BVE_MODEL = "UVR-BVE-4B_SN-44100-2.pth"


def separate_backing(vocals_path, output_dir, model_dir):
    import torch
    from audio_separator.separator import Separator

    torch.set_num_threads(max(1, int(os.environ.get("OMP_NUM_THREADS", "1"))))
    torch.set_num_interop_threads(1)
    separator = Separator(
        output_dir=output_dir,
        model_file_dir=model_dir,
        output_format="WAV",
        sample_rate=44100,
        normalization_threshold=1.0,
        amplification_threshold=0.0,
        use_soundfile=True,
        vr_params={"batch_size": 1, "window_size": 512, "aggression": 5,
                   "enable_tta": False, "enable_post_process": False,
                   "post_process_threshold": 0.2, "high_end_process": False},
    )
    separator.load_model(model_filename=BVE_MODEL)
    if not separator.model_instance.is_bv_model:
        raise RuntimeError("O modelo carregado não é um separador de backing vocals.")
    # BVE targets the backing voices in its primary 'Vocals' stem; its
    # complementary 'Instrumental' stem is the lead voice when fed vocals only.
    separator.separate(vocals_path, {"Vocals": "backing_vocals", "Instrumental": "lead_vocals"})
    for filename in ("backing_vocals.wav", "lead_vocals.wav"):
        path = os.path.join(output_dir, filename)
        if not os.path.isfile(path) or os.path.getsize(path) <= 44:
            raise RuntimeError(f"O separador não produziu {filename}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("vocals_path")
    parser.add_argument("output_dir")
    parser.add_argument("model_dir")
    args = parser.parse_args()
    separate_backing(args.vocals_path, args.output_dir, args.model_dir)
