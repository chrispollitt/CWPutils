#!/usr/bin/env python3
"""probe_osc11: what survives the trip between a program and its terminal on THIS path?

    python probe_osc11.py [--timeout S] [--label TEXT] [--raw] [--input]

Run it in every terminal / shell / ssh combination you care about and compare.  It asks the terminal, in one burst,
the questions a capability-negotiating TUI (tvision, notcurses, vim, ...) asks:

    OSC 10 / 11        foreground / background colour
    DA1, DA2, XTVERSION    who are you
    CSI 18t / 14t / 16t    size in characters / in pixels / of one cell
    CSI 6n             cursor position
    kitty keyboard, modifyOtherKeys    which key encodings
    DECRQM 1000 1006 2004 2026 9001    mouse, SGR mouse, bracketed paste, synchronized output, win32-input-mode

and then checks what came back, not just whether something did.  Two verdicts:

  OSC 11    ANSWERED   the colour reply came back                                            exit 0
            DROPPED    something answered but not the colour query (ignored, or eaten on the way)
            SILENT     nothing came back at all
  NEGOTIATION   CLEAN  every reply that came is whole, single and consistent
                MANGLED  replies doubled (two layers both answered), bytes that are no known reply (garbage that would
                         land on a TUI's screen), a size that disagrees with the real window, a DA1 that is conhost's
                         canned "1;0", or win32-input-mode switched on (keys then arrive as CSI ... _ sequences)

A terminal that does not know a query stays quiet; that is listed as "no reply", not as a fault.  It waits the whole
timeout unless every query has been answered: ConPTY answers DA1 itself, at once, while the other queries have to go
to the terminal and back, so DA1 arriving first proves nothing.

--input adds a keyboard and mouse fidelity test: it turns on SGR mouse reporting, asks you to type, click and press
the arrow keys, and reports what arrived (dropped keystrokes, missing clicks, win32-input-mode sequences).
--tvision does the same after setting the terminal up exactly as tvision does at startup (win32-input-mode 9001,
kitty keys, modifyOtherKeys, mouse), decodes the win32-input-mode records, and counts records that were cut in two
across reads (a lone ESC then reads as the Escape key, and the rest shows on screen as "[68;32;100;1;0;1_").
Note that a program can turn 9001 on itself: a plain printf of ESC [ ? 9001 l beforehand changes nothing for tvision.

Talks to the controlling terminal (/dev/tty on POSIX: Linux, WSL, macOS, Cygwin, MSYS, mintty; CONIN$ / CONOUT$ with
native Windows Python), so it works with stdin / stdout redirected.  Python 3.7+, standard library only.
Exit codes: 0 all clean, 1 a problem found, 2 no terminal.
"""
from __future__ import print_function

import argparse
import os
import platform
import re
import sys
import time

GRACE = 0.3                                              # seconds to go on listening once every query is answered
ESC = "\x1b"
ST = r"(?:\x07|\x1b\\)"                                  # string terminator: BEL or ESC \
_RGB = re.compile(r"rgba?:([0-9a-fA-F]+)/([0-9a-fA-F]+)/([0-9a-fA-F]+)")
DECRQM_STATE = {0: "not recognised", 1: "set (on)", 2: "reset (off)", 3: "permanently on", 4: "permanently off"}


class Query(object):
    def __init__(self, key, name, seq, pattern, show=None):
        self.key, self.name, self.seq = key, name, seq
        self.pat = re.compile(pattern, re.S)
        self.show = show or (lambda m, ctx: m.group(1))


def parse_rgb(body):
    """(r, g, b) 0..255 from 'rgb:RRRR/GGGG/BBBB' (any digits per channel), or None."""
    m = _RGB.match(body)
    if not m:
        return None
    return tuple(int(round(int(g, 16) / float(16 ** len(g) - 1) * 255)) for g in m.groups())


def _colour(m, ctx):
    rgb = parse_rgb(m.group(1))
    return "%r  = rgb%s" % (m.group(1), rgb) if rgb else "%r  (unparsed)" % m.group(1)


def _da1(m, ctx):
    return "%r%s" % (m.group(1), "   <- conhost's canned reply, not the terminal's" if m.group(1) == "1;0" else "")


