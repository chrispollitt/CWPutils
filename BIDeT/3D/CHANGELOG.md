# Changelog

## Unreleased

- ASCII art: `-a/--art` keeps lines aligned (they were each centred separately), uses a monospace
  font, no letter-spacing and tighter lines (0.9). Piped multi-line art (cowsay, figlet, boxes) is
  detected automatically; `--no-art` turns that off. `-l` now defaults to per-mode, not 1.0.
- `--time-machine` (with `--stage-time`): banner, FIGlet, TOIlet, BIDeT and BIDeT3D, in that
  order. Uses the real programs when installed, imitations otherwise (`BIDET3D_EMULATE`).
- Animation internals split into `render_loop` / `play_loop` (no change in behaviour).

## 0.1 (2026-10-01)

First release.

- 30 css3wordart WordArt presets rendered as real 3D (software renderer, Pillow + numpy),
  including the arc / inverted-arc / squeeze baselines; wave baseline.
- Camera control (`--view`, `--yaw`, `--pitch`, `--roll`, `--perspective`), `--depth`, `--shape`.
- `--spin` / `--sway` animation: one seamless pre-rendered loop on a shared palette.
- SIXEL output via the libsixel Python binding or `img2sixel`; SIXEL support check (DA1);
  terminal background detection (OSC 11) with exact background colour through quantization;
  transparent-sixel fallback for terminals that will not report it (Windows Terminal).
- BIDeT-compatible options (`-b -c -f -l -p -s -w -d -v`).
- Works with old libraries: Python 3.7, Pillow 5.4, numpy 1.16 and up.
- Man page (`bidet3d.1`), Makefile, smoke test (`test.sh`).
