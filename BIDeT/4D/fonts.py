#!/usr/bin/env python3
"""fonts: find a TrueType font by name.

    fonts.find("impact")                       a path (some heavy sans if there is no Impact)
    fonts.resolve("serif", bold=True)          a Face: path, family, style, and whether bold / italic have to be faked
    fonts.find("Georgia,serif")                the first that exists
    fonts.families()                           what is installed

A name is a file, a family ("DejaVu Sans", any case, or a part of one), or a generic: sans, serif, mono, impact
(a heavy sans), script, comic, times, arial, courier, georgia.  A generic carries a list of fallbacks, so a recipe
that says `--font impact` works on any machine: it gets Impact where there is one.  A list joined with commas is
tried in order.  Only TrueType-outline fonts (.ttf, .ttc) are seen: that is what ttfglyphs reads.
Python 3.7+.
"""
from __future__ import print_function

import json
import os

import ttfglyphs

FONT_DIRS = ["C:/Windows/Fonts", "/cygdrive/c/Windows/Fonts", "/mnt/c/Windows/Fonts", "~/AppData/Local/Microsoft/Windows/Fonts",
             "/usr/share/fonts", "/usr/local/share/fonts", "~/.fonts", "~/.local/share/fonts",
             "/System/Library/Fonts", "/Library/Fonts", "~/Library/Fonts"]

STANDARD_STYLES = ("regular", "italic", "bold", "bold italic", "oblique", "bold oblique", "book", "roman", "normal", "medium")

_SANS = ["Arial", "Helvetica", "DejaVu Sans", "Liberation Sans", "Noto Sans", "Segoe UI", "FreeSans", "Verdana", "Bitstream Vera Sans"]
_SERIF = ["Times New Roman", "Georgia", "DejaVu Serif", "Liberation Serif", "Noto Serif", "FreeSerif", "Bitstream Vera Serif"]
_MONO = ["Consolas", "DejaVu Sans Mono", "Liberation Mono", "Menlo", "Courier New", "FreeMono", "Noto Sans Mono", "Bitstream Vera Sans Mono"]
# a generic name: families to try, in order; (name, True) means "this family, bold"
ALIASES = {
    "sans": _SANS, "arial": _SANS, "helvetica": _SANS,
    "serif": _SERIF, "times": _SERIF,
    "mono": _MONO, "courier": ["Courier New", "Liberation Mono", "FreeMono"] + _MONO,
    "georgia": ["Georgia"] + _SERIF,
    "impact": ["Impact", "Anton", "Haettenschweiler", "Arial Black", ("Arial", True), ("DejaVu Sans", True), ("Liberation Sans", True),
               ("Noto Sans", True), ("FreeSans", True), ("Verdana", True)],
    "comic": ["Comic Sans MS", "Comic Neue", "Chalkboard", "Marker Felt"] + _SANS,
    "script": ["Segoe Script", "Brush Script MT", "Lucida Handwriting", "URW Chancery L", "Z003"] + [(f, "italic") for f in _SERIF],
}


class FontNotFound(Exception):
    """No font by that name: the message lists some that exist."""


class Face(object):
    """One font file: path, family, style, bold, italic; need_bold / need_italic say a face of the wanted style does
    not exist, so the caller has to fake it."""
    def __init__(self, path, family, style, bold, italic):
        self.path, self.family, self.style, self.bold, self.italic = path, family, style, bold, italic
        self.need_bold = self.need_italic = False

    def __repr__(self):
        return "<Face %s %s (%s)>" % (self.family, self.style, os.path.basename(self.path))


_cache = {}


def font_dirs(extra=None):
    out = [os.path.expanduser(d) for d in FONT_DIRS + list(extra or [])]
    return [d for d in out if os.path.isdir(d)]


def cache_path(env=None):
    env = os.environ if env is None else env
    base = env.get("BIDET_CACHE") or os.path.join(env.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache"), "bidet")
    return os.path.join(base, "fonts.json")


def _load_cache(path):
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) and data.get("version") == 1 else {}
    except (IOError, OSError, ValueError):
        return {}


def _save_cache(path, data):
    try:
        d = os.path.dirname(path)
        if not os.path.isdir(d):
            os.makedirs(d)
        tmp = path + ".%d.tmp" % os.getpid()
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except (IOError, OSError):
        pass                                                         # a cache that cannot be written is only slower