def _size(m, ctx):
    rows, cols = int(m.group(1)), int(m.group(2))
    real = ctx.get("size")
    note = ""
    if real and (rows, cols) != real[:2]:
        note = "   <- the window is %dx%d" % (real[1], real[0])
    return "%d rows x %d cols%s" % (rows, cols, note)


def _px(m, ctx):
    return "%s x %s px (h x w)" % (m.group(1), m.group(2))


def _decrqm(mode, label):
    return Query("mode%d" % mode, "DECRQM %d (%s)" % (mode, label), "\x1b[?%d$p" % mode,
                 r"\x1b\[\?%d;(\d)\$y" % mode, lambda m, ctx: DECRQM_STATE.get(int(m.group(1)), m.group(1)))


QUERIES = (
    Query("fg", "OSC 10 (foreground)", "\x1b]10;?\x1b\\", r"\x1b\]10;([^\x07\x1b]*)" + ST, _colour),
    Query("bg", "OSC 11 (background)", "\x1b]11;?\x1b\\", r"\x1b\]11;([^\x07\x1b]*)" + ST, _colour),
    Query("xtver", "XTVERSION", "\x1b[>0q", r"\x1bP>\|(.*?)\x1b\\", lambda m, ctx: repr(m.group(1))),
    Query("da2", "DA2 (secondary attrs)", "\x1b[>c", r"\x1b\[>([0-9;]*)c", lambda m, ctx: repr(m.group(1))),
    Query("size18", "CSI 18t (size, chars)", "\x1b[18t", r"\x1b\[8;(\d+);(\d+)t", _size),
    Query("pix14", "CSI 14t (size, pixels)", "\x1b[14t", r"\x1b\[4;(\d+);(\d+)t", _px),
    Query("cell16", "CSI 16t (cell, pixels)", "\x1b[16t", r"\x1b\[6;(\d+);(\d+)t", _px),
    Query("cpr", "CSI 6n (cursor pos)", "\x1b[6n", r"\x1b\[(\d+);(\d+)R", lambda m, ctx: "row %s, col %s" % m.groups()),
    Query("kitty", "kitty keyboard flags", "\x1b[?u", r"\x1b\[\?(\d+)u", lambda m, ctx: "flags %s" % m.group(1)),
    Query("modkeys", "modifyOtherKeys", "\x1b[?4m", r"\x1b\[>4;(\d+)m", lambda m, ctx: "level %s" % m.group(1)),
    _decrqm(1000, "mouse"), _decrqm(1006, "SGR mouse"), _decrqm(2004, "bracketed paste"),
    _decrqm(2026, "synchronized output"), _decrqm(9001, "win32-input-mode"),
    Query("da1", "DA1 (device attributes)", "\x1b[c", r"\x1b\[\?([0-9;]*)c", _da1),      # last: the others are the point
)
BY_KEY = dict((q.key, q) for q in QUERIES)


class PosixTty(object):
    def __init__(self):
        import termios
        import tty
        self._termios = termios
        self.fd = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY)
        self._old = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd, termios.TCSANOW)

    def write(self, text):
        os.write(self.fd, text.encode("latin1"))

    def read(self, timeout):
        import select
        if not select.select([self.fd], [], [], max(timeout, 0))[0]:
            return ""
        return os.read(self.fd, 256).decode("latin1")

    def size(self):
        """(rows, cols, xpixel, ypixel) of the window, or None."""
        try:
            import fcntl
            import struct
            return struct.unpack("HHHH", fcntl.ioctl(self.fd, self._termios.TIOCGWINSZ, b"\0" * 8))
        except Exception:
            return None

    def close(self):
        try:
            self._termios.tcflush(self.fd, self._termios.TCIFLUSH)
            self._termios.tcsetattr(self.fd, self._termios.TCSADRAIN, self._old)
        finally:
            os.close(self.fd)


