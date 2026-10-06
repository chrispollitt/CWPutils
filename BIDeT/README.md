# BIDeT

You know banner. You know FIGlet. You may have heard of TOIlet. This is BIDeT:
big text for the terminal, drawn as SIXEL graphics.

## Use `3D/`

| folder | what | status |
| --- | --- | --- |
| [`3D/`](3D/) | **BIDeT3D**: 1990s WordArt, extruded into real 3D (Python, Pillow, numpy, libsixel) | **current, maintained** |
| [`gfx-conv/`](gfx-conv/) | converters from SIXEL to the kitty and iTerm2 image protocols, to ANSI art and to Tektronix vector graphics | current |
| [`v2/`](v2/) | `bidet2.py`, the Python port of BIDeT | obsolete, **unmaintained** |
| [`v1/`](v1/) | `BIDeT.pl`, the original Perl/Ghostscript/netpbm version (2020) | obsolete, **unmaintained** |

`v1/` and `v2/` are kept for posterity only. **Please don't use them**: they
are not maintained, will not get fixes, and v1 depends on an old, patched
netpbm and a pile of tools that are painful to set up. They may stop working
without notice.

In particular, `v1/fixnetpbm` has been **disabled**. It removed system
packages and installed an unverified `.deb` as root. If anything in v1 (the
Makefile, the man page, `INSTALL`) tells you to run it, don't; BIDeT3D does not need netpbm.

Start here instead:

    cd 3D
    ./bidet3d.py -P superhero "Hello, World!"
    man ./bidet3d.1

See [`3D/README.md`](3D/README.md) for requirements and options.

Demonstration of the original BIDeT: https://youtu.be/TxpBYhGrmH0
