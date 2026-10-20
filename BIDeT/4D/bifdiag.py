#!/usr/bin/env python3
"""bifdiag: what the tools say on standard error while they work: a status line with a spinning cursor, --debug and
--profile.

    bifdiag.start("bifin", debug=a.debug, profile=a.profile)     once the input has been read
    bifdiag.plan(["bifin", "bifop spin", "bifout"])              the steps of a pipeline (bidet, bifop): "[2/3]"
    bifdiag.step("bifop spin")                                   that step begins (no-op without a plan)
    with bifdiag.stage("classify"):                              a named stage: timed, shown with --debug, in the profile
        ...
    bifdiag.progress("drawing frame", n, total)                  a counted loop: "drawing frame 3 of 20, 15%, 9 s left"
    bifdiag.debug("chose", mode)                                 a line only with --debug
    with bifdiag.quiet():                                        the terminal is used for something else (a query, playback)
        ...
    bifdiag.stop()                                               before writing the result; prints the profile

The status line is one line of standard error, only if it is a terminal, from a quarter of a second on (a quick run
shows nothing), redrawn in place by a thread ten times a second, so it also moves inside one long numpy call:

    bidet: [3/4] bifout gif animation: draw and write frames: drawing frame 12 of 40, 30%, 8 s left |

the step of the pipeline (if there is a plan), the stages open now, the counted loop, and bidet3d's spinning cursor
(|/-\\).  A percent and the time left are given only for a counted loop (frames, screens), from its own pace so far:
how long the other stages take depends too much on the input for an honest figure for the whole run, so the whole run
is "step k of N".  The line is rubbed out at the end and while the terminal is asked something or an animation plays.
In a pipe (bifin | bifop | bifout) each tool starts only after its input has arrived, so the tools take turns.
BIDET_NO_SPIN=1: no status line at all; nor with --profile.

--debug: every stage as it starts and ends, with its time, the versions of Python / numpy / Pillow, the tool's own
--verbose lines, how long each counted loop took, and a traceback for an error.  --profile: when the tool ends, the
time of every stage (as a tree, repeated stages added up) and the functions that took longest (cProfile, cumulative
time; see THREADS for the 3D renderer's worker threads, and BIDET_THREADS=1 to draw on one).  BIDET_PROFILE=FILE also
saves the cProfile statistics there (for pstats, snakeviz, ...).
"""
from __future__ import print_function

import atexit
import contextlib
import os
import shutil
import sys
import threading
import time

SPINNER = "|/-\\"
SPIN_DELAY = 0.25                 # seconds before the status line shows (a quick run shows nothing)
SPIN_STEP = 0.1                   # seconds between redraws
ETA_AFTER = 0.5                   # seconds into a counted loop before the time left is guessed
TOP_FUNCTIONS = 25                # lines of the cProfile list
CLEAR = "\r\x1b[K"


class _State(object):
    def __init__(self):
        self.prog = None              # who speaks ("bifin", "bidet", ...); None = not started
        self.debug = False
        self.profile = False
        self.t0 = time.time()
        self.stack = []               # the stages open now: [name, start]
        self.times = {}               # path (tuple of names) -> [count, seconds, first seen order]
        self.steps = []               # the plan: names of the steps of the pipeline
        self.at = -1                  # the step under way (index into steps)
        self.loop = None              # the counted loop: [what, done, total, depth, first time, first done, last time]
        self.lock = threading.RLock()
        self.spin = None              # the status line's thread
        self.stopping = None          # its stop event
        self.turn = 0
        self.paused = 0
        self.shown = False            # a status line is on the screen
        self.profiler = None
        self.err = None               # where to write (standard error unless a test says otherwise)
        self.width = None             # columns of the terminal (tests set it)


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


def _clear_line():
    if _S.shown:
        _write(CLEAR)
        _S.shown = False


def _columns():
    if _S.width:
        return _S.width
    try:
        cols = shutil.get_terminal_size((80, 24)).columns
    except (OSError, ValueError):
        cols = 0
    return cols if cols >= 20 else 80                      # (a pty may say 0 x 0)


