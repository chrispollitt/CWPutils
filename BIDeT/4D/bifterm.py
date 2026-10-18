#!/usr/bin/env python3
"""bifterm: ask the terminal what it can do.

    r = bifterm.query()            # -> Reply(sixel, bg, cell, asked)
    r.sixel                        True / False (DA1 lists SIXEL or not), None if the terminal did not answer
    r.bg                           (r, g, b) of its background colour (OSC 11), None if it would not say
    r.cell                         (width, height) of a character cell in pixels (CSI 16 t), None if unknown
    r.asked                        there was a terminal to ask (False: no tty, not POSIX, BIDET_NO_QUERY set)

First "what are you?" (DA1) alone: a terminal that does not list SIXEL is asked nothing more.  The others are
then asked for the background colour and the cell size in one go, ending with DA1 again: it comes back last, so
it marks the end of the answers, and a terminal that ignores OSC 11 costs no waiting.  Only
a terminal that does not answer at all costs `timeout` seconds.  The conversation is with the controlling
terminal (/dev/tty), not stdin / stdout, so it works in `bifin | bifout -s` and when the output is piped.
POSIX only (Linux, WSL, macOS, Cygwin, mintty); elsewhere nothing is asked and callers go on without answers.
BIDET_NO_QUERY=1 turns asking off.  `python bifterm.py` shows what your terminal says.

Cygwin's own console (a tab that runs bash directly: Windows Terminal, conhost; the tty is /dev/cons*) swallows OSC
strings on their way out, so an OSC 11 query never reaches the terminal, which would have answered it (measured
with Windows Terminal 1.24: a native Windows program in the same tab gets the colour; mintty and ssh sessions are
other paths).  There only DA1 is asked, and the user is told once (see `warn_once`).

The parsers (parse_da1, parse_osc11, parse_cell) are plain functions so they can be tested without a terminal.
Python 3.7+.
"""
from __future__ import print_function

import collections
import os
import re
import select
import sys
import time

Reply = collections.namedtuple("Reply", "sixel bg cell asked", defaults=(True,))
NOTHING = Reply(None, None, None, False)                      # there was no terminal to ask (or asking is off)

OSC11 = "\x1b]11;?\x1b\\"
CELL = "\x1b[16t"
DA1 = "\x1b[c"
_DA1 = re.compile(r"\x1b\[\?([0-9;]*)c")
_BG = re.compile(r"\x1b\]11;rgba?:([0-9a-fA-F]+)/([0-9a-fA-F]+)/([0-9a-fA-F]+)")
_CELL = re.compile(r"\x1b\[6;(\d+);(\d+)t")


def parse_da1(text):
    """True if the DA1 reply lists SIXEL (attribute 4), False if it does not, None if there is no reply."""
    m = _DA1.search(text)
    return None if not m else "4" in m.group(1).split(";")


def parse_osc11(text):
    """(r, g, b) 0..255 from an OSC 11 reply (rgb:RRRR/GGGG/BBBB, any digits per channel), or None."""
    m = _BG.search(text)
    if not m:
        return None
    try:
        return tuple(int(round(int(g, 16) / float(16 ** len(g) - 1) * 255)) for g in m.groups())
    except (ValueError, ZeroDivisionError):
        return None


def parse_cell(text):
    """(width, height) of a cell in pixels from a CSI 16 t reply (which says height;width), or None."""
    m = _CELL.search(text)
    if not m or int(m.group(1)) <= 0 or int(m.group(2)) <= 0:
        return None
    return float(m.group(2)), float(m.group(1))


def parse(text):
    return Reply(parse_da1(text), parse_osc11(text), parse_cell(text), bool(text))


