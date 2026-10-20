#!/usr/bin/env python3
"""bifdiag: what the tools say on standard error while they work: a spinning cursor, --debug and --profile.

    bifdiag.start("bifin", debug=a.debug, profile=a.profile)     once the input has been read
    with bifdiag.stage("classify"):                              a named step: timed, shown with --debug, in the profile
        ...
    bifdiag.progress("drawing frame", n, total)                  "bifout: drawing frame 3 of 20" on one line
    bifdiag.debug("chose", mode)                                 a line only with --debug
    with bifdiag.quiet():                                        the terminal is used for something else (a query, playback)
        ...
    bifdiag.stop()                                               before writing the result; prints the profile

The spinner is the one bidet3d had (|/-\\ and a backspace, on standard error, only if it is a terminal, from a quarter
of a second on, so a quick run shows nothing), turned by a thread, so it also turns inside one long numpy call.  In a
pipe (bifin | bifop | bifout) each tool starts it only after its input has arrived, so the tools take turns.
BIDET_NO_SPIN=1 turns it off.

--debug: every stage as it starts and ends, with its time, the versions of Python / numpy / Pillow, the tool's own
--verbose lines, and a traceback for an error.  --profile: when the tool ends, the time of every stage (as a tree,
repeated stages added up) and the functions that took longest (cProfile, cumulative time; only the main thread: the
3D renderer's worker threads are counted in their stage's wall time, not by function).  BIDET_PROFILE=FILE also saves
the cProfile statistics there (for pstats, snakeviz, ...).
"""
from __future__ import print_function

import atexit
import contextlib
import os
import sys
import threading
import time

SPINNER = "|/-\\"
SPIN_DELAY = 0.25                 # seconds before the spinner shows (a quick run shows nothing)
SPIN_STEP = 0.1                   # seconds a turn
TOP_FUNCTIONS = 25                # lines of the cProfile list


class _State(object):
    def __init__(self):
        self.prog = None              # who speaks ("bifin", "bidet", ...); None = not started
        self.debug = False
        self.profile = False
        self.t0 = time.time()
        self.stack = []               # the stages open now: [name, start]
        self.times = {}               # path (tuple of names) -> [count, seconds, first seen order]
        self.lock = threading.RLock()
        self.spin = None              # the spinner's thread
        self.stopping = None          # its stop event
        self.paused = 0
        self.shown = False            # a spinner character is on the screen (under the cursor)
        self.line_open = False        # a progress line without its newline
        self.profiler = None
        self.err = None               # where to write (standard error unless a test says otherwise)


_S = _State()
_S_atexit = []


def _err():
    return _S.err or sys.stderr


def _tty():
    try:
        return _err().isatty()
    except (AttributeError, ValueError):
        return False


def _write(text):
    try:
        e = _err()
        e.write(text)
        e.flush()
    except (IOError, ValueError):
        pass


def _clear_spinner():
    if _S.shown:
        _write(" \b")
        _S.shown = False


def _spin(stopping):
    if stopping.wait(SPIN_DELAY):
        return
    i = 0
    while not stopping.is_set():
        with _S.lock:
            if not _S.paused and not stopping.is_set():
                _write(SPINNER[i % len(SPINNER)] + "\b")
                _S.shown = True
                i += 1
        stopping.wait(SPIN_STEP)


def start(prog, debug=False, profile=False, spin=None, err=None):
    """Begin: `prog` names the tool in what it says.  spin: None = when standard error is a terminal."""
    stop(report=False)
    _S.__init__()
    _S.prog, _S.debug, _S.profile, _S.err = prog, bool(debug), bool(profile), err
    if spin is None:
        spin = _tty() and not os.environ.get("BIDET_NO_SPIN")
    if spin:
        if not _S_atexit:
            atexit.register(stop, False)                     # (Ctrl-C: the spinner's character is not left behind)
            _S_atexit.append(True)
        _S.stopping = threading.Event()
        _S.spin = threading.Thread(target=_spin, args=(_S.stopping,), name="bifdiag-spinner")
        _S.spin.daemon = True
        _S.spin.start()
    if _S.profile:
        import cProfile
        _S.profiler = cProfile.Profile()
        _S.profiler.enable()
    if _S.debug:
        say(versions())


def versions():
    """The versions that matter here, on one line."""
    parts = ["Python %s" % sys.version.split()[0], sys.platform]
    for name in ("numpy", "PIL"):
        try:
            mod = __import__(name)
            parts.append("%s %s" % ("Pillow" if name == "PIL" else name, getattr(mod, "__version__", "?")))
        except ImportError:
            parts.append("no %s" % name)
    return ", ".join(parts)


def active():
    return _S.prog is not None


def debugging():
    return _S.debug


