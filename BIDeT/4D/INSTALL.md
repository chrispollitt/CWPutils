# Installing BIDeT 4D

BIDeT 4D (`bidet`, `bifin`, `bifop`, `bifout` and the BIF library `bif.py`) is plain Python. Nothing is compiled,
nothing needs root to try, and nothing needs libsixel: SIXEL is written by the program itself.

Contents: [1 Try it in place](#1-try-it-in-place) · [2 Prerequisites](#2-prerequisites) ·
[3 Installing](#3-installing) · [4 Terminals](#4-terminals-and-sixel) · [5 Fonts](#5-fonts) ·
[6 Optional extras](#6-optional-extras) · [7 Pictures](#7-the-pictures-in-gallery) ·
[8 Environment](#8-environment-variables) · [9 Tests](#9-tests) · [10 Removing it](#10-uninstalling-and-cleaning-up) ·
[11 Troubleshooting](#11-troubleshooting)

## 1. Try it in place

From this folder, once the prerequisites below are there:

    ./bidet.py "Hello, World!"                            # on a SIXEL terminal: drawn there
    ./bidet.py -P chrome "Hello" -o hello.png             # a file instead
    ./bidet.py -P popout "Hello" -o hello.gif             # 2D to 3D: it pops out of the screen
    cowsay moo | ./bidet.py -P bold -o moo.png            # terminal art, from a pipe
    ./bidet.py --list-presets

On Windows without a shell, run `python bidet.py ...`. The tools find their modules next to themselves, so they run
from wherever you leave them, or through a symlink (that is how `make install` links them).

## 2. Prerequisites

| needed | version | for |
| --- | --- | --- |
| Python | 3.7 or newer | everything |
| numpy | 1.16 or newer | everything |
| Pillow | 5.4 or newer | drawing, PNG, GIF |
| a TrueType font | any | text (the system's are found; see [Fonts](#5-fonts)) |
| a SIXEL terminal | | live pictures and animations; not needed for files |
| `make` | | `make test`, `make install`; not needed to run |

Those are the oldest versions the code is written for (`requirements.txt`). The tests have been run on Python 3.8 /
numpy 1.17 / Pillow 7.0 (WSL, Ubuntu 20.04), on Python 3.11 / numpy 2.2 / Pillow 11 (Windows) and on Python 3.12 /
numpy 2.5 / Pillow 12.3 (Cygwin). The stated minimum, Python 3.7 with Pillow 5.4 and numpy 1.16, has **not** been run.

How to get them:

- **Debian, Ubuntu, Raspberry Pi OS, WSL**: `sudo make installreq` (it runs `apt install python3 python3-pil python3-numpy`).
- **Cygwin**: Cygwin setup for Python 3, then a Pillow and a numpy for it, or
  `python3 -m pip install -r requirements.txt`.
- **Windows**: Python from python.org, then `py -m pip install -r requirements.txt`; run `python bidet.py`.
- **macOS**: `brew install python`, then `python3 -m pip install -r requirements.txt`. (Not tried by the author.)
- **Anywhere**: `python3 -m pip install -r requirements.txt`.

## 3. Installing

Optional: it is only to have the commands on your path and the man pages.

    sudo make install                     # PREFIX=/usr/local; DESTDIR=... for packaging
    make PREFIX=$HOME/.local install      # no root: into ~/.local (put ~/.local/bin on your PATH)
    make help                             # every target

What goes where (relative to `PREFIX`):

| what | where |
| --- | --- |
| `bif`, `bifin`, `bifop`, `bifout`, `bidet` | `bin/`, as links to the files in `share/BIDeT4D/` |
| the modules, and `presets.ini` | `share/BIDeT4D/` (a tool runs from there, so it finds them) |
| `README.md`, `BIF-SPEC.md`, `HANDOFF.md` | `share/doc/bidet4d/` |
| `bidet.1`, `bifin.1`, `bifop.1`, `bifout.1` | `share/man/man1/` |

`make dist` makes `bidet4d-VERSION.tar.gz`: the sources, tests, samples, test data and documents. Your own presets
go in `~/.config/bidet/presets.ini` ([8](#8-environment-variables) says how to put them elsewhere).

## 4. Terminals and SIXEL

On a terminal, `bifout` and `bidet` send what the terminal can show (`-f auto`, the default): SIXEL if it has it, the kitty
or iTerm2 image protocol if it says it is kitty (or Ghostty) or iTerm2, else coloured Unicode text, which any UTF-8 terminal
shows. To decide, `bifout` asks the terminal whether it has SIXEL (the DA1 reply) and, if it is going to draw on the
terminal's own background, what that colour is (OSC 11) and how big a character cell is (CSI 16 t). `-f sixel` by name
is checked: a terminal that says it has no SIXEL gets an error, not garbage. `python bifterm.py` shows what yours says.
`-f kitty`, `-f iterm`, `-f ansi` and `-f tek` (Tektronix, for `xterm -t`) choose a format yourself; `-o x.ans` writes coloured
text you can `cat` anywhere.

**Your mileage may vary.** SIXEL support differs from terminal to terminal, and animation puts it under the most
strain. Live pictures are well tested in **mintty** only. In **Windows Terminal**, when the tools do not know its
background colour, animations show noise and leftover pixels of earlier frames; when it does know it (see the Cygwin
note below) a spinning 3D animation played clean. WezTerm, foot, `xterm -ti vt340`,
mlterm and iTerm2 have not been tried by the author. Files are the dependable way: `-o x.png`, and `-o x.gif` for
an animation.

**Cygwin in Windows Terminal: the background colour is not found.** Windows Terminal itself answers the colour
question (OSC 11), but Cygwin's own console, the tty (`/dev/cons0`) of a tab that starts `bash` directly, swallows the
question on its way out. There `bifout` asks SIXEL support only (that works), assumes a dark background, and says so
once on stderr (delete `~/.cache/bidet/cygwin-console-warned`, or the same file under `$BIDET_CACHE`, to see the note
again). Give the colour yourself with `-b '#RRGGBB'`, or use one of these:

- run `bash` on a pty with **wincygterm** (CWPutils/toolbox; it needs a native Windows Python): `python wincygterm
  --login-dir` in a Windows Terminal tab, or make the output of `python wincygterm --profile` the *Command line* of a
  profile. The shell has a pty (`/dev/pty0`), no ssh and no `sshd` are needed, and the colour question gets through
  (`termprobe` there says `ANSWERED`; checked with Windows Terminal 1.24 and a Cygwin 3.7 development snapshot).
  Animations were not replayed under it, but what made them noisy, not knowing the colour, is gone; or
- run in **mintty**, which is a pty and answers; or
- the clunky workaround, tested on two Windows 11 machines with Windows Terminal 1.24 and Cygwin 3.6.11: do not use the
  Cygwin tab. Open a **PowerShell** tab and log in to the same machine with *Windows'* OpenSSH client, which needs the
  Cygwin `sshd` running there:

      C:\Windows\System32\OpenSSH\ssh.exe MACHINE-NAME

  The shell you land in has a pty (`/dev/pty0`) and the colour question gets through (`termprobe` there says
  `ANSWERED`, in about 50 ms), and animations played live show no noise. Tried with the machine's own name;
  `localhost` was not retried with this client. To make it permanent, give Windows Terminal a profile whose
  *Command line* is `c:\windows\system32\openssh\ssh.exe MACHINE-NAME` (Settings, Add a new profile, e.g. named
  "Cygwin"): every tab of it is then such a login.

`termprobe` (CWPutils/toolbox) shows what a given way of reaching the terminal does with the question.

## 5. Fonts

`bidet --list-fonts` lists the TrueType families it found; `bidet -F impact "Sale"` or `-F /path/to/face.ttf`
chooses one. Generic names (`sans`, `serif`, `mono`, `impact`, `script`, `comic`, `times`, `arial`, `courier`,
`georgia`) each fall back to what the system has, so a preset that asks for `impact` still works without it. Fonts are
looked for in the usual places for Windows, Cygwin, WSL, macOS and Linux, and the catalogue is cached in
`~/.cache/bidet/fonts.json` (`BIDET_CACHE` moves it). No font is bundled.

## 6. Optional extras

- `banner`, `figlet`, `toilet`: `bidet --time-machine` uses the real programs if they are installed
  (`figlet` and `toilet` are in most distributions; `banner` is rarer) and draws imitations from a font if not
  (`BIDET_EMULATE=1` forces the imitations).
- `groff`: `make lint` checks the man pages with it when it is there.
- `fortune`, `figlet`, `toilet`, `cowsay`, `boxes`, `ffmpeg`, `img2txt` (libcaca), `curl`: ingredients of the pipelines in
  [`RECIPES.md`](RECIPES.md); none is needed by BIDeT itself.
- `git`: the pictures in `gallery/` are a separate branch ([7](#7-the-pictures-in-gallery)).

## 7. The pictures in `gallery/`

The gallery pictures and animations are not part of the main branch. They are the `media` branch, which holds only
the latest of them as one commit, mounted here as a git worktree. In a fresh clone:

    git fetch origin media && make media-checkout

`make gallery`, `make gallery-gif` and `make time-machine` redraw them; `make media` records them (replacing the
branch's one commit); `make publish-media` force-pushes just that branch, if you want it on a remote at all.

## 8. Environment variables

| variable | effect |
| --- | --- |
| `BIDET_NO_QUERY=1` | never ask the terminal anything (the tests set it) |
| `LSIX_FORCE_SIXEL_SUPPORT=1` | send SIXEL even if the terminal does not say it can (`--force`) |
| `KITTY_WINDOW_ID`, `TERM`, `TERM_PROGRAM`, `LC_TERMINAL` | read by `-f auto` to tell kitty / Ghostty and iTerm2 from the rest |
| `BIDET_CELL=WxH` | the size of a character cell in pixels, if the terminal will not say (`--cell`) |
| `COLORFGBG` | read, when the terminal will not say its colours, to guess light or dark |
| `BIDET_PRESETS=FILE` | an extra presets file, read after the shipped one |
| `XDG_CONFIG_HOME` | where your own `bidet/presets.ini` is (default `~/.config`) |
| `BIDET_CACHE`, `XDG_CACHE_HOME` | where the font catalogue is cached (default `~/.cache/bidet`) |
| `BIDET_EMULATE=1` | the time machine draws its own banner / figlet / toilet even if the real ones exist |

## 9. Tests

    make lint            # syntax of every program and test, the shell scripts, the man pages
    make test-quick      # the unit suites: library, renderer, importers, tracer, operations, bidet, animation, 3D
    make test            # the same, and a smoke subset of the parity gate (several minutes)
    make test-full       # everything, including the full parity matrix (about ten minutes)
    make PYTHON=python3.8 test-quick

The tests are self-contained: they write their own font, use the `samples/` here, and never ask your terminal anything.
While developing, one platform and `make test-quick` are enough; `test-full` and a second platform are for milestones
(see `DEVNOTES.txt`).

## 10. Uninstalling and cleaning up

    sudo make uninstall                   # the links, the modules, the documents and the man pages
    make clean                            # generated files here: tarballs, __pycache__ folders, out/

Nothing else is written outside this folder, except `~/.cache/bidet/fonts.json` (the font catalogue) and any
`~/.config/bidet/presets.ini` you made yourself.

## 11. Troubleshooting

| you see | what to do |
| --- | --- |
| `your terminal does not report having SIXEL graphics support` (only when you said `-f sixel`) | use a SIXEL terminal (mintty, WezTerm, foot, `xterm -ti vt340`, mlterm ...), or `--force`, or `-f auto` / `-f ansi` for what the terminal can show, or write a file with `-o x.png` |
| a blank picture from a few words | the words were taken for art: say `-t` (text) or `--art` (art) |
| text in the wrong font, or "no font" | `bidet --list-fonts`; install a TrueType font or give `-F FILE.ttf`; delete `~/.cache/bidet/fonts.json` if you added fonts |
| a picture wider than the terminal, or clipped | `-w PX`, or `--cell WxH` if the terminal will not say its cell size |
| animation is slow or stutters | a smaller `-w`, `--fps 8`, or write a GIF |
| noise or leftover pixels in an animation | some terminals (Windows Terminal) do this: try `reset`, or write a GIF; see [Terminals](#4-terminals-and-sixel) |
| `make` is not found (Windows) | not needed to run: `python bidet.py ...`; use Cygwin or Git Bash for the Makefile |
| a test fails on your machine only | run it again with `python tests/test_NAME.py`, and say which Python, Pillow and numpy you have (`python -c "import PIL, numpy; print(PIL.__version__, numpy.__version__)"`) |

More: `README.md` (the tools, the presets, the gallery), `BIF-SPEC.md` (the file format), `DEVNOTES.txt` (for
people changing the code), and the man pages `bidet(1)`, `bifin(1)`, `bifop(1)` and `bifout(1)`.