class WindowsConsole(object):
    """CONIN$ / CONOUT$ with VT input and output on: the query goes out as text, the reply comes back as key events."""
    ENABLE_PROCESSED_OUTPUT, ENABLE_VT_PROCESSING = 0x1, 0x4
    ENABLE_VT_INPUT = 0x200
    KEY_EVENT = 0x1

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.c = ctypes
        self.w = wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        self.k = k
        k.CreateFileW.restype = wintypes.HANDLE
        k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                  wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        k.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        k.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k.WriteConsoleW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD,
                                    ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        k.FlushConsoleInputBuffer.argtypes = [wintypes.HANDLE]
        k.CloseHandle.argtypes = [wintypes.HANDLE]

        class KeyEvent(ctypes.Structure):
            _fields_ = [("down", wintypes.BOOL), ("repeat", wintypes.WORD), ("vk", wintypes.WORD),
                        ("scan", wintypes.WORD), ("char", wintypes.WCHAR), ("state", wintypes.DWORD)]

        class Record(ctypes.Structure):
            class U(ctypes.Union):
                _fields_ = [("key", KeyEvent), ("pad", ctypes.c_byte * 16)]
            _anonymous_ = ("u",)
            _fields_ = [("type", wintypes.WORD), ("u", U)]

        class Info(ctypes.Structure):
            _fields_ = [("sx", wintypes.SHORT), ("sy", wintypes.SHORT), ("cx", wintypes.SHORT), ("cy", wintypes.SHORT),
                        ("attr", wintypes.WORD), ("left", wintypes.SHORT), ("top", wintypes.SHORT),
                        ("right", wintypes.SHORT), ("bottom", wintypes.SHORT), ("mx", wintypes.SHORT),
                        ("my", wintypes.SHORT)]

        self.Record, self.Info = Record, Info
        k.ReadConsoleInputW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Record), wintypes.DWORD,
                                        ctypes.POINTER(wintypes.DWORD)]
        k.GetConsoleScreenBufferInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Info)]
        bad = wintypes.HANDLE(-1).value
        share, openex = 3, 3
        self.hin = k.CreateFileW("CONIN$", 0xC0000000, share, None, openex, 0, None)
        self.hout = k.CreateFileW("CONOUT$", 0xC0000000, share, None, openex, 0, None)
        if self.hin in (None, bad) or self.hout in (None, bad):
            raise OSError("no console")
        self._old_in, self._old_out = wintypes.DWORD(), wintypes.DWORD()
        if not (k.GetConsoleMode(self.hin, ctypes.byref(self._old_in))
                and k.GetConsoleMode(self.hout, ctypes.byref(self._old_out))):
            raise OSError("not a console")
        k.SetConsoleMode(self.hin, self.ENABLE_VT_INPUT)                       # no line input, no echo, no processing
        k.SetConsoleMode(self.hout, self._old_out.value | self.ENABLE_PROCESSED_OUTPUT | self.ENABLE_VT_PROCESSING)
        k.FlushConsoleInputBuffer(self.hin)

    def write(self, text):
        n = self.w.DWORD()
        self.k.WriteConsoleW(self.hout, text, len(text), self.c.byref(n), None)

    def read(self, timeout):
        if self.k.WaitForSingleObject(self.hin, int(max(timeout, 0) * 1000)) != 0:
            return ""
        rec, n = self.Record(), self.w.DWORD()
        if not self.k.ReadConsoleInputW(self.hin, self.c.byref(rec), 1, self.c.byref(n)) or not n.value:
            return ""
        if rec.type == self.KEY_EVENT and rec.key.down and rec.key.char != "\0":
            return rec.key.char
        return ""                                                              # focus / mouse / resize: not a reply

    def size(self):
        info = self.Info()
        if not self.k.GetConsoleScreenBufferInfo(self.hout, self.c.byref(info)):
            return None
        return (info.bottom - info.top + 1, info.right - info.left + 1, 0, 0)

    def close(self):
        try:
            self.k.FlushConsoleInputBuffer(self.hin)
            self.k.SetConsoleMode(self.hin, self._old_in.value)
            self.k.SetConsoleMode(self.hout, self._old_out.value)
        finally:
            self.k.CloseHandle(self.hin)
            self.k.CloseHandle(self.hout)


def open_tty():
    """The controlling terminal, or None."""
    try:
        return PosixTty() if os.name == "posix" else WindowsConsole()
    except Exception:
        return None


