#!/usr/bin/env python3
"""bidetsh: an imitation of a bash prompt, for bidet behind ttyd (see bidet-web.sh).

It is NOT a shell.  Nothing a user types is ever given to a real shell, and only commands listed here run: bidet, a few
text toys (figlet, toilet, cowsay, cowthink, fortune, lolcat, banner) with a fixed list of options each, and builtins
(echo, ls, cat, rev, sort ... on a pretend file system).  What it copies from bash: quoting, $VAR, name=value, | pipelines,
; && ||, Tab completion, history.  Not supported, and refused with a message: redirections, & jobs, `...` and $(...),
globs, loops.  Nothing is written to disk; every external program is started from an argument list, with a fixed
environment, in an empty scratch directory, with a time limit.

  python3 ttyd/bidetsh.py            (BIDET_PY names the Python that has numpy and Pillow, for bidet itself)
  BIDETSH_PATH=dir:dir               where figlet, fortune ... are looked for (default /usr/games:/usr/local/bin:/usr/bin:/bin)
"""
from __future__ import print_function

import atexit
import calendar
import datetime
import os
import posixpath
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BIDET = os.path.join(os.path.dirname(HERE), "bidet.py")
SAFE_PATH = os.environ.get("BIDETSH_PATH", "/usr/games:/usr/local/bin:/usr/bin:/bin")
MAX_LINE = 1000       # characters in a command line
MAX_TEXT = 200        # characters of text given as arguments to a drawing command
MAX_STDIN = 2000      # characters piped into one
MAX_OUT = 100000      # characters kept of one command's output
MAX_VARS = 50
TIMEOUT = 30          # seconds for one external program
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
HOME = "/home/guest"
START = time.time()

MOTD = """\
BIDeT 4D web shell: an imitation of bash, not the real thing.
  fortune -s | cowsay                    figlet -f slant Hello | rev
  bidet -P arc,chrome Hello              fortune -s | bidet -P gold
Type help for the commands, Tab to complete, Ctrl-D to leave.
"""
README = """\
This is bidetsh, a make-believe shell.  Pipes work (fortune | cowsay | lolcat),
so do ; && || quotes and $VARIABLES.  The files you can see are pretend, and
so is almost everything else: nothing you type reaches a real shell.
bidet draws a picture on the terminal, so it goes last in a pipeline.
"""
FS = {
    "home": {"guest": {"README": README, "hello.txt": "Hello, World\n", "pictures": {}}},
    "etc": {"motd": MOTD, "hostname": "bidet\n", "shells": "/usr/bin/bidetsh\n"},
    "tmp": {},
    "usr": {"games": {}},
}
# named like tools people try, but not offered: say so instead of "command not found"
REFUSED = set("""bash sh zsh dash ksh csh tcsh fish python python3 perl ruby node php lua gcc make vi vim nano emacs ed ssh scp
telnet nc ncat curl wget ftp rm rmdir mv cp ln chmod chown mkdir touch kill pkill dd mount su apt apt-get dpkg pip""".split())


class ShellError(Exception):
    pass


class ExitShell(Exception):
    def __init__(self, status=0):
        Exception.__init__(self)
        self.status = status


# --- the pretend file system -------------------------------------------------------------------------------------------

def resolve(cwd, path):
    if path == "~" or path.startswith("~/"):
        path = HOME + path[1:]
    full = posixpath.normpath(posixpath.join(cwd, path))
    return "/" + full.lstrip("/")


def vfs_get(path):
    node = FS
    for part in [p for p in path.split("/") if p]:
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


# --- option checking ---------------------------------------------------------------------------------------------------

def v_int(lo, hi):
    def check(v):
        if not re.fullmatch(r"[0-9]{1,5}", v) or not lo <= int(v) <= hi:
            raise ShellError("%r: a whole number from %d to %d, please" % (v, lo, hi))
        return v
    return check


def v_re(pattern, what):
    def check(v):
        if not re.fullmatch(pattern, v):
            raise ShellError("%r is not %s" % (v, what))
        return v
    return check


V_NAME = v_re(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,40}", "a plain name (no paths)")
V_FILTER = v_re(r"[a-z0-9]+(:[a-z0-9]+)*", "a filter list such as gay:border")
V_EYES = v_re(r"[!-~]{1,2}", "one or two characters")
V_COLOR = v_re(r"[A-Za-z]{3,20}|#[0-9A-Fa-f]{6}", "a colour name or #rrggbb")
V_FLOAT = v_re(r"[0-9]{1,2}(\.[0-9]{1,3})?", "a number")
V_DIR = v_re(r"left|right|up|down", "left, right, up or down")