def _seconds(s):
    s = int(round(s))
    if s < 60:
        return "%d s" % s
    if s < 3600:
        return "%d min %02d s" % (s // 60, s % 60)
    return "%d h %02d min" % (s // 3600, s % 3600 // 60)


def loop_text(now=None):
    """The counted loop as the status line says it: 'drawing frame 12 of 40, 30%, 8 s left' ('' if none)."""
    if not _S.loop:
        return ""
    what, done, total, _depth, t_first, d_first, t_last = _S.loop
    text = "%s %d of %d" % (what, done, total)
    if total > 0:
        text += ", %d%%" % int(100.0 * done / total)
    now = time.time() if now is None else now
    if 0 < done < total and done > d_first and now - t_first >= ETA_AFTER:
        # the pace measured up to the last one, counted down since (frames from a thread pool come in bursts)
        left = (t_last - t_first) / float(done - d_first) * (total - done) - (now - t_last)
        text += ", %s left" % _seconds(left) if left >= 0.5 else ", nearly done"
    return text


def status_line(now=None, room=None):
    """What the status line says now (without the spinner), in `room` characters if given: the stages in the middle
    go first, then the end is cut."""
    line = _status(now)
    names = len(_S.stack)
    while room and len(line) > room and names > 0:
        names -= 1
        line = _status(now, names)
    if room and len(line) > room:
        line = line[:max(0, room - 3)] + "..."
    return line


def _status(now=None, keep=None):
    parts = []
    if _S.steps and 0 <= _S.at < len(_S.steps):
        parts.append("[%d/%d]" % (_S.at + 1, len(_S.steps)))
    names = [n for n, _ in _S.stack]
    if keep is not None and len(names) > keep:            # (the outermost and the innermost are the ones to keep)
        names = names[:keep] if keep < 2 else names[:1] + ["..."] + names[len(names) - keep + 1:]
    if _S.steps and 0 <= _S.at < len(_S.steps) and (not names or not names[0].startswith(_S.steps[_S.at])):
        names.insert(0, _S.steps[_S.at])
    text = " ".join(parts + [": ".join(names)]) if names else " ".join(parts)
    lt = loop_text(now)
    if lt:
        text = (text + ": " if text else "") + lt
    return "%s: %s" % (_S.prog or "bidet", text or "working")


def _draw():
    line = status_line(room=max(10, _columns() - 3))
    _write("\r" + line + " " + SPINNER[_S.turn % len(SPINNER)] + "\x1b[K")
    _S.turn += 1
    _S.shown = True


def _spin(stopping):
    if stopping.wait(SPIN_DELAY):
        return
    while not stopping.is_set():
        with _S.lock:
            if not _S.paused and not stopping.is_set():
                _draw()
        stopping.wait(SPIN_STEP)


def start(prog, debug=False, profile=False, spin=None, err=None):
    """Begin: `prog` names the tool in what it says.  spin: None = a status line when standard error is a terminal."""
    stop(report=False)
    _S.__init__()
    _S.prog, _S.debug, _S.profile, _S.err = prog, bool(debug), bool(profile), err
    if _S.profile:
        import cProfile
        _S.profiler = cProfile.Profile()
        _S.profiler.enable()
    if spin is None:                                         # (not with --profile: see THREADS)
        spin = _tty() and not os.environ.get("BIDET_NO_SPIN") and not _S.profile
    if spin:
        if not _S_atexit:
            atexit.register(stop, False)                     # (Ctrl-C: the status line is not left behind)
            _S_atexit.append(True)
        _S.stopping = threading.Event()
        _S.spin = threading.Thread(target=_spin, args=(_S.stopping,), name="bifdiag-status")
        _S.spin.daemon = True
        _S.spin.start()
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
    """A line on standard error, `prog: ...`, that does not tangle with the status line (it is drawn again after it)."""
    text = " ".join(str(w) for w in words)
    with _S.lock:
        _clear_line()
        _write("%s: %s\n" % (_S.prog or os.path.basename(sys.argv[0] or "bidet"), text))


def debug(*words):
    """say(), only with --debug."""
    if _S.debug:
        say(*words)


def _elapsed():
    return time.time() - _S.t0


def plan(names):
    """The steps of the pipeline that is about to run, by name ("bifin", "bifop spin", "bifout"): "[k/N]"."""
    _S.steps, _S.at = list(names), -1
    debug("steps:", ", ".join(_S.steps))


def step(name):
    """Step `name` of the plan begins (the next one of that name; the one under way is not counted twice)."""
    if not _S.steps or (0 <= _S.at < len(_S.steps) and _S.steps[_S.at] == name):
        return
    for i in range(_S.at + 1, len(_S.steps)):
        if _S.steps[i] == name:
            _S.at = i
            debug("step %d of %d: %s" % (i + 1, len(_S.steps), name))
            return


@contextlib.contextmanager
def stage(name):
    """A named stage: timed for --profile, shown as it starts and ends with --debug.  Stages nest."""
    if not active():
        yield
        return
    depth = len(_S.stack)
    path = tuple(n for n, _ in _S.stack) + (name,)
    if _S.debug:
        say("%7.2fs %s> %s" % (_elapsed(), "  " * depth, name))
    t = time.time()
    with _S.lock:
        _S.stack.append((name, t))
    try:
        yield
    finally:
        dt = time.time() - t
        with _S.lock:
            if _S.stack and _S.stack[-1][0] == name:
                _S.stack.pop()
            if _S.loop and _S.loop[3] > len(_S.stack):        # (the counted loop was inside this stage)
                _end_loop()
        rec = _S.times.setdefault(path, [0, 0.0, len(_S.times)])
        rec[0] += 1
        rec[1] += dt
        if _S.debug:
            say("%7.2fs %s< %s (%.3fs)" % (_elapsed(), "  " * depth, name, dt))


def _end_loop():
    what, done, total, _depth, t_first, _d_first, t_last = _S.loop
    _S.loop = None
    if _S.debug and done:
        say("%s: %d of %d in %.2fs" % (what, done, total, t_last - t_first))


def progress(what, done, total):
    """A counted loop: `done` of `total` (1, 2, ...).  The status line shows it with a percent and the time left."""
    if not active():
        return
    now = time.time()
    with _S.lock:
        lp = _S.loop
        if lp is None or lp[0] != what or done < lp[1]:
            if lp is not None:
                _end_loop()
            _S.loop = [what, done, total, len(_S.stack), now, done, now]
        else:
            lp[1], lp[2], lp[6] = done, total, now
        if done >= total:
            _end_loop()


@contextlib.contextmanager
def quiet():
    """No status line meanwhile: the terminal is being asked something, or an animation is playing on it."""
    with _S.lock:
        _S.paused += 1
        _clear_line()
    try:
        yield
    finally:
        with _S.lock:
            _S.paused -= 1


def stop(report=True):
    """The end: the status line goes, and with --profile the report is printed."""
    if _S.spin is not None:
        _S.stopping.set()
        _S.spin.join(1.0)
        _S.spin = None
    with _S.lock:
        _clear_line()
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
        lines += ["", "  the %d functions with the most cumulative time (%s):" % (TOP_FUNCTIONS, THREADS), ""]
        lines += ["  " + l for l in (body[start_at:] if start_at >= 0 else body).rstrip().splitlines()]
    return "\n".join(lines) + "\n\n"


# Before Python 3.12 cProfile sees only the thread that enabled it.  From 3.12 on (sys.monitoring) it sees every thread
# but keeps ONE call stack for all of them, so when threads take turns a call is put down to whatever another thread was
# in (the main thread's threading wait / acquire gets the 3D workers' time, and the cumulative column adds up to more
# than the run).  So --profile has no status line (its thread would be counted too), and BIDET_THREADS=1 draws 3D frames
# on the main thread for a list that is right function by function (the stage times are the real ones either way).
THREADS = ("every thread, mixed up between them: BIDET_THREADS=1 for a clean list" if sys.version_info >= (3, 12)
           else "main thread only: BIDET_THREADS=1 to count the 3D workers too")


def _order(path):
    """Stages in the order they first began, children under their parent."""
    return tuple(_S.times[path[:i + 1]][2] if path[:i + 1] in _S.times else 0 for i in range(len(path)))


def fail(prog, e, debug=False):
    """The way a tool dies of an error `e`: the message, and with --debug (or debug) the traceback before it."""
    if _S.debug or debug:
        import traceback
        with _S.lock:
            _clear_line()
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