def luminance(rgb):
    """0 (black) .. 1 (white), a plain weighting of the channels."""
    return (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255.0


def cygwin_console(ttyname, platform=None):
    """Is `ttyname` (os.ttyname of the tty) Cygwin's own console, which eats OSC queries?"""
    return (sys.platform if platform is None else platform) == "cygwin" and (ttyname or "").startswith("/dev/cons")


def warn_once(env=None, stream=None):
    """Tell the user, on stderr and once ever (a marker file beside the font cache), that Cygwin's console hides the
    terminal's colour.  Returns True if it printed.  Never raises."""
    env = os.environ if env is None else env
    base = env.get("BIDET_CACHE") or os.path.join(env.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache"), "bidet")
    marker = os.path.join(base, "cygwin-console-warned")
    try:
        if os.path.exists(marker):
            return False
    except OSError:
        return False
    (stream or sys.stderr).write(
        "bifterm: Cygwin's console swallows the query for the terminal's background colour, so a dark one is assumed.\n"
        "         Give the colour yourself (-b '#RRGGBB', --dark / --light in bidet), run in mintty, or ssh in from a\n"
        "         PowerShell tab with Windows' ssh.exe (see INSTALL.md, Terminals).  Said once;\n"
        "         delete %s to see this again.\n" % marker)
    try:
        if not os.path.isdir(base):
            os.makedirs(base)
        with open(marker, "w") as f:
            f.write("bifterm told the user that Cygwin's console eats OSC 11\n")
    except OSError:
        pass
    return True


def _ttyname(fd):
    try:
        return os.ttyname(fd)
    except OSError:
        return ""


def exchange(rfd, wfd, seq, timeout=1.0, tail=0.25):
    """Write `seq` to wfd and read what comes back from rfd, until a DA1 reply has arrived or `timeout` seconds
    pass (then `tail` more for a straggler that began).  Returns the text."""
    os.write(wfd, seq.encode("latin1"))
    text = ""
    deadline = time.time() + timeout
    while len(text) < 4096:
        left = deadline - time.time()
        if left <= 0 or not select.select([rfd], [], [], left)[0]:
            break
        chunk = os.read(rfd, 256)
        if not chunk:
            break
        text += chunk.decode("latin1")
        if _DA1.search(text):
            break
        deadline = min(deadline, time.time() + tail)             # something is coming: it will not be long
    return text


def query(want_bg=True, want_cell=True, timeout=1.0, debug=False, env=None):
    """Ask the controlling terminal; see the module docstring.  Never raises.  `asked` of the Reply says whether
    there was a terminal to ask (then a silent one has sixel None); without one the answer is NOTHING."""
    env = os.environ if env is None else env
    if os.name != "posix" or env.get("BIDET_NO_QUERY"):
        return NOTHING
    if env.get("TERM", "").startswith("yaft"):
        return Reply(True, (0, 0, 0), None, True)           # yaft cannot answer DA1
    try:
        import termios
        import tty
        fd = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY)
    except (ImportError, OSError):
        return NOTHING
    try:
        old = termios.tcgetattr(fd)
    except Exception:
        os.close(fd)
        return NOTHING
    if (want_bg or want_cell) and cygwin_console(_ttyname(fd)):
        if want_bg:
            warn_once(env)
        want_bg = want_cell = False                          # asked anyway they would be eaten: DA1 alone still works
    texts = []
    try:
        tty.setcbreak(fd, termios.TCSANOW)
        # first only "what are you?": a terminal without SIXEL is not shown the colour and size questions it may
        # not understand (a console could print them); the others get them, with DA1 again behind them as the end mark
        texts.append(exchange(fd, fd, DA1, timeout))
        if parse_da1(texts[0]) and (want_bg or want_cell):
            texts.append(exchange(fd, fd, (OSC11 if want_bg else "") + (CELL if want_cell else "") + DA1, min(timeout, 1.0)))
    except Exception:
        pass
    finally:
        try:
            termios.tcflush(fd, termios.TCIFLUSH)            # drop a reply that comes too late
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        finally:
            os.close(fd)
    text = "".join(texts)
    reply = parse(text)._replace(asked=True)
    if debug:
        sys.stderr.write("bifterm: replies %r -> sixel=%s bg=%s cell=%s\n" % (texts, reply.sixel, reply.bg, reply.cell))
    return reply


def guess_dark(env=None):
    """Is the terminal dark, from COLORFGBG ("fg;bg", bg 0-6 and 8 are dark)?  None if it does not say."""
    env = os.environ if env is None else env
    v = env.get("COLORFGBG", "")
    if ";" not in v:
        return None
    try:
        bg = int(v.split(";")[-1])
    except ValueError:
        return None
    return bg in (0, 1, 2, 3, 4, 5, 6, 8)


if __name__ == "__main__":
    r = query(debug=True)
    print("terminal asked: %s\nsixel: %s\nbackground: %s\ncell: %s" % (r.asked, r.sixel, r.bg, r.cell))