def catalog(dirs=None, use_cache=None):
    """[Face] of every TrueType font under `dirs` (default: the system's), found once per process.  For the system's
    fonts the answers are kept in a file (cache_path()): only fonts that are new or changed are read again."""
    system = dirs is None
    dirs = tuple(font_dirs() if system else dirs)
    if dirs in _cache:
        return _cache[dirs]
    use_cache = system if use_cache is None else use_cache
    cpath = cache_path()
    cached = _load_cache(cpath) if use_cache else {}
    known = cached.get("fonts", {})
    fresh, faces, seen, changed = {}, [], set(), False
    for d in dirs:
        for root, _subdirs, files in os.walk(d):
            for fn in sorted(files):
                if not fn.lower().endswith((".ttf", ".ttc")):
                    continue
                path = os.path.join(root, fn)
                key = fn.lower()
                if key in seen:
                    continue
                seen.add(key)
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                stamp = [int(st.st_mtime), st.st_size]
                old = known.get(path)
                if old and old[0] == stamp:
                    info = old[1]
                else:
                    info = ttfglyphs.read_names(path)
                    changed = True
                fresh[path] = [stamp, info]
                if info and info["family"]:
                    faces.append(Face(path, info["family"], info["style"] or "Regular", info["bold"], info["italic"]))
    if use_cache and (changed or set(fresh) != set(known)):
        _save_cache(cpath, {"version": 1, "fonts": fresh})
    _cache[dirs] = faces
    return faces


def families(dirs=None):
    return sorted(set(f.family for f in catalog(dirs)), key=lambda s: s.lower())


def _pick(faces, family_names, bold, italic, exact=True):
    """The face of the best matching family and style among `faces`, or None."""
    for entry in family_names:
        fam, want = (entry if isinstance(entry, tuple) else (entry, False))
        wb = bold or want is True
        wi = italic or want == "italic"
        low = fam.lower()
        mine = [f for f in faces if f.family.lower() == low] if exact else [f for f in faces if low in f.family.lower()]
        if not mine:
            continue
        # the closest style; among equals the plain, standard one (Arial's family also holds "Narrow" and "Black")
        best = max(mine, key=lambda f: (2 * (f.bold == wb) + (f.italic == wi), f.style.lower() in STANDARD_STYLES, -len(f.style)))
        face = Face(best.path, best.family, best.style, best.bold, best.italic)
        face.need_bold, face.need_italic = wb and not best.bold, wi and not best.italic
        return face
    return None


def resolve(spec, bold=False, italic=False, dirs=None):
    """The Face for a font name (see the module docstring)."""
    faces = catalog(dirs)
    tried = []
    for part in [p.strip() for p in str(spec).split(",") if p.strip()]:
        if os.path.isfile(os.path.expanduser(part)):
            path = os.path.expanduser(part)
            info = ttfglyphs.read_names(path)
            if not info:
                raise FontNotFound("'%s' is not a TrueType font (.ttf / .ttc with outlines)" % part)
            face = Face(path, info["family"] or os.path.basename(path), info["style"], info["bold"], info["italic"])
            face.need_bold, face.need_italic = bold and not info["bold"], italic and not info["italic"]
            return face
        key = part.lower()
        tried.append(part)
        if key in ALIASES:
            face = _pick(faces, ALIASES[key], bold, italic)
            if face is None and faces:                                    # a generic always gets some font
                face = _pick(faces, [f.family for f in faces[:1]], bold, italic)
        else:
            face = _pick(faces, [part], bold, italic) or _pick(faces, [part], bold, italic, exact=False)
        if face is not None:
            return face
    fams = families(dirs)
    raise FontNotFound("no font '%s' (installed: %s%s)" % (", ".join(tried) or str(spec), ", ".join(fams[:25]),
                                                          ", ..." if len(fams) > 25 else "") if fams else
                       "no font '%s', and no TrueType fonts were found" % (", ".join(tried) or str(spec)))


def find(spec, bold=False, italic=False, dirs=None):
    return resolve(spec, bold, italic, dirs).path


def default(bold=False, italic=False, dirs=None):
    """The font used when none is asked for: a sans."""
    return resolve("sans", bold, italic, dirs)
