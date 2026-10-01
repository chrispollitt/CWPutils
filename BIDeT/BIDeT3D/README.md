# BIDeT3D

You know banner. You know FIGlet. You may have heard of TOIlet. You met BIDeT.

Now it has a third dimension: **1990s WordArt, extruded into real 3D, printed in
your terminal as SIXEL graphics.**

    ./bidet3d.py -P superhero "Hello, World!"
    ./bidet3d.py -P chrome --spin "Spin me"
    ./bidet3d.py --gallery

All 30 presets of [css3wordart](https://github.com/arizzitano/css3wordart) are
here, including the arc / inverted-arc / squeeze baselines that the CSS version
marked "not achievable". Encoding goes through
[libsixel](https://github.com/saitoha/libsixel).

## How it works

    text -> mask -> baseline warp -> material (gradient/texture) + bevel light
         -> stack of depth slices -> perspective camera -> SIXEL (libsixel)

It is a small software renderer (Pillow + numpy), not a font-outline mesher:
the face is one textured quad, the extrusion is a dense stack of shaded
silhouettes seen through a perspective projection, so rotation, pitch, roll
and animation all come from the same math. Near edge-on (yaw ~90) the side
walls show a little banding; raise `SLICE_DENSITY` in the script if it bothers you.

## Requirements

- Python 3 with **Pillow** and **numpy**
- **libsixel**: either its Python binding (`pip install libsixel-python`) or the
  `img2sixel` program. The binding is used when present, `img2sixel` otherwise.
- A SIXEL terminal (see `../TERMINAL-SUPPORT-LIST.txt`: mintty, xterm
  `-ti vt340`, mlterm, WezTerm, foot, iTerm2, ...)
- Fonts: Arial Bold, Times New Roman Bold and Impact are used when found
  (Windows, Cygwin `/cygdrive/c/Windows/Fonts`, WSL, macOS); otherwise
  Liberation / DejaVu; `-f` picks any font file.

## Options

Shared with BIDeT: `-b` background, `-c` colour, `-f` font, `-l` line spacing,
`-p` preserve newlines, `-s` size (pixels; default fits the terminal), `-w` wrap
width, `-d` debug, `-v` version. Text comes from the arguments or stdin.

| option | meaning |
| --- | --- |
| `-P NAME` | preset (`--list-presets`), or `random`; default `rainbow` |
| `--gallery` | show every preset with your text |
| `--depth EM` | extrusion depth |
| `--yaw/--pitch/--roll DEG` | camera angles (`--view=-30,10,0` for all three) |
| `--shape S` | `plain arc inverted-arc squeeze wave` baseline warp |
| `--perspective F` | camera distance in text widths (smaller = more perspective) |
| `--spin`, `--sway DEG` | animate by rotating, or swinging; Ctrl-C stops |
| `--spin-speed`, `--fps`, `--frames` | animation control |
| `--colors N` | SIXEL palette size (default 256) |
| `--png FILE` | write a PNG instead of SIXEL (handy for testing) |
| `--cell WxH` | terminal cell size in pixels if it can't be detected |

The black presets (`up`, `arc`, `squeeze`, ...) used to sit on a light page, so
their "ink" turns white on dark terminals. The terminal background is asked
for with OSC 11 where supported; otherwise use `-b`.

## Textures

Four presets (`green-marble`, `marble-slab`, `paper-bag`, `texture-stack`) use
the Word textures from css3wordart. That repository has **no license file**, so
they are not bundled. Run `./get-textures.sh` to fetch them into `textures/`
(or point `--texture-dir` / `$BIDET3D_TEXTURES` at a css3wordart checkout).
Without them a procedural stand-in is used and everything still works.

## Files

- `bidet3d.py`: everything
- `test.sh`: smoke test (renders every preset to PNG; SIXEL if img2sixel is there)
- `get-textures.sh`: optional texture download
- `3RDPARTY`: what this borrows from, and from whom
