"""Shared helpers for the README capture tools (`capture_demo`, `capture_selector`)."""

from __future__ import annotations

from pathlib import Path


def assemble_gif(
    frame_paths: list[str],
    out: Path,
    *,
    durations: int | list[int],
    colors: int = 128,
) -> None:
    """Quantise the PNG frames and write an optimised looping GIF to *out*.

    *durations* is milliseconds per frame: a single int for a uniform rate, or a
    list with one entry per frame for a scripted timeline.  Requires Pillow
    (in the ``dev`` group).
    """
    from PIL import Image

    out.parent.mkdir(parents=True, exist_ok=True)
    frames = [
        Image.open(p).convert("RGB").quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
        for p in frame_paths
    ]
    frames[0].save(
        out,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
        disposal=2,
    )