def probe(tty, timeout):
    """Send every query in one burst and collect replies until all are in (plus GRACE, for a straggler or a second
    answer) or `timeout` passes.  Returns (text, seen) with seen[key] = seconds after sending of the first reply."""
    tty.write("".join(q.seq for q in QUERIES))
    t0 = time.time()
    text, seen, full = "", {}, None
    while time.time() - t0 < timeout:
        wait = t0 + timeout - time.time()
        if full is not None:
            wait = min(wait, full + GRACE - time.time())
            if wait <= 0:
                break
        chunk = tty.read(wait)
        if not chunk:
            continue
        text += chunk
        for q in QUERIES:
            if q.key not in seen and q.pat.search(text):
                seen[q.key] = time.time() - t0
        if full is None and len(seen) == len(QUERIES):
            full = time.time()
    return text, seen


def analyse(text, seen, size):
    """-> (rows, issues): rows = [(query, dt or None, shown text, count)], issues = [str] for the negotiation verdict."""
    ctx = {"size": size}
    rows, issues, rest = [], [], text
    for q in QUERIES:
        found = list(q.pat.finditer(text))
        rest = q.pat.sub("", rest)
        rows.append((q, seen.get(q.key), q.show(found[0], ctx) if found else None, len(found)))
        if len(found) > 1:
            issues.append("%s answered %d times: two layers both replied (the second lands on the TUI's screen)"
                          % (q.name, len(found)))
    rest = rest.strip()
    if rest:
        issues.append("%d byte(s) came back that are no known reply: %r - garbage that would land on a TUI's screen"
                      % (len(rest), rest))
    got = dict((q.key, m) for q, m in ((q, q.pat.search(text)) for q in QUERIES) if m)
    if "size18" in got and size and (int(got["size18"].group(1)), int(got["size18"].group(2))) != tuple(size[:2]):
        issues.append("CSI 18t says %sx%s but the window is %dx%d (stale or rewritten by an intermediary)"
                      % (got["size18"].group(2), got["size18"].group(1), size[1], size[0]))
    if "da1" not in got:
        issues.append("DA1 got no reply: a TUI that waits for it will stall")
    elif got["da1"].group(1) == "1;0":
        issues.append("DA1 is conhost's canned '1;0': the real terminal's capabilities are hidden from the program")
    if "mode9001" in got and got["mode9001"].group(1) in ("1", "3"):
        issues.append("win32-input-mode (9001) is ON: keys and mouse arrive as CSI ... _ records, a plain TUI "
                      "will see garbage or drop input")
    return rows, issues


def environment():
    keys = ("TERM", "TERM_PROGRAM", "WT_SESSION", "MSYSTEM", "CYGWIN", "SSH_TERM_CONHOST_PARSER", "WSL_DISTRO_NAME",
            "SSH_CONNECTION", "SSH_TTY")
    return ", ".join("%s=%s" % (k, os.environ[k]) for k in keys if os.environ.get(k)) or "(no terminal variables set)"


def osc_verdict(seen, text):
    """-> (name, exit code)"""
    if "bg" in seen:
        return "ANSWERED", 0
    return ("DROPPED", 1) if seen or text else ("SILENT", 1)


