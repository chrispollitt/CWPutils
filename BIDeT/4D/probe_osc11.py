#!/usr/bin/env python3
"""probe_osc11: does the terminal answer OSC 10 / OSC 11 (colour queries) on THIS path to it?

    python probe_osc11.py [--timeout S] [--label TEXT] [--raw]

Run it in every terminal / shell / ssh combination you care about and compare.  It sends OSC 10 ? (foreground) and
OSC 11 ? (background), then DA1 (CSI c), and waits the whole timeout for both colour replies.  It does not stop at
DA1: ConPTY answers DA1 itself, instantly, while an OSC query has to go to the terminal and back, so DA1 arriving
first proves nothing.  It reports what came back, in what order and how fast, and a verdict:

    ANSWERED   the colour reply came back                     exit 0
    DROPPED    DA1 came back but no OSC reply (the terminal ignores the query, or something on the way ate it)  exit 1
    SILENT     nothing came back at all (no reply path, or everything was eaten)                                   exit 1
    NO TTY     there is no terminal to ask                    exit 2

Talks to the controlling terminal (/dev/tty on POSIX: Linux, WSL, macOS, Cygwin, MSYS, mintty; CONIN$ / CONOUT$ with
native Windows Python), so it works with stdin / stdout redirected.  Python 3.7+, standard library only.
"""
from __future__ import print_function

import argparse
import os
import platform
import re
import sys
import time

QUERIES = (
    ("fg", "OSC 10 (foreground)", "\x1b]10;?\x1b\\", re.compile(r"\x1b\]10;([^\x07\x1b]*)(?:\x07|\x1b\\)")),
    ("bg", "OSC 11 (background)", "\x1b]11;?\x1b\\", re.compile(r"\x1b\]11;([^\x07\x1b]*)(?:\x07|\x1b\\)")),
    ("da1", "DA1 (device attributes)", "\x1b[c", re.compile(r"\x1b\[\?([0-9;]*)c")),
)
GRACE = 0.3                                                                   # seconds to wait for DA1 after both colours
_RGB = re.compile(r"rgba?:([0-9a-fA-F]+)/([0-9a-fA-F]+)/([0-9a-fA-F]+)")


def parse_rgb(body):
    """(r, g, b) 0..255 from 'rgb:RRRR/GGGG/BBBB' (any digits per channel), or None."""
    m = _RGB.match(body)
    if not m:
        return None
    return tuple(int(round(int(g, 16) / float(16 ** len(g) - 1) * 255)) for g in m.groups())


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

        self.Record = Record
        k.ReadConsoleInputW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Record), wintypes.DWORD,
                                        ctypes.POINTER(wintypes.DWORD)]
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
    """Send the queries and collect replies until both colour replies are in or `timeout` passes.
    Returns (text, seen) with seen[key] = (seconds after sending, the reply body) for each reply that arrived."""
    tty.write("".join(q[2] for q in QUERIES))
    t0 = time.time()
    text, seen, both = "", {}, None
    while time.time() - t0 < timeout:
        wait = t0 + timeout - time.time()
        if both is not None:
            wait = min(wait, both + GRACE - time.time())          # the colour replies are in: DA1 may be a moment behind
            if wait <= 0:
                break
        chunk = tty.read(wait)
        if not chunk:
            continue
        text += chunk
        for key, _, _, pat in QUERIES:
            m = pat.search(text)
            if m and key not in seen:
                seen[key] = (time.time() - t0, m.group(1))
        if both is None and "fg" in seen and "bg" in seen:
            both = time.time()
        if both is not None and "da1" in seen:
            break
    return text, seen


def environment():
    keys = ("TERM", "TERM_PROGRAM", "WT_SESSION", "MSYSTEM", "WEZTERM_EXECUTABLE", "SSH_CONNECTION", "SSH_TTY")
    return ", ".join("%s=%s" % (k, os.environ[k]) for k in keys if os.environ.get(k)) or "(no terminal variables set)"


def verdict(seen, text):
    """-> (name, exit code)"""
    if "bg" in seen:
        return "ANSWERED", 0
    return ("DROPPED", 1) if "da1" in seen or text else ("SILENT", 1)


def report(label, seen, text, timeout, raw=False):
    out = ["probe_osc11%s" % (" [%s]" % label if label else ""),
           "  python:  %s %s, %s, os.name=%s" % (platform.python_implementation(), platform.python_version(),
                                                 platform.platform(), os.name),
           "  env:     %s" % environment()]
    order = sorted(seen.items(), key=lambda kv: kv[1][0])
    for key, name, _, _ in QUERIES:
        if key in seen:
            dt, body = seen[key]
            extra = ""
            if key in ("fg", "bg"):
                rgb = parse_rgb(body)
                extra = "  = rgb%s" % (rgb,) if rgb else "  (unparsed)"
            out.append("  %-24s answered after %5.0f ms: %r%s" % (name, dt * 1000, body, extra))
        else:
            waited = GRACE if "fg" in seen and "bg" in seen else timeout
            out.append("  %-24s no reply in %.1f s" % (name, waited))
    if len(order) > 1:
        out.append("  reply order: " + " -> ".join(k for k, _ in order))
    if raw:
        out.append("  raw bytes: %r" % text)
    name, code = verdict(seen, text)
    why = {"ANSWERED": "the colour query round-trips on this path.",
           "DROPPED": "something answered (DA1 or other bytes) but not the OSC colour query: the terminal ignores it, "
                      "or an intermediary (ConPTY, ssh, a multiplexer) ate it.",
           "SILENT": "no reply of any kind: the reply path may be dead, or every query was eaten."}[name]
    out.append("  VERDICT: %s - %s" % (name, why))
    return "\n".join(out), code


def main(argv=None):
    ap = argparse.ArgumentParser(description="Does this terminal answer OSC 10/11 colour queries on this path?")
    ap.add_argument("--timeout", type=float, default=2.0, help="seconds to wait for the replies (default 2.0)")
    ap.add_argument("--label", default="", help="a name for this run, to tell the outputs apart")
    ap.add_argument("--raw", action="store_true", help="also show every byte that came back")
    args = ap.parse_args(argv)
    tty = open_tty()
    if tty is None:
        print("probe_osc11: NO TTY - there is no terminal to ask (is this a pipe, cron, or a Windows Python run "
              "from a pty such as mintty? run it from a Cygwin/MSYS Python there instead)", file=sys.stderr)
        return 2
    try:
        text, seen = probe(tty, args.timeout)
    finally:
        tty.close()
    msg, code = report(args.label, seen, text, args.timeout, args.raw)
    print(msg)
    return code


if __name__ == "__main__":
    sys.exit(main())