def getopts(cmd, args, short="", long_=(), valued=None, optional=None):
    """Split args into [(option, value-or-None)] and the other words.  Only what is listed is accepted.
    valued maps '-f' or '--font' to a checker that returns the value or raises ShellError; optional maps '--sway' to a checker for
    '--sway=VALUE' (no separate value).  A single dash and several letters (-ck) is fine."""
    valued, optional = valued or {}, optional or {}
    opts, words, i = [], [], 0
    while i < len(args):
        a = args[i]
        i += 1
        if a == "--":
            words += args[i:]
            break
        if a.startswith("--"):
            name, eq, val = a.partition("=")
            if name in long_ and not eq:
                opts.append((name, None))
            elif name in valued:
                if not eq:
                    if i >= len(args):
                        raise ShellError("option '%s' needs a value" % name)
                    val, i = args[i], i + 1
                opts.append((name, valued[name](val)))
            elif name in optional:
                opts.append((name, optional[name](val) if eq else None))
            else:
                raise ShellError("unrecognized option '%s'" % name)
        elif a.startswith("-") and len(a) > 1 and not a[1:].isdigit():
            k = 1
            while k < len(a):
                ch = a[k]
                k += 1
                if ch in short:
                    opts.append(("-" + ch, None))
                elif "-" + ch in valued:
                    val = a[k:]
                    if not val:
                        if i >= len(args):
                            raise ShellError("option requires a value -- '%s'" % ch)
                        val, i = args[i], i + 1
                    opts.append(("-" + ch, valued["-" + ch](val)))
                    break
                else:
                    raise ShellError("invalid option -- '%s'" % ch)
        else:
            words.append(a)
    return opts, words


def flat(opts):
    out = []
    for name, val in opts:
        if val is None:
            out.append(name)
        elif name.startswith("--") and name in ("--sway", "--scroll"):
            out.append("%s=%s" % (name, val))
        else:
            out += [name, val]
    return out


# --- the shell ---------------------------------------------------------------------------------------------------------

def is_assignment(word):
    """name=value, judged before expansion: it starts with literal text that has NAME= in it."""
    return bool(word) and isinstance(word[0], str) and bool(re.match(r"[A-Za-z_][A-Za-z0-9_]*=", word[0]))