def report(label, rows, issues, seen, text, timeout, raw=False, size=None):
    out = ["probe_osc11%s" % (" [%s]" % label if label else ""),
           "  python:  %s %s, %s, os.name=%s" % (platform.python_implementation(), platform.python_version(),
                                                 platform.platform(), os.name),
           "  env:     %s" % environment()]
    if size:
        out.append("  window:  %d rows x %d cols%s" % (size[0], size[1], ", %dx%d px" % (size[2], size[3])
                                                       if size[2] and size[3] else ""))
    for q, dt, shown, count in rows:
        if shown is None:
            out.append("  %-34s no reply" % q.name)
        else:
            out.append("  %-34s %5.0f ms  %s%s" % (q.name, dt * 1000, shown, "   (x%d)" % count if count > 1 else ""))
    placed = sorted((q.pat.search(text).start(), q.key) for q in QUERIES if q.key in seen)
    asked = [q.key for q in QUERIES if q.key in seen]
    if [k for _, k in placed] != asked:
        out.append("  note: replies came back in a different order than asked: " + " -> ".join(k for _, k in placed))
    if raw:
        out.append("  raw bytes: %r" % text)
    name, code = osc_verdict(seen, text)
    why = {"ANSWERED": "the colour query round-trips on this path.",
           "DROPPED": "something answered but not the OSC colour query: the terminal ignores it, or an intermediary "
                      "(ConPTY, ssh, Cygwin's console layer, a multiplexer) ate it.",
           "SILENT": "no reply of any kind: the reply path may be dead, or every query was eaten."}[name]
    out.append("  OSC 11:      %s - %s" % (name, why))
    if issues:
        out.append("  NEGOTIATION: MANGLED")
        out.extend("    - " + i for i in issues)
    else:
        out.append("  NEGOTIATION: CLEAN - every reply that came is whole, single and consistent.")
    return "\n".join(out), (code or (1 if issues else 0))


TV_ON = ("\x1b[?1000h\x1b[?1002h\x1b[?1006h"                        # what tvision turns on (mouse; keys: below)
         "\x1b[?1036s\x1b[?1036h\x1b[?2004s\x1b[?2004h\x1b[>4;1m\x1b[>5u\x1b[?9001h")
TV_OFF = ("\x1b[?9001l\x1b[<u\x1b[>4m\x1b[?2004l\x1b[?2004r\x1b[?1036r"
          "\x1b[?1006l\x1b[?1002l\x1b[?1000l")
REC = re.compile(r"\x1b\[(\d+);(\d+);(\d+);([01]);(\d+);(\d+)_")           # win32-input-mode: Vk;Sc;Uc;Kd;Cs;Rc _
LEAK = re.compile(r"\[?\d+;\d+;\d+;[01];\d+;\d+_")                             # the same with its ESC eaten: shows on screen
VKEYS = {38: "\x1b[A", 40: "\x1b[B", 39: "\x1b[C", 37: "\x1b[D"}              # Up Down Right Left


def unwrap(text):
    """Decode win32-input-mode records the way tvision does: a key-down with a character is that character (this
    also unwraps the ESC [ < ... M of a mouse report that ConPTY wraps one record per byte), an arrow key is its CSI."""
    def one(m):
        vk, _, uc, down, _, rep = [int(g) for g in m.groups()]
        if not down:
            return ""
        return chr(uc) * max(rep, 1) if uc else VKEYS.get(vk, "")
    return REC.sub(one, text)


