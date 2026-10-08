# BIDeT

You know banner. You know FIGlet. You may have heard of TOIlet. This is BIDeT:
big text for the terminal, drawn as SIXEL graphics.

## Which folder?

| folder | what | status |
| --- | --- | --- |
| [`4D/`](4D/) | **BIDeT 4D**: the BIF image format (`.bif`) and its tools. `bifin` turns terminal art (cowsay, figlet, ANSI and DOS art, jp2a / chafa output) into a BIF of vectors and rasters, `bifout` draws a BIF as PNG or SIXEL at any size. Python, Pillow, numpy; no libsixel. | **current, in development** |
| [`3D/`](3D/) | **BIDeT3D**: 1990s WordArt, extruded into real 3D (Python, Pillow, numpy, libsixel). Holds [`3D/unascii/`](3D/unascii/) (art back to a line drawing) and [`3D/gfx-conv/`](3D/gfx-conv/) (SIXEL to kitty, iTerm2, ANSI art, Tektronix). | **legacy**: it works, but gets no new features or fixes. Until 4D has its own 3D step, it is the only tool here that makes 3D WordArt. |
| [`v2/`](v2/) | `bidet2.py`, the Python port of BIDeT | obsolete, **unmaintained** |
| [`v1/`](v1/) | `BIDeT.pl`, the original Perl/Ghostscript/netpbm version (2020) | obsolete, **unmaintained** |

`v1/` and `v2/` are kept for posterity only. **Please don't use them**: they
are not maintained, will not get fixes, and v1 depends on an old, patched
netpbm and a pile of tools that are painful to set up. They may stop working
without notice.

In particular, `v1/fixnetpbm` has been **disabled**. It removed system
packages and installed an unverified `.deb` as root. If anything in v1 (the
Makefile, the man page, `INSTALL`) tells you to run it, don't; BIDeT3D and BIDeT 4D do not need netpbm.

Start here instead.

For 3D WordArt:

    cd 3D
    ./bidet3d.py -P superhero "Hello, World!"
    man ./bidet3d.1

See [`3D/README.md`](3D/README.md) for requirements and options.

For terminal art (turn it into a BIF, draw it at any size, change its colours):

    cd 4D
    ./bifin.py ../3D/unascii/samples/cow.txt | ./bifout.py -s
    ./bifin.py art.ans -o art.bif && ./bifout.py art.bif -o art.png --scale 3 --ink "#00ff66" --paper "#101820"

See [`4D/README.md`](4D/README.md) for the tools and [`4D/BIF-SPEC.md`](4D/BIF-SPEC.md) for the file format,
which is written so that others can build on it.

Demonstration of the original BIDeT: https://youtu.be/TxpBYhGrmH0