class Shell(object):
    def __init__(self, out=None, err=None, interactive=False):
        self.out = out or sys.stdout
        self.err_stream = err or sys.stderr
        self.interactive = interactive
        self.cwd = HOME
        self.status = 0
        self.last = True
        self.vars = {"HOME": HOME, "USER": "guest", "HOSTNAME": "bidet", "SHELL": "/usr/bin/bidetsh", "TERM": "xterm-256color"}
        self.scratch = tempfile.mkdtemp(prefix="bidetsh-")
        atexit.register(shutil.rmtree, self.scratch, True)
        self._presets = None
        self._found = {}

    # ---- helpers
    def err(self, msg):
        self.err_stream.write(re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "?", msg) + "\n")

    def which(self, name):
        if name not in self._found:
            self._found[name] = shutil.which(name, path=SAFE_PATH)
        return self._found[name]

    def presets(self):
        if self._presets is None:
            try:
                out = subprocess.run([bidet_python(), BIDET, "-l"], stdin=subprocess.DEVNULL, capture_output=True, cwd=self.scratch,
                                     timeout=TIMEOUT).stdout.decode("utf-8", "replace")
                self._presets = [ln.split()[0] for ln in out.splitlines() if ln.split()]
            except (OSError, subprocess.SubprocessError):
                self._presets = []
        return self._presets

    def getvar(self, name):
        if name == "RANDOM":
            return str(random.randrange(32768))
        if name == "PWD":
            return self.cwd
        return self.vars.get(name, "")

    def prompt(self):
        where = "~" + self.cwd[len(HOME):] if self.cwd == HOME or self.cwd.startswith(HOME + "/") else self.cwd
        return "\001\033[1;32m\002guest@bidet\001\033[0m\002:\001\033[1;34m\002%s\001\033[0m\002$ " % where

    def commands(self):
        cmds = dict(BUILTINS)
        for name, tool in TOOLS.items():
            if tool is bidet or self.which(name):
                cmds[name] = tool
        return cmds

    # ---- reading a line
    def tokenize(self, line):
        """('word', parts) and ('op', '|' ';' '&&' '||') tokens; quotes are dealt with here.  A word is a list of parts: text, or
        ('$', NAME) for a variable, which expand() fills in only when the pipeline runs (as in bash: x=1; echo $x)."""
        toks, buf, have, i, n = [], [], False, 0, len(line)

        def flush():
            if have:
                word = []
                for part in buf:
                    if word and isinstance(part, str) and isinstance(word[-1], str):
                        word[-1] += part
                    else:
                        word.append(part)
                toks.append(("word", word))
            del buf[:]

        while i < n:
            c = line[i]
            if c in " \t":
                flush()
                have = False
                i += 1
            elif c == "#" and not have:
                break
            elif c == "'":
                j = line.find("'", i + 1)
                if j < 0:
                    raise ShellError("unterminated quote")
                buf.append(line[i + 1:j])
                have, i = True, j + 1
            elif c == '"':
                have, i = True, i + 1
                while True:
                    if i >= n:
                        raise ShellError("unterminated quote")
                    c = line[i]
                    if c == '"':
                        i += 1
                        break
                    if c == "\\" and i + 1 < n and line[i + 1] in '"\\$`':
                        buf.append(line[i + 1])
                        i += 2
                    elif c == "$":
                        text, i = self.dollar(line, i)
                        buf.append(text)
                    elif c == "`":
                        raise ShellError("`...` is not supported")
                    else:
                        buf.append(c)
                        i += 1
            elif c == "\\":
                if i + 1 < n:
                    buf.append(line[i + 1])
                    have = True
                i += 2
            elif c == "$":
                text, i = self.dollar(line, i)
                buf.append(text)
                have = True
            elif c in ";|&":
                flush()
                have = False
                two = line[i:i + 2]
                if two in ("&&", "||"):
                    toks.append(("op", two))
                    i += 2
                elif c == "&":
                    raise ShellError("& (background jobs) is not supported")
                else:
                    toks.append(("op", c))
                    i += 1
            elif c in "<>()`":
                raise ShellError("%s is not supported here (no redirection, subshells or substitution)" % c)
            else:
                buf.append(c)
                have, i = True, i + 1
        flush()
        return toks

    def dollar(self, line, i):
        n, j = len(line), i + 1
        if j < n and line[j] == "?":
            return ("$", "?"), j + 1
        if j < n and line[j] == "(":
            raise ShellError("$( ) is not supported")
        if j < n and line[j] == "{":
            k = line.find("}", j)
            if k < 0 or not NAME.fullmatch(line[j + 1:k]):
                raise ShellError("bad substitution")
            return ("$", line[j + 1:k]), k + 1
        m = NAME.match(line, j)
        if m:
            return ("$", m.group()), m.end()
        return "$", j

    def expand(self, word):
        out = []
        for part in word:
            if isinstance(part, str):
                out.append(part)
            else:
                out.append(str(self.status) if part[1] == "?" else self.getvar(part[1]))
        return "".join(out)

    @staticmethod
    def parse(toks):
        """[(connector, [argv, argv ...])]: connector is how this pipeline follows the last one (';' '&&' '||')."""
        seq, conn, pipe, argv = [], ";", [], []
        for kind, val in toks:
            if kind == "word":
                argv.append(val)
                continue
            if not argv:
                raise ShellError("syntax error near unexpected token '%s'" % val)
            pipe.append(argv)
            argv = []
            if val != "|":
                seq.append((conn, pipe))
                conn, pipe = val, []
        if argv:
            pipe.append(argv)
        elif pipe or conn != ";":
            raise ShellError("syntax error: unexpected end of line")
        if pipe:
            seq.append((conn, pipe))
        return seq

    # ---- running it
    def run_line(self, line):
        """Run one command line; the status goes in $?.  ExitShell leaves."""
        if len(line) > MAX_LINE:
            self.err("bidetsh: line too long")
            return
        if re.search(r"[\x00-\x08\x0a-\x1f\x7f]", line):
            return
        try:
            seq = self.parse(self.tokenize(line))
        except ShellError as e:
            self.err("bidetsh: %s" % e)
            self.status = 2
            return
        for conn, pipe in seq:
            if (conn == "&&" and self.status != 0) or (conn == "||" and self.status == 0):
                continue
            self.status = self.run_pipeline(pipe)

    def run_pipeline(self, stages):
        if len(stages) == 1:
            words = stages[0][1:] if stages[0] and stages[0][0] == ["export"] else stages[0]
            if words and all(is_assignment(w) for w in words):
                try:
                    for w in words:
                        name, _, first = w[0].partition("=")
                        val = self.expand([first] + w[1:])[:500]
                        if not NAME.fullmatch(name) or len(name) > 32:
                            raise ShellError("%s: not a valid identifier" % name)
                        if name not in self.vars and len(self.vars) >= MAX_VARS:
                            raise ShellError("too many variables")
                        self.vars[name] = val
                    return 0
                except ShellError as e:
                    self.err("bidetsh: %s" % e)
                    return 1
        stages = [[self.expand(w) for w in argv] for argv in stages]
        cmds = self.commands()
        data, rc = None, 0
        for k, argv in enumerate(stages):
            self.last = k == len(stages) - 1
            name = argv[0]
            fn = cmds.get(name)
            if fn is None:
                if name in REFUSED:
                    self.err("bidetsh: %s: not available (this is an imitation shell)" % name)
                elif name in TOOLS:
                    self.err("bidetsh: %s: not installed on this machine" % name)
                else:
                    self.err("bidetsh: %s: command not found (try: help)" % name)
                data, rc = "", 127
                continue
            try:
                data, rc = fn(self, argv[1:], data)
            except ShellError as e:
                self.err("%s: %s" % (name, e))
                data, rc = "", 2
            except subprocess.TimeoutExpired:
                self.err("%s: timed out after %d s" % (name, TIMEOUT))
                data, rc = "", 124
            data = (data or "")[:MAX_OUT]
        if data:
            self.out.write(data)
            self.out.flush()
        return rc