def input_test(tty, seconds=20.0, idle=4.0, tvision=False):
    """Ask for 10 letters, 3 clicks and the 4 arrow keys; -> (lines, ok).  With `tvision` the terminal is set up as
    tvision sets it up (win32-input-mode, kitty keys, modifyOtherKeys, mouse) and the records are decoded."""
    print("\nINPUT TEST%s: within %d s type  abcdefghij , click anywhere in this window 3 times, then press"
          "\n            Up Down Left Right  (in that order).  It ends %d s after you stop."
          % (" (tvision's setup)" if tvision else "", seconds, idle))
    sys.stdout.flush()
    tty.write(TV_ON if tvision else "\x1b[?1000h\x1b[?1006h")
    text, chunks, t0, last = "", [], time.time(), None
    try:
        while time.time() - t0 < seconds:
            wait = min(0.2, t0 + seconds - time.time())
            chunk = tty.read(wait)
            if chunk:
                text += chunk
                chunks.append((time.time(), chunk))
                last = time.time()
            elif last is not None and time.time() - last > idle:
                break
    finally:
        tty.write(TV_OFF if tvision else "\x1b[?1006l\x1b[?1000l")
    split = []                                                  # (tail, ms until the rest came): cut off at a read's end
    for i, (t, c) in enumerate(chunks):
        if re.search(r"\x1b(?:\[[0-9;<?>]*)?$", c):
            split.append((c[-12:], (chunks[i + 1][0] - t) * 1000 if i + 1 < len(chunks) else None))
    nrec, leaked = len(REC.findall(text)), len(LEAK.findall(REC.sub("", text)))
    if tvision:
        text = unwrap(text)
    mouse = re.compile(r"\x1b\[<(\d+);(\d+);(\d+)([Mm])")
    arrows = re.compile(r"\x1b[\[O]([ABCD])")
    w32 = re.compile(r"\x1b\[\d+;\d+;\d+;\d+;\d+;\d+_")
    clicks = [m for m in mouse.finditer(text) if int(m.group(1)) < 32]            # buttons, not motion or wheel
    press, release = [m for m in clicks if m.group(4) == "M"], [m for m in clicks if m.group(4) == "m"]
    ar = "".join(m.group(1) for m in arrows.finditer(text))
    rest = w32.sub("", arrows.sub("", mouse.sub("", text)))
    letters = "".join(c for c in rest if c.isalpha())
    junk = "".join(c for c in rest if not c.isalpha() and c not in "\r\n")
    lines, ok = [], True
    for what, got, want in (("letters", letters, "abcdefghij"), ("arrow keys", ar, "ABDC")):
        good = got == want
        ok = ok and good
        lines.append("  %-11s %s  (got %r, wanted %r%s)" % (what, "ok     " if good else "PROBLEM", got, want,
                                                             "; A=Up B=Down C=Right D=Left" if what == "arrow keys" else ""))
    good = len(press) >= 3 and len(release) >= 3
    ok = ok and good
    lines.append("  %-11s %s  (%d presses, %d releases, wanted 3 and 3)" % ("mouse", "ok     " if good else "PROBLEM",
                                                                           len(press), len(release)))
    if tvision:
        gaps = [g for _, g in split if g is not None]
        lines.append("  win32 records: %d whole, %d split across reads, %d leaked as text%s"
                     % (nrec, len(split), leaked, "" if not leaked else "  <- this is the garbage on a TUI's screen"))
        if split:
            lines.append("  split: the rest came after %s ms (e.g. %s); ncurses (tvision) waits only ESCDELAY, "
                         "default 10 ms, before it calls a lone ESC the Escape key"
                         % ("/".join("%.0f" % g for g in gaps[:8]) or "?", repr(split[0][0])))
        if split or leaked:
            ok = False
    elif w32.search(text):
        ok = False
        lines.append("  win32-input-mode records arrived (%d): the terminal is in win32-input-mode and the program "
                     "is not decoding it" % len(w32.findall(text)))
    if junk:
        ok = False
        lines.append("  stray bytes arrived: %r" % junk)
    if not text:
        lines.append("  (nothing was typed or clicked)")
        ok = False
    return lines, ok


def main(argv=None):
    ap = argparse.ArgumentParser(description="What survives the trip between a program and its terminal?")
    ap.add_argument("--timeout", type=float, default=2.0, help="seconds to wait for the replies (default 2.0)")
    ap.add_argument("--label", default="", help="a name for this run, to tell the outputs apart")
    ap.add_argument("--raw", action="store_true", help="also show every byte that came back")
    ap.add_argument("--input", action="store_true", help="also test keyboard and mouse fidelity (interactive)")
    ap.add_argument("--tvision", action="store_true",
                    help="like --input, but first set the terminal up as tvision does (win32-input-mode, kitty keys, "
                         "modifyOtherKeys) and decode the key records: reproduces tvmail's input problems")
    args = ap.parse_args(argv)
    tty = open_tty()
    if tty is None:
        print("probe_osc11: NO TTY - there is no terminal to ask (is this a pipe, cron, or a Windows Python run "
              "from a pty such as mintty? run it from a Cygwin/MSYS Python there instead)", file=sys.stderr)
        return 2
    try:
        size = tty.size()
        text, seen = probe(tty, args.timeout)
        rows, issues = analyse(text, seen, size)
        msg, code = report(args.label, rows, issues, seen, text, args.timeout, args.raw, size)
        print(msg)
        if args.input or args.tvision:
            lines, ok = input_test(tty, tvision=args.tvision)
            print("\n".join(lines))
            print("  INPUT:       %s" % ("CLEAN" if ok else "PROBLEM"))
            code = code or (0 if ok else 1)
    finally:
        tty.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
