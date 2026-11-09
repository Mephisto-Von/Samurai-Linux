#!/usr/bin/env python3
"""Neurally upscale the Samurai art collection before it is wallpapended.

The sources in ``Samurai Walls/`` are 236-760 px wide, which is not 4K by any
measure: a plain Lanczos stretch to 3840 px is visibly an enlargement (a fact
the whole "looks like depth of field" pipeline in ``make-wallpapers.py`` was
compensating for). This script runs a Real-ESRGAN animevideo-v3 model
(SRVGGNetCompact, 4x, by design small and fast - it is the model that restores
line work and cel texture in anime illustration rather than pretending to be
a photo model) over each thumbnail, so the images ``make-wallpapers.py``
consumes carry real, model-synthesised detail instead of a blur.

Workflow:

    python build/upscale-nn.py --out .tmp/upscaled
    python build/make-wallpapers.py --source .tmp/upscaled

The upscaled intermediates are NOT committed: at 4x they are larger than the
wallpapers themselves. The thumbnails in ``Samurai Walls/`` remain the only
committed source art; the neural pass is how the committed 4K files are made,
and the fact that it is one is part of their provenance (see
``samurai/docs/known-limitations.md``).

Model: the ONNX conversion of ``realesr-animevideov3.pth`` upstream
(https://github.com/xinntao/Real-ESRGAN, BSD-3-Clause) published as
``model.onnx`` at https://huggingface.co/skillsafe-ai/realesr-animevideov3
(input ``input``: float32 NCHW; output ``output``: float32 NCHW x4). Run with
--model to test another file with the same contract.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = REPO_ROOT / "Samurai Walls"
DEFAULT_OUT = REPO_ROOT / ".tmp" / "upscaled"
DEFAULT_MODEL = REPO_ROOT / ".tmp" / "models" / "realesr-animevideov3-x4.onnx"

MODEL_URL = "https://huggingface.co/skillsafe-ai/realesr-animevideov3/resolve/main/model.onnx"

#: realesr-animevideov3 is a 4x model. Rank by *output* width to choose tiles.
SCALE = 4
#: Pixels of context fed around each tile. Too little and the seams show;
#: SRVGGNetCompact's receptive field is modest, so 16 is plenty.
PAD = 16
#: Input tile side. 512 keeps a CPU session comfortable on 4 GB of RAM.
TILE = 512


def _run_tile(session, image: np.ndarray) -> np.ndarray:
    tensor = np.ascontiguousarray(image.transpose(2, 0, 1)[None], dtype=np.float32)
    return session.run(None, {"input": tensor})[0][0].transpose(1, 2, 0)


def upscale_image(session, image: Image.Image, tile: int = TILE, pad: int = PAD) -> Image.Image:
    """Run the model over ``image`` with reflection padding and tile stitching."""
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    height, width = rgb.shape[:2]

    # The SRVGG family convolves with stride and pixel-shuffles: the spatial
    # size must be a multiple of 8 or the output shifts. Reflect, run, crop.
    def _padded(value: int) -> int:
        return ((value + 7) // 8) * 8

    padded = np.pad(rgb, ((0, _padded(height) - height), (0, _padded(width) - width), (0, 0)), mode="reflect")
    tiled = np.zeros((padded.shape[0] * SCALE, padded.shape[1] * SCALE, 3), dtype=np.float32)

    for y in range(0, padded.shape[0], tile):
        for x in range(0, padded.shape[1], tile):
            y2, x2 = min(y + tile, padded.shape[0]), min(x + tile, padded.shape[1])
            context_y, context_x = max(y - pad, 0), max(x - pad, 0)
            chunk = padded[context_y : y2 + pad, context_x : x2 + pad]
            result = _run_tile(session, chunk)
            # Crop away the context the model saw but did not need to render.
            tiled[y * SCALE : y2 * SCALE, x * SCALE : x2 * SCALE] = result[
                (y - context_y) * SCALE : (y2 - context_y) * SCALE,
                (x - context_x) * SCALE : (x2 - context_x) * SCALE,
            ]

    tiled = np.clip(tiled, 0.0, 1.0)[: height * SCALE, : width * SCALE]
    return Image.fromarray((tiled * 255.0 + 0.5).astype(np.uint8), mode="RGB")


def iter_sources(source: Path):
    for path in sorted(source.iterdir()):
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".jfif", ".png", ".webp"}:
            yield path


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--tile", type=int, default=TILE)
    parser.add_argument("--quality", type=int, default=95)
    args = parser.parse_args(argv)

    try:
        import onnxruntime as ort
    except ImportError:
        print("onnxruntime is required: python -m pip install onnxruntime", file=sys.stderr)
        return 2

    if not args.model.is_file():
        print(
            f"model not found: {args.model}\n"
            f"  download it with:\n  curl -L -o {args.model} {MODEL_URL}",
            file=sys.stderr,
        )
        return 2

    session = ort.InferenceSession(str(args.model), providers=["CPUExecutionProvider"])
    args.out.mkdir(parents=True, exist_ok=True)

    sources = list(iter_sources(args.source))
    if not sources:
        print(f"no pictures in {args.source}", file=sys.stderr)
        return 2

    for source in sources:
        # Same filename as the thumbnail: make-wallpapers.py looks pictures up
        # by their original names, so this dir is a drop-in --source replacement.
        target = args.out / source.name
        import time

        started = time.perf_counter()
        with Image.open(source) as image:
            upscaled = upscale_image(session, image, tile=args.tile)
        upscaled.save(target, quality=args.quality)
        elapsed = time.perf_counter() - started
        print(f"{source.name} -> {upscaled.size} ({target.name}, {elapsed:.1f}s)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