# --- running outside programs ------------------------------------------------------------------------------------------

def bidet_python():
    return os.environ.get("BIDET_PY") or sys.executable


def run_ext(sh, argv, data=None, env=None):
    """Run a program from an argument list (never a shell), scratch directory; (stdout, status).  The environment is a fixed small
    one unless env is given (bidet, which is our own code, gets ours: Python and numpy may need more than PATH)."""
    env = env or {"PATH": SAFE_PATH, "LANG": os.environ.get("LANG", "C.UTF-8"), "TERM": "xterm-256color",
                  "COLUMNS": str(shutil.get_terminal_size((80, 24)).columns)}
    kw = {"input": data.encode("utf-8", "replace")} if data is not None else {"stdin": subprocess.DEVNULL}
    try:
        p = subprocess.run(argv, capture_output=True, env=env, cwd=sh.scratch, timeout=TIMEOUT, **kw)
    except OSError as e:
        raise ShellError(str(e))
    for ln in p.stderr.decode("utf-8", "replace").splitlines()[:3]:
        sh.err(os.path.basename(argv[0]) + ": " + ln)
    return p.stdout.decode("utf-8", "replace"), p.returncode


def text_tool(binname, short="", long_=(), valued=None, words="text", info="", force=()):
    """A program that takes text as its message.  words: 'text' (joined, after --), 'category' (fortune), 'none' (stdin only)."""
    def tool(sh, args, stdin):
        opts, rest = getopts(binname, args, short, long_, valued or {})
        argv = [sh.which(binname)] + list(force) + flat(opts)
        data = None
        if words == "category":
            for w in rest:
                if not re.fullmatch(r"[a-z][a-z0-9-]{0,30}", w):
                    raise ShellError("%r is not a category name" % w)
            argv += rest
        elif words == "none" and rest:
            raise ShellError("it reads the pipe only: try  fortune | %s" % binname)
        elif rest:
            joined = " ".join(rest)
            if len(joined) > MAX_TEXT:
                raise ShellError("too long (max %d characters)" % MAX_TEXT)
            argv += ["--", joined]
        elif stdin:
            if len(stdin) > MAX_STDIN:
                raise ShellError("input too long (max %d characters)" % MAX_STDIN)
            data = stdin
        elif not any(name in info for name, _ in opts):
            raise ShellError("give it some text, or pipe some in")
        return run_ext(sh, argv, data)
    return tool


TOOLS = {
    "figlet": text_tool("figlet", "clrxkosSW", valued={"-f": V_NAME, "-w": v_int(1, 200)}),
    "toilet": text_tool("toilet", "kosSW", ("--gay", "--metal"), {"-f": V_NAME, "-F": V_FILTER, "-w": v_int(1, 200)}),
    "cowsay": text_tool("cowsay", "bdgpstwynl", valued={"-f": V_NAME, "-e": V_EYES, "-T": V_EYES, "-W": v_int(1, 200)}, info=("-l",)),
    "cowthink": text_tool("cowthink", "bdgpstwynl", valued={"-f": V_NAME, "-e": V_EYES, "-T": V_EYES, "-W": v_int(1, 200)},
                          info=("-l",)),
    "fortune": text_tool("fortune", "sl", words="category"),
    "lolcat": text_tool("lolcat", "ti", valued={"-p": v_int(1, 99), "-F": v_int(1, 99), "-S": v_int(1, 99999)}, words="none",
                        force=("-f",)),
    "banner": text_tool("banner"),
}

def window_size():
    """(rows, columns, width px, height px) of the terminal; the pixels are 0 if it does not say (ttyd does not), and 24x80 if
    there is no terminal."""
    try:
        import fcntl
        import struct
        import termios
        return struct.unpack("HHHH", fcntl.ioctl(1, termios.TIOCGWINSZ, b"\0" * 8))
    except Exception:
        return (24, 80, 0, 0)


def fit_size(width=None):
    """(width, height) in pixels to draw within.  The width is bidet's own rule (95% of the window, or 8 px a column when the
    terminal gives no pixels); the height leaves the last three rows free.  A picture as tall as the window hides the prompt
    under it (the browser draws images over the text), and a wide window gives a tall picture.  A row is taken as 17 px when
    the terminal does not say."""
    rows, cols, xp, yp = window_size()
    rows, cols = rows or 24, cols or 80
    w = width or max(320, min(2400, int(0.95 * xp) if xp else 8 * cols))
    cell_h = yp / float(rows) if yp else 17
    return w, max(100, int((rows - 3) * cell_h))