def say(*words):
    """A line on standard error, `prog: ...`, that does not tangle with the spinner or a progress line."""
    text = " ".join(str(w) for w in words)
    with _S.lock:
        _clear_spinner()
        if _S.line_open:
            _write("\n")
            _S.line_open = False
        _write("%s: %s\n" % (_S.prog or os.path.basename(sys.argv[0] or "bidet"), text))


def debug(*words):
    """say(), only with --debug."""
    if _S.debug:
        say(*words)


def _elapsed():
    return time.time() - _S.t0


@contextlib.contextmanager
def stage(name):
    """A named step: timed for --profile, shown as it starts and ends with --debug.  Stages nest."""
    if not active():
        yield
        return
    depth = len(_S.stack)
    path = tuple(n for n, _ in _S.stack) + (name,)
    if _S.debug:
        say("%7.2fs %s> %s" % (_elapsed(), "  " * depth, name))
    t = time.time()
    _S.stack.append((name, t))
    try:
        yield
    finally:
        dt = time.time() - t
        if _S.stack and _S.stack[-1][0] == name:
            _S.stack.pop()
        rec = _S.times.setdefault(path, [0, 0.0, len(_S.times)])
        rec[0] += 1
        rec[1] += dt
        if _S.debug:
            say("%7.2fs %s< %s (%.3fs)" % (_elapsed(), "  " * depth, name, dt))


def progress(what, done, total):
    """`prog: what 3 of 20` on one line of standard error, rewritten in place (a terminal only), ended at the last one."""
    if not _tty():
        return
    with _S.lock:
        _clear_spinner()
        last = done >= total
        _write("\r%s: %s %d of %d%s" % (_S.prog or "bidet", what, done, total, "\n" if last else ""))
        _S.line_open = not last


@contextlib.contextmanager
def quiet():
    """No spinner meanwhile: the terminal is being asked something, or an animation is playing on it."""
    with _S.lock:
        _S.paused += 1
        _clear_spinner()
        if _S.line_open:
            _write("\n")
            _S.line_open = False
    try:
        yield
    finally:
        with _S.lock:
            _S.paused -= 1


def stop(report=True):
    """The end: the spinner goes, and with --profile the report is printed."""
    if _S.spin is not None:
        _S.stopping.set()
        _S.spin.join(1.0)
        _S.spin = None
    with _S.lock:
        _clear_spinner()
        if _S.line_open:
            _write("\n")
            _S.line_open = False
    if _S.profiler is not None:
        _S.profiler.disable()
        if report and _S.prog:
            _write(profile_report())
            path = os.environ.get("BIDET_PROFILE")
            if path:
                try:
                    _S.profiler.dump_stats(path)
                    say("profile statistics saved in", path)
                except (IOError, OSError) as e:
                    say("could not save the profile in %s: %s" % (path, e))
        _S.profiler = None
    if report and _S.debug and _S.prog:
        say("%.2fs in all" % _elapsed())
    _S.prog = None


def profile_report():
    """The text --profile prints: the stages, then the slowest functions."""
    lines = ["", "%s: profile, %.3f s in all" % (_S.prog, _elapsed()), "", "  seconds  count  stage"]
    for path, (count, secs, _) in sorted(_S.times.items(), key=lambda kv: _order(kv[0])):
        lines.append("  %7.3f  %5d  %s%s" % (secs, count, "  " * (len(path) - 1), path[-1]))
    if not _S.times:
        lines.append("  (no stages)")
    if _S.profiler is not None:
        import io
        import pstats
        buf = io.StringIO()
        st = pstats.Stats(_S.profiler, stream=buf)
        st.strip_dirs().sort_stats("cumulative").print_stats(TOP_FUNCTIONS)
        body = buf.getvalue()
        start_at = body.find("   ncalls")
        lines += ["", "  the %d functions with the most cumulative time (main thread only):" % TOP_FUNCTIONS, ""]
        lines += ["  " + l for l in (body[start_at:] if start_at >= 0 else body).rstrip().splitlines()]
    return "\n".join(lines) + "\n\n"


def _order(path):
    """Stages in the order they first began, children under their parent."""
    return tuple(_S.times[path[:i + 1]][2] if path[:i + 1] in _S.times else 0 for i in range(len(path)))


def fail(prog, e, debug=False):
    """The way a tool dies of an error `e`: the message, and with --debug (or debug) the traceback before it."""
    if _S.debug or debug:
        import traceback
        with _S.lock:
            _clear_spinner()
            traceback.print_exc(file=_err())
    stop(report=True)
    sys.exit("%s: %s" % (prog, e))


def add_arguments(ap):
    """The --debug and --profile flags, the same in every tool."""
    ap.add_argument("--debug", action="store_true", help="show every stage as it starts and ends, with its time, the "
                    "versions in use and the --verbose lines; a traceback for an error")
    ap.add_argument("--profile", "--profiling", dest="profile", action="store_true",
                    help="when done, print the time of every stage and the functions that took longest (cProfile) on "
                         "standard error; BIDET_PROFILE=FILE also saves the statistics")