def termsize(sh, args, stdin):
    """What the terminal reports and the picture size bidet is given: for finding out why a picture does not fit a window."""
    rows, cols, xp, yp = window_size()
    sys.path.insert(0, os.path.dirname(HERE))
    try:
        import bifterm
        reply = bifterm.query(want_bg=False, want_cell=True)
        cell = "%s (width, height) px, asked: %s, sixel: %s" % (reply.cell, reply.asked, reply.sixel)
    except Exception as e:
        cell = "not asked (%s)" % e
    w, h = fit_size()
    return ("window:   %d rows x %d columns, %d x %d px reported (0 = not said)\ncell:     %s\npicture:  at most %d x %d px "
            "(%d px per row assumed)\n" % (rows, cols, xp, yp, cell, w, h, 17)), 0


def bidet(sh, args, stdin):
    presets = sh.presets()

    def v_preset(v):
        for p in v.split(","):
            if p not in presets:
                raise ShellError("no such preset: %s (try: bidet -l)" % p)
        return v

    opts, words = getopts("bidet", args, short="lhV",
                          long_=("--3d", "--spin", "--pop", "--dark", "--light", "--time-machine", "--list-presets",
                                 "--help", "--version", "--list-fonts"),
                          valued={"-P": v_preset, "--preset": v_preset, "-w": v_int(100, 1600), "--width": v_int(100, 1600),
                                  "--ink": V_COLOR, "--paper": V_COLOR, "--material": V_COLOR, "--depth": V_FLOAT},
                          optional={"--sway": v_int(1, 90), "--scroll": V_DIR})
    names = [n for n, _ in opts]
    if set(names) & {"-l", "--list-presets", "-h", "--help", "-V", "--version", "--list-fonts"}:
        info = [n for n in names if n in ("-l", "--list-presets", "-h", "--help", "-V", "--version", "--list-fonts")][0]
        return run_ext(sh, [bidet_python(), BIDET, info], env=dict(os.environ))
    if words:
        text = " ".join(words)
    elif stdin:
        text = stdin.strip()
    else:
        raise ShellError("give it some text (bidet [-P preset[,preset]] Hello), or pipe some in; bidet -l lists the presets")
    if not text:
        raise ShellError("nothing to draw")
    if len(text) > MAX_TEXT:
        raise ShellError("too long (max %d characters)" % MAX_TEXT)
    if not sh.last:
        raise ShellError("it draws on the terminal, so it has to be the last command in a pipeline")
    argv = [bidet_python(), BIDET, "-t"]
    width = None
    for name, val in opts:
        if name in ("-P", "--preset"):
            for p in val.split(","):
                argv += ["-P", p]
        elif name in ("-w", "--width"):
            width = int(val)
        else:
            argv += flat([(name, val)])
    argv += ["--bifout=--width %d --height %d" % fit_size(width), "--", text]
    try:
        # inherits the terminal (it asks it for its size, then draws SIXEL); same process group, so no SIGTTIN
        rc = subprocess.run(argv, cwd=sh.scratch, timeout=TIMEOUT).returncode
    except subprocess.TimeoutExpired:
        sh.out.write("\n")
        sh.err("bidet: stopped after %d s" % TIMEOUT)
        rc = 124
    except OSError as e:
        raise ShellError(str(e))
    if sh.interactive:
        sh.out.write("\033[0m\033[?25h")      # an animation cut short can leave the cursor hidden
        sh.out.flush()
    return "", rc


TOOLS["bidet"] = bidet


# --- builtins ----------------------------------------------------------------------------------------------------------

BUILTINS = {}


def builtin(*names):
    def deco(fn):
        for name in names:
            BUILTINS[name] = fn
        return fn
    return deco


builtin("termsize")(termsize)


def need_stdin(stdin):
    if stdin is None:
        raise ShellError("no file given, and nothing piped in")
    return stdin


def lines_of(text):
    return text.split("\n")[:-1] if text.endswith("\n") else text.split("\n")


def num_opt(args, default):
    """-n N, -nN or -N from head/tail/seq style arguments: (N, remaining args)."""
    n, rest, i = default, [], 0
    while i < len(args):
        a = args[i]
        m = re.fullmatch(r"-n?(\d+)", a)
        if a == "-n" and i + 1 < len(args) and args[i + 1].isdigit():
            n, i = int(args[i + 1]), i + 1
        elif m:
            n = int(m.group(1))
        else:
            rest.append(a)
        i += 1
    return min(n, 100000), rest


@builtin("help", "?")
def b_help(sh, args, stdin):
    cmds = sh.commands()
    have = lambda *names: "  ".join(n for n in names if n in cmds)
    text = """\
bidetsh, an imitation of bash.  Join commands with | (pipe), ; && ||.  Quotes, $VARS and name=value work.

  bidet [-P preset[,preset]] [--3d] [--spin] [--pop] [--scroll] [-w px] TEXT   draw a picture (last in a pipeline)
  bidet -l                       list the presets      bidet -h   all the options
  text toys:  %s
  text tools: cat rev tac nl wc head tail sort uniq tr grep seq
  the rest:   echo ls cd pwd date cal whoami hostname uname id uptime env history clear fonts termsize type help exit

  fortune -s | cowsay                  figlet -f slant Hello | rev
  fortune -s | bidet -P gold           echo "Hello" | toilet --gay
  x=Hi; echo $x there | figlet         cal 2026 | head -n 8
""" % (have("figlet", "toilet", "cowsay", "cowthink", "fortune", "lolcat", "banner") or "(none installed)")
    return text, 0


@builtin("exit", "logout", "quit")
def b_exit(sh, args, stdin):
    raise ExitShell(int(args[0]) % 256 if args and args[0].isdigit() else sh.status)


@builtin("clear")
def b_clear(sh, args, stdin):
    return ("\033[H\033[2J\033[3J" if sh.last else ""), 0


@builtin("echo")
def b_echo(sh, args, stdin):
    nl, esc = True, False
    while args and re.fullmatch(r"-[neE]+", args[0]):
        nl = nl and "n" not in args[0]
        esc = "e" in args[0] or (esc and "E" not in args[0])
        args = args[1:]
    text = " ".join(args)
    if esc:
        table = {"n": "\n", "t": "\t", "e": "\033", "\\": "\\", "a": "\a", "r": "\r"}
        text = re.sub(r"\\(.)", lambda m: table.get(m.group(1), m.group(0)), text)
    return text + ("\n" if nl else ""), 0


@builtin("pwd")
def b_pwd(sh, args, stdin):
    return sh.cwd + "\n", 0


@builtin("cd")
def b_cd(sh, args, stdin):
    path = resolve(sh.cwd, args[0] if args else "~")
    node = vfs_get(path)
    if node is None:
        raise ShellError("%s: No such file or directory" % (args[0] if args else path))
    if not isinstance(node, dict):
        raise ShellError("%s: Not a directory" % args[0])
    sh.cwd = path
    return "", 0


@builtin("ls")
def b_ls(sh, args, stdin):
    flags, paths = set(), []
    for a in args:
        if a.startswith("-") and len(a) > 1:
            if not set(a[1:]) <= set("alF1"):
                raise ShellError("invalid option -- '%s'" % a[1:])
            flags |= set(a[1:])
        else:
            paths.append(a)
    out, rc = [], 0
    for p in paths or ["."]:
        node = vfs_get(resolve(sh.cwd, p))
        if node is None:
            sh.err("ls: cannot access '%s': No such file or directory" % p)
            rc = 2
            continue
        items = [(posixpath.basename(p.rstrip("/")) or p, node)] if not isinstance(node, dict) else \
            [(k, node[k]) for k in sorted(node) if "a" in flags or not k.startswith(".")]
        if "a" in flags and isinstance(node, dict):
            items = [(".", {}), ("..", {})] + items
        for name, item in items:
            if "l" in flags:
                d = isinstance(item, dict)
                out.append("%s 1 guest guest %5d Oct 29 12:00 %s" % ("drwxr-xr-x" if d else "-rw-r--r--", 4096 if d else len(item),
                                                                      name + ("/" if d and "F" in flags else "")))
            else:
                out.append(name + ("/" if isinstance(item, dict) and "F" in flags else ""))
    if out and not ("l" in flags or "1" in flags) and sh.last and sh.interactive:
        width = max(map(len, out)) + 2
        per = max(1, shutil.get_terminal_size((80, 24)).columns // width)
        out = ["".join(n.ljust(width) for n in out[i:i + per]).rstrip() for i in range(0, len(out), per)]
    return "".join(ln + "\n" for ln in out), rc


@builtin("cat")
def b_cat(sh, args, stdin):
    if not args:
        return need_stdin(stdin), 0
    out, rc = [], 0
    for a in args:
        node = vfs_get(resolve(sh.cwd, a)) if a != "-" else need_stdin(stdin)
        if node is None:
            sh.err("cat: %s: No such file or directory" % a)
            rc = 1
        elif isinstance(node, dict):
            sh.err("cat: %s: Is a directory" % a)
            rc = 1
        else:
            out.append(node)
    return "".join(out), rc


@builtin("whoami")
def b_whoami(sh, args, stdin):
    return "guest\n", 0


@builtin("id")
def b_id(sh, args, stdin):
    return "uid=1000(guest) gid=1000(guest) groups=1000(guest)\n", 0


@builtin("hostname")
def b_hostname(sh, args, stdin):
    return "bidet\n", 0


@builtin("uname")
def b_uname(sh, args, stdin):
    return ("BIDeT bidet 4D ttyd imitation\n" if "-a" in args else "BIDeT\n"), 0


@builtin("uptime")
def b_uptime(sh, args, stdin):
    s = int(time.time() - START)
    return " %s up %d min, 1 user\n" % (time.strftime("%H:%M:%S"), s // 60), 0


@builtin("date")
def b_date(sh, args, stdin):
    fmt = args[0][1:] if args and args[0].startswith("+") else "%a %b %e %H:%M:%S %Z %Y"
    return time.strftime(fmt) + "\n", 0


@builtin("cal")
def b_cal(sh, args, stdin):
    nums = [a for a in args if a.isdigit()]
    if len(nums) != len(args) or len(nums) > 2:
        raise ShellError("usage: cal [[month] year]")
    now = datetime.date.today()
    cal = calendar.TextCalendar(6)
    if len(nums) == 2:
        month, year = int(nums[0]), int(nums[1])
    elif nums:
        month, year = None, int(nums[0])
    else:
        month, year = now.month, now.year
    if not 1 <= year <= 9999 or (month is not None and not 1 <= month <= 12):
        raise ShellError("bad month or year")
    return (cal.formatmonth(year, month) if month else cal.formatyear(year)), 0


@builtin("env", "printenv")
def b_env(sh, args, stdin):
    return "".join("%s=%s\n" % kv for kv in sorted(sh.vars.items())), 0


@builtin("history")
def b_history(sh, args, stdin):
    try:
        import readline
        n = readline.get_current_history_length()
        return "".join("%5d  %s\n" % (i, readline.get_history_item(i)) for i in range(1, n + 1)), 0
    except ImportError:
        return "", 0


@builtin("type", "which")
def b_type(sh, args, stdin):
    cmds, out, rc = sh.commands(), [], 0
    for a in args:
        if a in TOOLS and a in cmds:
            out.append("%s is /usr/bin/%s" % (a, a))
        elif a in cmds:
            out.append("%s is a shell builtin" % a)
        else:
            sh.err("bidetsh: type: %s: not found" % a)
            rc = 1
    return "".join(ln + "\n" for ln in out), rc


@builtin("sudo")
def b_sudo(sh, args, stdin):
    sh.err("guest is not in the sudoers file.  This incident will be reported.")
    return "", 1


@builtin("true")
def b_true(sh, args, stdin):
    return "", 0


@builtin("false")
def b_false(sh, args, stdin):
    return "", 1


@builtin("fonts")
def b_fonts(sh, args, stdin):
    """The figlet / toilet font names, for figlet -f and toilet -f."""
    figlet = sh.which("figlet")
    if not figlet:
        raise ShellError("figlet is not installed on this machine")
    fontdir = run_ext(sh, [figlet, "-I2"])[0].strip()
    try:
        names = sorted({os.path.splitext(f)[0] for f in os.listdir(fontdir) if f.endswith((".flf", ".tlf"))})
    except OSError:
        raise ShellError("no font directory")
    return "".join(n + "\n" for n in names), 0


# text filters, for the middle of a pipeline

@builtin("rev")
def b_rev(sh, args, stdin):
    return "".join(ln[::-1] + "\n" for ln in lines_of(need_stdin(stdin))), 0


@builtin("tac")
def b_tac(sh, args, stdin):
    return "".join(ln + "\n" for ln in reversed(lines_of(need_stdin(stdin)))), 0


@builtin("nl")
def b_nl(sh, args, stdin):
    return "".join("%6d\t%s\n" % (i, ln) for i, ln in enumerate(lines_of(need_stdin(stdin)), 1)), 0


@builtin("wc")
def b_wc(sh, args, stdin):
    text = need_stdin(stdin)
    counts = {"l": text.count("\n"), "w": len(text.split()), "c": len(text.encode("utf-8"))}
    want = [c for a in args if a.startswith("-") for c in a[1:] if c in counts] or ["l", "w", "c"]
    return " ".join(str(counts[c]) for c in "lwc" if c in want) + "\n", 0


@builtin("head")
def b_head(sh, args, stdin):
    n, _ = num_opt(args, 10)
    return "".join(ln + "\n" for ln in lines_of(need_stdin(stdin))[:n]), 0


@builtin("tail")
def b_tail(sh, args, stdin):
    n, _ = num_opt(args, 10)
    return "".join(ln + "\n" for ln in (lines_of(need_stdin(stdin))[-n:] if n else [])), 0


@builtin("sort")
def b_sort(sh, args, stdin):
    flags = "".join(a[1:] for a in args if a.startswith("-"))
    ls = lines_of(need_stdin(stdin))
    def number(s):
        m = re.match(r"\s*-?\d+(\.\d+)?", s)
        return float(m.group()) if m else 0.0

    ls = sorted(ls, key=number if "n" in flags else None, reverse="r" in flags)
    if "u" in flags:
        ls = [ln for i, ln in enumerate(ls) if i == 0 or ln != ls[i - 1]]
    return "".join(ln + "\n" for ln in ls), 0


@builtin("uniq")
def b_uniq(sh, args, stdin):
    out, prev, count = [], None, 0
    for ln in lines_of(need_stdin(stdin)) + [None]:
        if ln == prev:
            count += 1
            continue
        if prev is not None:
            out.append(("%7d %s" % (count, prev)) if "-c" in args else prev)
        prev, count = ln, 1
    return "".join(ln + "\n" for ln in out), 0


@builtin("grep")
def b_grep(sh, args, stdin):
    flags = "".join(a[1:] for a in args if re.fullmatch(r"-[ivcn]+", a))
    pats = [a for a in args if not re.fullmatch(r"-[ivcn]+", a)]
    if len(pats) != 1:
        raise ShellError("usage: grep [-ivcn] TEXT   (plain text, not a pattern; reads the pipe)")
    pat = pats[0].lower() if "i" in flags else pats[0]
    hits = [(i, ln) for i, ln in enumerate(lines_of(need_stdin(stdin)), 1)
            if ((pat in (ln.lower() if "i" in flags else ln)) != ("v" in flags))]
    if "c" in flags:
        return "%d\n" % len(hits), 0 if hits else 1
    return "".join(("%d:%s\n" % h) if "n" in flags else h[1] + "\n" for h in hits), 0 if hits else 1


def tr_set(spec):
    spec = re.sub(r"\[:(upper|lower|digit|alpha):\]",
                  lambda m: {"upper": "A-Z", "lower": "a-z", "digit": "0-9", "alpha": "A-Za-z"}[m.group(1)], spec)
    spec = spec.replace("\\n", "\n").replace("\\t", "\t")
    out, i = [], 0
    while i < len(spec):
        if i + 2 < len(spec) and spec[i + 1] == "-" and ord(spec[i + 2]) >= ord(spec[i]):
            out += [chr(c) for c in range(ord(spec[i]), ord(spec[i + 2]) + 1)]
            i += 3
        else:
            out.append(spec[i])
            i += 1
    return "".join(out)


@builtin("tr")
def b_tr(sh, args, stdin):
    delete = args[:1] == ["-d"]
    sets = args[1:] if delete else args
    if len(sets) != (1 if delete else 2):
        raise ShellError("usage: tr SET1 SET2   or   tr -d SET")
    a = tr_set(sets[0])
    if delete:
        table = {ord(c): None for c in a}
    else:
        b = tr_set(sets[1]) or " "
        table = {ord(c): b[min(i, len(b) - 1)] for i, c in enumerate(a)}
    return need_stdin(stdin).translate(table), 0


@builtin("seq")
def b_seq(sh, args, stdin):
    try:
        nums = [int(a) for a in args]
    except ValueError:
        raise ShellError("whole numbers only")
    if len(nums) == 1:
        first, step, last = 1, 1, nums[0]
    elif len(nums) == 2:
        first, step, last = nums[0], 1, nums[1]
    elif len(nums) == 3:
        first, step, last = nums
    else:
        raise ShellError("usage: seq [first [step]] last")
    if step == 0 or (last - first) // step > 1000:
        raise ShellError("at most 1000 numbers")
    return "".join("%d\n" % n for n in range(first, last + (1 if step > 0 else -1), step)), 0


# --- the terminal ------------------------------------------------------------------------------------------------------

def setup_readline(sh):
    try:
        import readline
    except ImportError:
        return

    def complete(text, state):
        buf = readline.get_line_buffer()[:readline.get_begidx()]
        seg = re.split(r"[|;&]", buf)[-1].split()
        if not seg:
            pool = sorted(sh.commands())
        elif seg[-1] in ("-P", "--preset"):
            pool = sh.presets()
        else:
            node = vfs_get(sh.cwd)
            pool = sorted(node) if isinstance(node, dict) else []
        hits = [c + " " for c in pool if c.startswith(text)]
        return hits[state] if state < len(hits) else None

    readline.set_completer_delims(" \t\n|;&")
    readline.set_completer(complete)
    readline.parse_and_bind("tab: complete")


def main():
    interactive = sys.stdin.isatty()
    sh = Shell(interactive=interactive)
    if interactive:
        setup_readline(sh)
        sys.stdout.write(MOTD + "\n")
    while True:
        try:
            line = input(sh.prompt() if interactive else "")
        except EOFError:
            if interactive:
                print("logout")
            break
        except KeyboardInterrupt:
            print("^C")
            sh.status = 130
            continue
        try:
            sh.run_line(line)
        except ExitShell as e:
            return e.status
        except KeyboardInterrupt:
            print("^C")
            sh.status = 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
