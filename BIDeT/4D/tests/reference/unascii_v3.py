# FROZEN REFERENCE: unascii 0.2 as of 2026-10-07 (with that day's two bug fixes: NUL in CP437 input, and the
# dangling SIXEL repeat count).  The oracle the 4D tests compare bifin | bifout against.  Do not edit it or
# import it from anything but tests; ../../../unascii is legacy and may go, this copy keeps the tests honest.
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
unascii - turn ASCII / ANSI / Unicode terminal art back into a line drawing.

ASCII art takes a picture and turns it into printable characters; this goes the other
way.  The result is a clean black-on-white (or any colour) PNG, or SIXEL graphics for
the terminal, and it feeds bidet3d:   unascii cow.txt -o - | bidet3d

Two modes, picked automatically per input (-m lineart / -m ansi-block to force one):

  lineart     a line drawing.  Three methods, picked by what the art is made of (-m line, tone,
              mix to force one):
      line    hand-drawn line art (cowsay, figlet, boxes: / \\ | _ - ( ) ^ ' . ,): the characters
              are read as pen strokes.  Stroke ends that meet are joined into continuous,
              spline-smoothed lines, so  _.-'--'-._  becomes one curve, not a row of marks.
      tone    picture-converted art (jp2a, chafa; ramps like  .:-=+*#%@): the characters are read
              as ink density; the picture they were squinted from is recovered and outlined.
      mix     both: strokes for the line characters, outlines for dense fill characters.
  ansi-block  art made of blocks and graphic characters (DOS .ANS, chafa half blocks, braille):
              the coloured picture it is, drawn crisp with exact blocks, blended shade
              characters and the original ANSI colours.

ANSI colours are kept throughout (-m lineart draws the lines in them; --mono turns it off).

Written for old libraries as well as new: Python 3.7+, Pillow 5.4+, numpy 1.16+.
"""

import argparse
import io
import math
import os
import re
import sys
import unicodedata

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

VERSION = "0.2"


# --------------------------------------------------------------------------
# Reading: text, ANSI escapes (colours, cursor movement), SAUCE, CP437
# --------------------------------------------------------------------------
_ANSI16 = [(0, 0, 0), (205, 0, 0), (0, 205, 0), (205, 205, 0), (0, 0, 238), (205, 0, 205),
           (0, 205, 205), (229, 229, 229), (127, 127, 127), (255, 0, 0), (0, 255, 0),
           (255, 255, 0), (92, 92, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255)]


# The 16 colours of a VGA text screen, in ANSI order (1 = red, 3 = yellow, which is brown, 4 = blue ...),
# as DOS .ANS art and DOSBox show them: light red is coral, "white" is light grey.
VGA16 = [(0, 0, 0), (170, 0, 0), (0, 170, 0), (170, 85, 0), (0, 0, 170), (170, 0, 170), (0, 170, 170),
         (170, 170, 170), (85, 85, 85), (255, 85, 85), (85, 255, 85), (255, 255, 85), (85, 85, 255),
         (255, 85, 255), (85, 255, 255), (255, 255, 255)]


def xterm_color(n):
    """Colour of palette entry n (0-255) as an (r, g, b) tuple."""
    if n < 16:
        return _ANSI16[n]
    if n < 232:
        n -= 16
        lv = (0, 95, 135, 175, 215, 255)
        return (lv[n // 36], lv[(n // 6) % 6], lv[n % 6])
    g = 8 + 10 * (n - 232)
    return (g, g, g)


CP437_GLYPHS = dict(zip(range(1, 32), "☺☻♥♦♣♠•◘○◙♂♀"
                                      "♪♫☼►◄↕‼¶§▬↨↑"
                                      "↓→←∟↔▲▼"))
_REAL_CONTROLS = (7, 8, 9, 10, 13, 26, 27)       # the other codes below 32 are pictures in a DOS .ANS file

# DEC special graphics (ESC ( 0): the line-drawing set that ncurses and VT100 art use
DEC_GRAPHICS = {"`": "◆", "a": "▒", "f": "°", "g": "±", "h": "▒", "i": "☃",
                "j": "┘", "k": "┐", "l": "┌", "m": "└", "n": "┼", "o": "⎺",
                "p": "⎻", "q": "─", "r": "⎼", "s": "⎽", "t": "├", "u": "┤",
                "v": "┴", "w": "┬", "x": "│", "y": "≤", "z": "≥", "{": "π",
                "|": "≠", "}": "£", "~": "·", "0": "█"}


def decode2(data, encoding=None):
    """bytes -> (str, encoding used).  UTF-8 if it is, else CP437 (the old DOS .ANS art).  A
    SAUCE record and the Ctrl-Z in front of it are dropped."""
    if isinstance(data, str):
        return data, "utf-8"
    i = data.rfind(b"SAUCE00")
    if i > 0 and data[i - 1:i] == b"\x1a":
        data = data[:i - 1]
    data = data.rstrip(b"\x1a")
    if encoding:
        return data.decode(encoding, "replace"), encoding.lower().replace("-", "")
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("cp437", "replace"), "cp437"


def decode(data, encoding=None):
    return decode2(data, encoding)[0]


class Grid(object):
    """The art as a rectangle of cells: ch[y][x] is one character, fg/bg[y][x] its colours
    ((r, g, b), 'fgdef' / 'bgdef' for reverse video, or None for the terminal default)."""
    def __init__(self, ch, fg, bg, vga=False):
        self.ch, self.fg, self.bg = ch, fg, bg
        self.vga = vga                    # DOS art: VGA colours, light grey default text
        self.rows = len(ch)
        self.cols = len(ch[0]) if ch else 0

    def has_color(self):
        """Does the art use colour at all (an explicit colour that is not just black)?"""
        return any(c is not None and c != (0, 0, 0) for row in self.fg + self.bg for c in row)


_CSI = re.compile(r"\x1b\[([0-9;:?<=>]*)([ -/]*)([@-~])")
_OSC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_STR = re.compile(r"\x1b[P^_X][^\x1b]*(?:\x1b\\)?")
MAX_CELLS = 4000000


class _Term(object):
    """Enough of a VT100/xterm to replay art and screen dumps: a screen of `rows` lines that
    scrolls into a history (so a long picture keeps every line), cursor addressing, scroll
    regions, erase / insert / delete, SGR colours, save / restore cursor, the DEC line-drawing
    set.  Cells are kept as {(line, column): (char, fg, bg)}."""
    def __init__(self, rows, cols, tabs, glyphs):
        self.rows, self.wrap, self.tabs, self.glyphs = max(1, rows), cols, tabs, glyphs
        self.maxx = cols if cols else 1000
        self.cells = {}
        self.top = self.x = self.y = 0
        self.r0, self.r1 = 0, self.rows - 1
        self.pending = False
        self.fg = self.bg = self.fg_idx = None
        self.bold = self.rev = False
        self.g, self.shift = ["B", "B"], 0
        self.saved = None
        self.save()

    def col(self, n):
        """Palette entry n; the first 16 are the VGA colours for DOS art, xterm's otherwise."""
        return VGA16[n] if self.glyphs and n < 16 else xterm_color(n)

    # -- state -----------------------------------------------------------
    def save(self):
        self.saved = (self.x, self.y, self.fg, self.bg, self.fg_idx, self.bold, self.rev, list(self.g), self.shift)

    def restore(self):
        if self.saved:
            (self.x, self.y, self.fg, self.bg, self.fg_idx, self.bold, self.rev, g, self.shift) = self.saved
            self.g = list(g)
            self.pending = False

    def colours(self):
        f, b = self.fg, self.bg
        if f is None and self.fg_idx is not None:
            f = self.col(self.fg_idx + 8 if self.bold and self.fg_idx < 8 else self.fg_idx)
        if self.rev:
            f, b = (b if b is not None else "bgdef"), (f if f is not None else "fgdef")
        return f, b

    # -- cells -----------------------------------------------------------
    def store(self, y, x, c, f, b):
        if c == " " and b is None:
            self.cells.pop((y, x), None)
        else:
            self.cells[(y, x)] = (c, f, b)

    def blank(self, y, x0, x1):
        """Erase columns x0..x1-1 of screen line y.  Erased cells take the current background."""
        b = self.colours()[1]
        b = None if b == (0, 0, 0) else b
        for x in range(x0, x1):
            self.store(self.top + y, x, " ", None, b)

    def shift_rows(self, a0, a1, delta):
        """Move the lines a0..a1 (absolute) by delta (positive = down); what is pushed out is lost."""
        keys = [k for k in self.cells if a0 <= k[0] <= a1]
        moved = [((k[0] + delta, k[1]), self.cells.pop(k)) for k in keys]
        for (y, x), v in moved:
            if a0 <= y <= a1:
                self.cells[(y, x)] = v

    def scroll(self, n, up=True):
        full = self.r0 == 0 and self.r1 == self.rows - 1
        n = min(n, self.r1 - self.r0 + 1)
        if up:
            if full:
                self.top += n
            else:
                self.shift_rows(self.top + self.r0, self.top + self.r1, -n)
        else:
            self.shift_rows(self.top + self.r0, self.top + self.r1, n)

    def lf(self):
        if self.y == self.r1:
            self.scroll(1)
        else:
            self.y = min(self.y + 1, self.rows - 1)
        self.pending = False

    def ri(self):
        if self.y == self.r0:
            self.scroll(1, up=False)
        else:
            self.y = max(0, self.y - 1)

    # -- printing --------------------------------------------------------
    def put(self, c):
        if self.pending and self.wrap:
            self.x = 0
            self.lf()
        self.pending = False
        if unicodedata.combining(c):
            return
        f, b = self.colours()
        self.store(self.top + self.y, self.x, c, f, b)
        w = 2 if unicodedata.east_asian_width(c) in "WF" else 1
        if self.wrap and self.x + w >= self.wrap:
            self.x = self.wrap - 1
            self.pending = True
        else:
            self.x = min(self.x + w, self.maxx)

    # -- sequences -------------------------------------------------------
    def sgr(self, nums):
        if not nums:
            nums = [0]
        i = 0
        while i < len(nums):
            v = nums[i]
            if v == 0:
                self.fg = self.bg = self.fg_idx = None
                self.bold = self.rev = False
            elif v == 1:
                self.bold = True
            elif v == 22:
                self.bold = False
            elif v == 7:
                self.rev = True
            elif v == 27:
                self.rev = False
            elif 30 <= v <= 37:
                self.fg_idx, self.fg = v - 30, None
            elif 90 <= v <= 97:
                self.fg_idx, self.fg = v - 90 + 8, None
            elif v == 39:
                self.fg = self.fg_idx = None
            elif 40 <= v <= 47:
                self.bg = self.col(v - 40)
            elif 100 <= v <= 107:
                self.bg = self.col(v - 100 + 8)
            elif v == 49:
                self.bg = None
            elif v in (38, 48):
                col = None
                if i + 2 < len(nums) and nums[i + 1] == 5:
                    col = self.col(min(255, nums[i + 2]))
                    i += 2
                elif i + 4 < len(nums) and nums[i + 1] == 2:
                    col = tuple(min(255, k) for k in nums[i + 2:i + 5])
                    i += 4
                if v == 38:
                    self.fg, self.fg_idx = col, None
                else:
                    self.bg = col
            i += 1

    def csi(self, args, fin):
        nums = [int(a) if a.isdigit() else 0 for a in args.replace(":", ";").split(";")] if args else []
        one = nums[0] if nums and nums[0] else 1
        if fin == "m":
            self.sgr(nums)
            return
        self.pending = False
        if fin == "A":
            self.y = max(0, self.y - one)
        elif fin in "Be":
            self.y = min(self.rows - 1, self.y + one)
        elif fin in "Ca":
            self.x = min(self.maxx - 1, self.x + one)
        elif fin == "D":
            self.x = max(0, self.x - one)
        elif fin == "E":
            self.y, self.x = min(self.rows - 1, self.y + one), 0
        elif fin == "F":
            self.y, self.x = max(0, self.y - one), 0
        elif fin in "G`":
            self.x = min(self.maxx - 1, one - 1)
        elif fin == "d":
            self.y = min(self.rows - 1, one - 1)
        elif fin in "Hf":
            self.y = min(self.rows - 1, max(0, (nums[0] or 1) - 1)) if nums else 0
            self.x = min(self.maxx - 1, max(0, (nums[1] or 1) - 1)) if len(nums) > 1 else 0
        elif fin == "J":
            n = nums[0] if nums else 0
            width = self.wrap or 80
            if n == 0:
                self.blank(self.y, self.x, max(width, self.x))
                for y in range(self.y + 1, self.rows):
                    self.blank(y, 0, width)
            elif n == 1:
                for y in range(0, self.y):
                    self.blank(y, 0, width)
                self.blank(self.y, 0, self.x + 1)
            else:
                for k in [k for k in self.cells if self.top <= k[0] < self.top + self.rows]:
                    del self.cells[k]
                if self.colours()[1] not in (None, (0, 0, 0)):
                    for y in range(self.rows):
                        self.blank(y, 0, width)
        elif fin == "K":
            n = nums[0] if nums else 0
            width = max(self.wrap or 80, self.x + 1)
            if n == 0:
                self.blank(self.y, self.x, width)
            elif n == 1:
                self.blank(self.y, 0, self.x + 1)
            else:
                self.blank(self.y, 0, width)
        elif fin == "X":
            self.blank(self.y, self.x, self.x + one)
        elif fin == "L" and self.r0 <= self.y <= self.r1:
            self.shift_rows(self.top + self.y, self.top + self.r1, min(one, self.r1 - self.y + 1))
        elif fin == "M" and self.r0 <= self.y <= self.r1:
            self.shift_rows(self.top + self.y, self.top + self.r1, -min(one, self.r1 - self.y + 1))
        elif fin == "@":
            row = self.top + self.y
            for k in sorted((k for k in self.cells if k[0] == row and k[1] >= self.x), reverse=True):
                self.cells[(row, k[1] + one)] = self.cells.pop(k)
        elif fin == "P":
            row = self.top + self.y
            for k in sorted(k for k in self.cells if k[0] == row and k[1] >= self.x):
                v = self.cells.pop(k)
                if k[1] >= self.x + one:
                    self.cells[(row, k[1] - one)] = v
        elif fin == "S" and len(nums) <= 1:
            self.scroll(one)
        elif fin == "T" and len(nums) <= 1:
            self.scroll(one, up=False)
        elif fin == "r":
            r0 = (nums[0] or 1) - 1 if nums else 0
            r1 = (nums[1] or self.rows) - 1 if len(nums) > 1 else self.rows - 1
            if 0 <= r0 < r1 < self.rows:
                self.r0, self.r1 = r0, r1
            self.x = self.y = 0
        elif fin == "s" and not nums:
            self.save()
        elif fin == "u":
            self.restore()

    def esc(self, c):
        """ESC followed by one character (the ones that stand alone)."""
        if c == "7":
            self.save()
        elif c == "8":
            self.restore()
        elif c == "M":
            self.ri()
        elif c == "D":
            self.lf()
        elif c == "E":
            self.x = 0
            self.lf()
        elif c == "c":
            self.__init__(self.rows, self.wrap, self.tabs, self.glyphs)

    def run(self, text):
        pos, n = 0, len(text)
        while pos < n:
            c = text[pos]
            if c == "\x1b":
                m = _CSI.match(text, pos)
                if m:
                    pos = m.end()
                    if m.group(1)[:1] not in ("?", "<", "=", ">") and not m.group(2):
                        self.csi(m.group(1), m.group(3))
                    continue
                m = _OSC.match(text, pos) or _STR.match(text, pos)
                if m:
                    pos = m.end()
                    continue
                nxt = text[pos + 1:pos + 2]
                if nxt in ("(", ")") and pos + 2 < n:           # designate a character set
                    self.g[0 if nxt == "(" else 1] = text[pos + 2]
                    pos += 3
                elif nxt in ("*", "+", "#", "%", " ") and pos + 2 < n:
                    pos += 3
                else:
                    self.esc(nxt)
                    pos += 2
                continue
            pos += 1
            o = ord(c)
            if c == "\n" or c == "\x0b" or c == "\x0c":
                self.x = 0
                self.lf()
            elif c == "\r":
                self.x, self.pending = 0, False
            elif c == "\t":
                self.x = min(self.maxx - 1, (self.x // self.tabs + 1) * self.tabs)
                self.pending = False
            elif c == "\b":
                self.x, self.pending = max(0, self.x - 1), False
            elif o in CP437_GLYPHS and self.glyphs and o not in _REAL_CONTROLS:     # (NUL has no picture: it was a KeyError)
                self.put(CP437_GLYPHS[o])
            elif c == "\x0e":
                self.shift = 1
            elif c == "\x0f":
                self.shift = 0
            elif o < 32 or o == 127:
                pass
            else:
                if self.g[self.shift] == "0":
                    c = DEC_GRAPHICS.get(c, c)
                elif c in " ⠀":
                    c = " "
                self.put(c)


def parse(text, cols=0, tabs=8, rows=24, glyphs=False):
    """Replay text on a terminal (see _Term) and return what is on it, history included, as a
    Grid.  cols: the wrap column (0 = lines never wrap); rows: the height of the screen that
    cursor addressing and scroll regions refer to; glyphs: codes below 32 are pictures (DOS .ANS)."""
    t = _Term(rows, cols, tabs, glyphs)
    t.run(text)
    cells = t.cells
    if not cells:
        return Grid([[" "]], [[None]], [[None]])
    y0 = min(k[0] for k in cells)
    nrows, width = max(k[0] for k in cells) - y0 + 1, max(k[1] for k in cells) + 1
    if nrows * width > MAX_CELLS:
        raise ValueError("the art is %d x %d characters: too big (limit %d cells)" % (width, nrows, MAX_CELLS))
    ch = [[" "] * width for _ in range(nrows)]
    fgs = [[None] * width for _ in range(nrows)]
    bgs = [[None] * width for _ in range(nrows)]
    for (yy, xx), (c, f, b) in cells.items():
        ch[yy - y0][xx], fgs[yy - y0][xx], bgs[yy - y0][xx] = c, f, b
    return Grid(ch, fgs, bgs, glyphs)


# --------------------------------------------------------------------------
# What kind of character is it?
# --------------------------------------------------------------------------
STRONG = set("/\\|_()[]{}<>^'`\u00b4\"\u00af\u203e!")        # clearly pen strokes
WEAK = set("-.,:;=~+*oO0vV")                                  # strokes in line art, ramp in tone art
DENSE = set("#%@&$8\u2588\u2593\u2592\u2591")                 # fill characters
LETTERS_OK = True


def is_block(c):
    return "\u2580" <= c <= "\u259f"


def is_braille(c):
    return "\u2800" <= c <= "\u28ff"


def is_box(c):
    return "\u2500" <= c <= "\u257f"


_SHAPEY = set("oOvV0")                       # letters that are also drawing characters
_TEXTY = set(".,:;'!-?")                     # punctuation that belongs to text when it touches a word


def shade_cells(grid, chars):
    """Cells that are shading rather than letters or strokes: a run of two or more of one of
    `chars` (default X), as in the filled regions of cowsay's ghostbusters, plus any such
    character standing directly above or below one."""
    if not chars:
        return None
    base = [[c in chars for c in row] for row in grid.ch]
    run = [[base[y][x] and ((x > 0 and base[y][x - 1]) or (x + 1 < grid.cols and base[y][x + 1]))
            for x in range(grid.cols)] for y in range(grid.rows)]
    out = [row[:] for row in run]
    for y in range(grid.rows):
        for x in range(grid.cols):
            if base[y][x] and not run[y][x] and ((y > 0 and run[y - 1][x]) or (y + 1 < grid.rows and run[y + 1][x])):
                out[y][x] = True
    return out if any(any(r) for r in out) else None


def word_cells(grid, skip=None):
    """Which cells are text rather than drawing?  A run of letters/digits is a word, and is
    drawn from the font, if it holds any letter that is not also a drawing character
    (o O v V 0): 'Moo' is text, '(oo)' is eyes.  Punctuation touching a word is text too.
    Cells in `skip` (shading) do not count as letters."""
    text = [[False] * grid.cols for _ in range(grid.rows)]
    for y, row in enumerate(grid.ch):
        x = 0

        def letter(k):
            return row[k].isalnum() and not (skip and skip[y][k])
        while x < grid.cols:
            if not letter(x):
                x += 1
                continue
            e = x
            while e < grid.cols and letter(e):
                e += 1
            if any(c not in _SHAPEY for c in row[x:e]):
                for k in range(x, e):
                    text[y][k] = True
                for k in (x - 1, e):
                    if 0 <= k < grid.cols and row[k] in _TEXTY:
                        text[y][k] = True
            x = e
    return text


_SIDES = set("<>/\\|()")


def bubble_bottoms(grid):
    """The bottom border of cowsay / cowthink speech bubbles, as a set of (row, col).

        _______        a run of _ ...
       < hello >       ... with side characters (< > / \\ | ( )) beside every row ...
        -------        ... and a run of - of the same width below.

    Drawn normally, the - floats at mid-height, away from the sides.  The caller lifts these
    to the row boundary, the mirror image of where the _ sits on top, so the bubble closes."""
    found = set()
    ch = grid.ch
    for y in range(2, grid.rows):
        x = 0
        while x < grid.cols:
            if ch[y][x] != "-":
                x += 1
                continue
            e = x
            while e < grid.cols and ch[y][e] == "-":
                e += 1
            a, b = x, e - 1                                       # the run, columns a..b
            x = e
            if b - a < 2 or a == 0 or b + 1 >= grid.cols:
                continue
            if ch[y][a - 1] != " " or ch[y][b + 1] != " ":
                continue
            r = y - 1                                             # side characters, going up
            while r >= 1 and ch[r][a - 1] in _SIDES and ch[r][b + 1] in _SIDES:
                r -= 1
            if r == y - 1 or r < 0:
                continue
            top = ch[r][a:b + 1]                                  # row r must be the _ border
            if top.count("_") >= 0.8 * len(top) and ch[r][a - 1] == " " and ch[r][b + 1] == " ":
                found.update((y, k) for k in range(a, b + 1))
    return found


def classify(grid, skip=None):
    """Pick block / line / tone / mix for this art, with the numbers behind the choice.  Cells in
    `skip` (shading) are left out of it.  Art made mostly of blocks, braille and coloured
    backgrounds is "block" (rendered as the picture it is); the rest is line drawing."""
    n = line = pix = dense = 0
    ys, xs = [], []
    for y, row in enumerate(grid.ch):
        for x, c in enumerate(row):
            if (c == " " and grid.bg[y][x] is None) or (skip and skip[y][x]):
                continue
            n += 1
            ys.append(y)
            xs.append(x)
            if c in STRONG or is_box(c):
                line += 1
            elif is_block(c) or is_braille(c) or grid.bg[y][x] is not None:
                pix += 1
            elif c in DENSE:
                dense += 1
    if not n:
        return "line", {}
    area = (max(ys) - min(ys) + 1) * (max(xs) - min(xs) + 1)
    st = {"cells": n, "fill": n / float(area), "strong": line / float(n),
          "pixel": pix / float(n), "dense": dense / float(n)}
    if st["pixel"] > 0.3:
        mode = "block"
    elif st["strong"] >= 0.45 and st["dense"] < 0.15:
        mode = "line"
    elif st["fill"] > 0.5 and st["strong"] < 0.25:
        mode = "tone"
    elif st["dense"] + st["pixel"] > 0.1:
        mode = "mix"
    else:
        mode = "line"
    return mode, st


# --------------------------------------------------------------------------
# Fonts and glyph coverage masks
# --------------------------------------------------------------------------
FONT_DIRS = ["C:/Windows/Fonts", "/cygdrive/c/Windows/Fonts", "/mnt/c/Windows/Fonts",
             "/usr/share/fonts", "/usr/local/share/fonts", "~/.fonts", "~/.local/share/fonts",
             "/System/Library/Fonts", "/Library/Fonts", "~/Library/Fonts"]
FONT_FILES = ["DejaVuSansMono.ttf", "consola.ttf", "LiberationMono-Regular.ttf", "Menlo.ttc",
              "FreeMono.ttf", "lucon.ttf", "cour.ttf", "UbuntuMono-R.ttf", "NotoSansMono-Regular.ttf"]


def find_font(override=None):
    if override:
        if os.path.isfile(override):
            return override
        sys.exit("unascii: font '%s' not found" % override)
    found = {}
    for d in FONT_DIRS:
        d = os.path.expanduser(d)
        if os.path.isdir(d):
            for root, _dirs, files in os.walk(d):
                for f in files:
                    found.setdefault(f.lower(), os.path.join(root, f))
    for f in FONT_FILES:
        if f.lower() in found:
            return found[f.lower()]
    return None


def _advance(font, s):
    try:
        return font.getlength(s)
    except AttributeError:
        return font.getsize(s)[0]


class Glyphs(object):
    """Coverage masks (float32, ch x cw, 1 = ink) for characters, cached.  Blocks and
    braille are computed exactly; everything else is rendered from a font."""
    def __init__(self, cw, ch, font_path=None):
        self.cw, self.ch = cw, ch
        self.cache = {}
        self.font = None
        self.S = 2
        path = find_font(font_path)
        if path:
            probe = ImageFont.truetype(path, 100)
            size = max(4, int(round(cw * self.S / _advance(probe, "M") * 100)))
            self.font = ImageFont.truetype(path, size)
            asc, desc = self.font.getmetrics()
            self.box = (int(math.ceil(_advance(self.font, "M"))), asc + desc)
        self.path = path

    def mask(self, c):
        m = self.cache.get(c)
        if m is None:
            m = self._make(c)
            self.cache[c] = m
        return m

    def _make(self, c):
        cw, ch = self.cw, self.ch
        m = np.zeros((ch, cw), np.float32)
        if c == " ":
            return m
        o = ord(c)
        if is_braille(c):
            bits = o - 0x2800
            pos = [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2), (0, 3), (1, 3)]
            for b, (cx, cy) in enumerate(pos):
                if bits & (1 << b):
                    m[cy * ch // 4:(cy + 1) * ch // 4, cx * cw // 2:(cx + 1) * cw // 2] = 1
            return m
        if is_block(c):
            h2, w2 = ch // 2, cw // 2
            if o == 0x2580:
                m[:h2] = 1
            elif 0x2581 <= o <= 0x2587:
                m[ch - int(round(ch * (o - 0x2580) / 8.0)):] = 1
            elif o == 0x2588:
                m[:] = 1
            elif 0x2589 <= o <= 0x258f:
                m[:, :int(round(cw * (0x2590 - o) / 8.0))] = 1
            elif o == 0x2590:
                m[:, w2:] = 1
            elif o in (0x2591, 0x2592, 0x2593):
                m[:] = (o - 0x2590) * 0.25
            elif o == 0x2594:
                m[:max(1, ch // 8)] = 1
            elif o == 0x2595:
                m[:, cw - max(1, cw // 8):] = 1
            else:
                quad = {0x2596: "L", 0x2597: "R", 0x2598: "l", 0x2599: "lLR", 0x259a: "lR",
                        0x259b: "lrL", 0x259c: "lrR", 0x259d: "r", 0x259e: "rL", 0x259f: "rLR"}[o]
                for q in quad:
                    ys = slice(0, h2) if q in "lr" else slice(h2, ch)
                    xs = slice(0, w2) if q in "lL" else slice(w2, cw)
                    m[ys, xs] = 1
            return m
        if self.font is None:
            return m
        W, H = self.box
        im = Image.new("L", (W, H), 0)
        ImageDraw.Draw(im).text((0, 0), c, font=self.font, fill=255)
        im = im.resize((cw, ch), Image.LANCZOS)
        return np.clip(np.asarray(im, np.float32) / 255.0, 0, 1)


# --------------------------------------------------------------------------
# Small image-processing helpers (numpy only)
# --------------------------------------------------------------------------
def _kernel(sigma):
    r = max(1, int(math.ceil(3.0 * sigma)))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / float(sigma)) ** 2)
    return (k / k.sum()).astype(np.float32), r


def _box_sizes(sigma, n=3):
    """Widths (odd) of n box filters whose product approximates a Gaussian of `sigma`."""
    ideal = math.sqrt(12.0 * sigma * sigma / n + 1.0)
    wl = int(math.floor(ideal))
    if wl % 2 == 0:
        wl -= 1
    wl = max(1, wl)
    m = int(round((12.0 * sigma * sigma - n * wl * wl - 4.0 * n * wl - 3.0 * n) / (-4.0 * wl - 4.0)))
    return [wl if i < m else wl + 2 for i in range(n)]


def _box_pass(a, width, axis):
    """Moving average of `width` (odd) along axis, edges replicated: one cumulative sum, so
    the cost does not depend on the width."""
    r = width // 2
    if r == 0:
        return a
    pad = [(0, 0), (0, 0)]
    pad[axis] = (r, r)
    c = np.cumsum(np.pad(a, pad, mode="edge"), axis=axis, dtype=np.float64)
    n = a.shape[axis]
    if axis == 1:
        hi, lo = c[:, width - 1:width - 1 + n], np.concatenate([np.zeros((c.shape[0], 1)), c[:, :n - 1]], 1)
    else:
        hi, lo = c[width - 1:width - 1 + n], np.concatenate([np.zeros((1, c.shape[1])), c[:n - 1]], 0)
    return ((hi - lo) / width).astype(np.float32)


def blur(a, sx, sy=None):
    """Gaussian blur, separable, edge-replicating.  sigma in pixels per axis.  Small sigmas
    are convolved exactly; from 6 px up three box filters stand in for the Gaussian (within a
    percent or two of it, and no slower for a wide blur than a narrow one)."""
    sy = sx if sy is None else sy
    a = a.astype(np.float32)
    for axis, s in ((1, sx), (0, sy)):
        if s < 0.3:
            continue
        if s >= 6.0:
            for width in _box_sizes(s):
                a = _box_pass(a, width, axis)
            continue
        k, r = _kernel(s)
        pad = [(0, 0), (0, 0)]
        pad[axis] = (r, r)
        p = np.pad(a, pad, mode="edge")
        n = a.shape[axis]
        out = np.zeros_like(a)
        for i, w in enumerate(k):
            out += w * (p[:, i:i + n] if axis == 1 else p[i:i + n, :])
        a = out
    return a


def smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


# --------------------------------------------------------------------------
# Tone: characters as ink density -> the picture -> outlines
# --------------------------------------------------------------------------
def lum(c):
    return (0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]) / 255.0


def pitch_of(grid, cw, ch):
    """Size in pixels of the smallest 'dot' this art is made of: a text cell, or half of
    one for half-blocks / quadrants, a quarter for braille."""
    k = {"cell": 0, "half": 0, "quad": 0, "braille": 0}
    for row in grid.ch:
        for c in row:
            o = ord(c)
            if is_braille(c) and o != 0x2800:
                k["braille"] += 1
            elif o in (0x2580, 0x2584, 0x258c, 0x2590):
                k["half"] += 1
            elif 0x2596 <= o <= 0x259f:
                k["quad"] += 1
            elif c != " ":
                k["cell"] += 1
    best = max(k, key=lambda a: k[a])
    return {"cell": (cw, ch), "half": (cw, ch / 2.0), "quad": (cw / 2.0, ch / 2.0),
            "braille": (cw / 2.0, ch / 4.0)}[best]


def _cell_colours(grid, dark):
    """Foreground and background of every cell, float arrays (rows, cols, 3) in 0..1.  The
    terminal defaults are black on white (white on black if dark); reverse-video markers
    resolve to those."""
    paper = (0.0, 0.0, 0.0) if dark else (1.0, 1.0, 1.0)
    ink = tuple(1.0 - v for v in paper)

    def rgb(v, default):
        if v is None:
            return default
        if isinstance(v, str):
            return ink if v == "fgdef" else paper
        return (v[0] / 255.0, v[1] / 255.0, v[2] / 255.0)
    fg = [[rgb(f, ink) for f in row] for row in grid.fg]
    bg = [[rgb(b, paper) for b in row] for row in grid.bg]
    return np.array(fg, np.float32), np.array(bg, np.float32)


def dot_field(grid, glyphs, only, dark, kx, ky):
    """The picture the art stands for, at the resolution of its dots: float (rows*ky, cols*kx, 3)
    in 0..1.  Each character's coverage is averaged over its kx x ky dots (1x1 for text, 1x2 for
    half blocks, 2x4 for braille) and mixes the cell's foreground into its background.
    Characters not accepted by `only` are left blank."""
    rows, cols = grid.rows, grid.cols
    uniq, pooled = {}, {}
    idx = np.zeros((rows, cols), np.int32)
    for y in range(rows):
        row = grid.ch[y]
        for x in range(cols):
            c = row[x]
            if only is not None and not only(c):
                c = " "
            idx[y, x] = uniq.setdefault(c, len(uniq))
    masks = np.zeros((len(uniq), ky, kx), np.float32)
    for c, i in uniq.items():
        m = glyphs.mask(c)
        masks[i] = m.reshape(ky, glyphs.ch // ky, kx, glyphs.cw // kx).mean(axis=(1, 3))
    M = masks[idx].transpose(0, 2, 1, 3).reshape(rows * ky, cols * kx)
    fg, bg = _cell_colours(grid, dark)
    fg = np.repeat(np.repeat(fg, ky, 0), kx, 1)
    bg = np.repeat(np.repeat(bg, ky, 0), kx, 1)
    return bg + (fg - bg) * M[..., None]


def _upsample(pooled, ix, iy):
    """Spread dot values back out smoothly (bicubic), ix x iy pixels per dot."""
    ny, nx = pooled.shape
    p = np.pad(pooled.astype(np.float32), 1, mode="edge")
    up = Image.fromarray(p).resize(((nx + 2) * ix, (ny + 2) * iy), Image.BICUBIC)
    return np.asarray(up, np.float32)[iy:iy + ny * iy, ix:ix + nx * ix]


def _resize(a, w, h):
    """A float array scaled (bicubic) to w x h."""
    return np.asarray(Image.fromarray(np.ascontiguousarray(a, np.float32)).resize((w, h), Image.BICUBIC), np.float32)


# The fields that outlines are made from are smooth: they come from one value per dot, blurred over
# many pixels.  So they are computed at about 4 pixels per dot (lx x ly) and scaled up to full size
# only afterwards; the sub-pixel line position is then found on the full-size signed field.  This is
# ten times less work than blurring a full-size picture.
def _dog_fields(f, lx, ly, ix, iy, scale):
    """At working resolution: the difference of Gaussians of f and the edge strength (tone change
    per dot, from the gradient)."""
    sx, sy = scale * lx, scale * ly
    g1 = blur(f, sx, sy)
    g2 = blur(f, 1.6 * sx, 1.6 * sy)
    gy, gx = np.gradient(g1)
    strength = np.hypot(gx * (lx / float(ix)), gy * (ly / float(iy))) * (0.5 * (ix + iy))
    return g1 - g2, strength


def _line_ink(dog, strength, width, edge):
    """Full size: lines `width` pixels wide along the zero crossings of dog, where the edge is
    at least `edge` high."""
    gy, gx = np.gradient(dog)
    dist = np.abs(dog) / (np.hypot(gx, gy) + 1e-6)               # px to the zero crossing
    return np.clip(0.5 * width - dist + 0.5, 0.0, 1.0) * \
        np.clip((strength - 0.9 * edge) / (0.2 * edge), 0.0, 1.0)


def _contour_fields(f, lx, ly, ix, iy, edge):
    """At working resolution: the gradient size of f, and where the shading is gentle enough for
    contour lines (at step edges they would double the outline)."""
    gy, gx = np.gradient(blur(f, 0.5 * lx, 0.5 * ly))
    gm = np.hypot(gx * (lx / float(ix)), gy * (ly / float(iy)))
    grad = gm * (0.5 * (ix + iy))
    weak = np.clip((grad - 0.015) / 0.02, 0.0, 1.0) * np.clip((0.7 * edge - grad) / (0.3 * edge), 0.0, 1.0)
    return gm, weak


def _contour_ink(f, gm, weak, width, levels):
    out = np.zeros_like(f)
    for k in range(1, levels + 1):
        dist = np.abs(f - k / (levels + 1.0)) / (gm + 1e-6)
        out = np.maximum(out, np.clip(0.4 * width - dist + 0.5, 0.0, 1.0) * weak)
    return out


def tone_lines(P, ix, iy, width, o, color):
    """Line drawing of the picture P (float (ny, nx, 3), 0..1) whose dots are ix x iy pixels.
    Returns (ink, sparse): ink is float (ny*iy, nx*ix), 1 = line; sparse is None, or when color
    is set (ys, xs, rgb 0..255) giving the colour of every line pixel.

    The picture is spread back out smoothly (undoing the halftone) and outlined.  A coloured
    picture is outlined per colour channel, so an edge between two hues of the same brightness
    still gets a line.  The colour of a line is the picture's own, weighted towards the
    colourful side of an edge so a coloured object keeps its colour against a dark ground."""
    ny, nx = P.shape[:2]
    lx, ly = min(ix, 4), min(iy, 4)                              # working resolution, px per dot
    D = 1.0 - P
    if o.invert:
        D = 1.0 - D
    Dl = 0.299 * D[..., 0] + 0.587 * D[..., 1] + 0.114 * D[..., 2]
    lo, hi = float(np.percentile(Dl, 2)), float(np.percentile(Dl, 98))
    span = (hi - lo) if hi - lo >= 0.04 else 1.0                 # a flat picture is not stretched
    colourful = (P.max(2) - P.min(2)).max() > 0.12
    sm = 0.7 if o.smooth is None else o.smooth

    def up(a):
        return a if (lx, ly) == (ix, iy) else _resize(a, nx * ix, ny * iy)

    def field(chan):
        f = blur(_upsample(chan, lx, ly), sm * lx, sm * ly)
        return np.clip((f - lo) / span, 0.0, 1.0)
    fl = field(Dl)
    chans = [D[..., k] for k in range(3)] if colourful else [Dl]
    ink = np.zeros((ny * iy, nx * ix), np.float32)
    for chan in chans:
        dog, strength = _dog_fields(fl if chan is Dl else field(chan), lx, ly, ix, iy, o.scale)
        ink = np.maximum(ink, _line_ink(up(dog), np.maximum(up(strength), 0.0), width, o.detail))
    if o.levels > 0:
        gm, weak = _contour_fields(fl, lx, ly, ix, iy, o.detail)
        ink = np.maximum(ink, _contour_ink(up(fl), np.maximum(up(gm), 0.0), np.clip(up(weak), 0.0, 1.0),
                                           width, o.levels))
    if not color:
        return ink.astype(np.float32), None
    chroma = P.max(2) - P.min(2)
    w = (chroma + 0.03) ** 2
    den = blur(w, 1.0, 1.0)
    C = np.dstack([blur(P[..., k] * w, 1.0, 1.0) / den for k in range(3)])
    ys, xs = np.nonzero(ink > 0.02)
    fy = np.clip((ys + 0.5) / iy - 0.5, 0, max(C.shape[0] - 1, 0))
    fx = np.clip((xs + 0.5) / ix - 0.5, 0, max(C.shape[1] - 1, 0))
    y0, x0 = fy.astype(np.int64), fx.astype(np.int64)
    y1, x1 = np.minimum(y0 + 1, C.shape[0] - 1), np.minimum(x0 + 1, C.shape[1] - 1)
    wy, wx = (fy - y0)[:, None], (fx - x0)[:, None]
    rgb = ((C[y0, x0] * (1 - wx) + C[y0, x1] * wx) * (1 - wy) +
           (C[y1, x0] * (1 - wx) + C[y1, x1] * wx) * wy) * 255.0
    return ink.astype(np.float32), (ys, xs, rgb)


# --------------------------------------------------------------------------
# Colour: making ANSI colours fit the page
# --------------------------------------------------------------------------
def legible(rgb, ink, paper):
    """Adjust colours (float array (..., 3), 0..255) to be seen on `paper`: greys and whites,
    which in a terminal are just 'the text colour', become `ink`; colours too bright for a
    light page are darkened (yellow stays yellow, as olive), too dark for a dark page lightened."""
    rgb = np.asarray(rgb, np.float32)
    mx, mn = rgb.max(-1), rgb.min(-1)
    sat = (mx - mn) / np.maximum(mx, 1.0)
    Y = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    if lum(paper) > 0.5:
        out = rgb * np.where(Y > 148.0, 148.0 / np.maximum(Y, 1.0), 1.0)[..., None]
    else:
        t = np.clip((115.0 - Y) / np.maximum(255.0 - Y, 1.0), 0.0, 1.0)[..., None]
        out = rgb + (255.0 - rgb) * t
    return np.where((sat < 0.15)[..., None], np.array(ink, np.float32), out)


def _shifted(a, dy, dx):
    out = np.zeros_like(a)
    h, w = a.shape[:2]
    out[max(0, dy):h + min(0, dy), max(0, dx):w + min(0, dx)] = a[max(0, -dy):h - max(0, dy), max(0, -dx):w - max(0, dx)]
    return out


def cell_color_map(grid, ink, paper):
    """The colour for strokes drawn in each cell, uint8 (rows, cols, 3): the cell's foreground
    colour made legible.  Blank cells take their neighbours' colour, so a curve that wanders
    into one does not change colour."""
    rows, cols = grid.rows, grid.cols
    col = np.zeros((rows, cols, 3), np.float32)
    known = np.zeros((rows, cols), bool)
    for y in range(rows):
        for x in range(cols):
            if grid.ch[y][x] == " ":
                continue
            f = grid.fg[y][x]
            col[y, x] = ink if f is None or isinstance(f, str) else f
            known[y, x] = True
    for _ in range(3):
        if known.all():
            break
        new, new_known = col.copy(), known.copy()
        for dy, dx in ((0, -1), (0, 1), (-1, 0), (1, 0), (-1, -1), (-1, 1), (1, -1), (1, 1)):
            sk, sc = _shifted(known, dy, dx), _shifted(col, dy, dx)
            take = sk & ~new_known
            new[take], new_known[take] = sc[take], True
        col, known = new, new_known
    col[~known] = ink
    return np.clip(legible(col, ink, paper) + 0.5, 0, 255).astype(np.uint8)


# --------------------------------------------------------------------------
# Line: characters as pen strokes
# --------------------------------------------------------------------------
def _arc(u_end, bulge, n=9):
    return [(u_end - bulge * math.sin(math.pi * i / (n - 1.0)), i / (n - 1.0)) for i in range(n)]


def _wave():
    return [(i / 8.0, 0.52 - 0.13 * math.sin(2 * math.pi * i / 8.0)) for i in range(9)]


# glyph -> list of ("p", [(u, v), ...], link) polyline, ("d", u, v) dot, ("r", u, v, rx, ry) ring.
# u, v run 0..1 across the cell (v downwards); link = its ends may join other strokes.
GEOM = {
    "/": [("p", [(0, 1), (1, 0)], 1)],
    "\\": [("p", [(0, 0), (1, 1)], 1)],
    "|": [("p", [(0.5, 0), (0.5, 1)], 1)],
    "_": [("p", [(0, 0.93), (1, 0.93)], 1)],
    "\u00af": [("p", [(0, 0.07), (1, 0.07)], 1)],
    "\u203e": [("p", [(0, 0.07), (1, 0.07)], 1)],
    "-": [("p", [(0, 0.5), (1, 0.5)], 1)],
    "=": [("p", [(0, 0.38), (1, 0.38)], 1), ("p", [(0, 0.62), (1, 0.62)], 1)],
    "~": [("p", _wave(), 1)],
    "^": [("p", [(0.08, 0.62), (0.5, 0.1), (0.92, 0.62)], 1)],
    "v": [("p", [(0.08, 0.38), (0.5, 0.9), (0.92, 0.38)], 1)],
    "V": [("p", [(0.0, 0.06), (0.5, 0.95), (1.0, 0.06)], 1)],
    "<": [("p", [(0.92, 0.2), (0.08, 0.5), (0.92, 0.8)], 1)],
    ">": [("p", [(0.08, 0.2), (0.92, 0.5), (0.08, 0.8)], 1)],
    "(": [("p", _arc(0.72, 0.42), 1)],
    ")": [("p", _arc(0.28, -0.42), 1)],
    "[": [("p", [(0.7, 0), (0.3, 0), (0.3, 1), (0.7, 1)], 1)],
    "]": [("p", [(0.3, 0), (0.7, 0), (0.7, 1), (0.3, 1)], 1)],
    "{": [("p", [(0.72, 0), (0.52, 0.08), (0.5, 0.4), (0.18, 0.5), (0.5, 0.6), (0.52, 0.92), (0.72, 1)], 1)],
    "}": [("p", [(0.28, 0), (0.48, 0.08), (0.5, 0.4), (0.82, 0.5), (0.5, 0.6), (0.48, 0.92), (0.28, 1)], 1)],
    "'": [("p", [(0.5, 0.04), (0.5, 0.34)], 1)],
    "`": [("p", [(0.3, 0.04), (0.62, 0.34)], 1)],
    "\u00b4": [("p", [(0.7, 0.04), (0.38, 0.34)], 1)],
    "\"": [("p", [(0.32, 0.04), (0.32, 0.32)], 0), ("p", [(0.68, 0.04), (0.68, 0.32)], 0)],
    ".": [("d", 0.5, 0.9, 1)],
    ",": [("p", [(0.58, 0.84), (0.42, 1.06)], 0)],
    ":": [("d", 0.5, 0.36), ("d", 0.5, 0.9)],
    ";": [("d", 0.5, 0.36), ("p", [(0.58, 0.84), (0.42, 1.06)], 0)],
    "!": [("p", [(0.5, 0.02), (0.5, 0.68)], 1), ("d", 0.5, 0.9)],
    "+": [("p", [(0.08, 0.5), (0.92, 0.5)], 1), ("p", [(0.5, 0.26), (0.5, 0.74)], 0)],
    "*": [("p", [(0.1, 0.4), (0.9, 0.4)], 1), ("p", [(0.5, 0.2), (0.5, 0.6)], 0),
          ("p", [(0.28, 0.27), (0.72, 0.53)], 0), ("p", [(0.28, 0.53), (0.72, 0.27)], 0)],
    "o": [("r", 0.5, 0.66, 0.3, 0.17)],
    "O": [("r", 0.5, 0.5, 0.42, 0.38)],
    "0": [("r", 0.5, 0.5, 0.42, 0.38)],
}


def box_arms(c):
    """Box-drawing character -> ({dir: 'LIGHT'|'HEAVY'|'DOUBLE'}, rounded), from its Unicode
    name; None if it is not an ordinary box piece."""
    try:
        name = unicodedata.name(c)
    except ValueError:
        return None
    if not name.startswith("BOX DRAWINGS "):
        return None
    words = name[13:].replace("DOUBLE DASH", "").replace("TRIPLE DASH", "") \
                     .replace("QUADRUPLE DASH", "").replace("DASH", "").split()
    if "DIAGONAL" in words:
        return None
    arc = "ARC" in words
    groups = [[]]
    for w in words:
        if w == "AND":
            groups.append([])
        else:
            groups[-1].append(w)
    arms, first = {}, None
    for g in groups:
        st = next((w for w in g if w in ("LIGHT", "HEAVY", "DOUBLE", "SINGLE")), None)
        if st is None:
            st = first or "LIGHT"
        else:
            first = first or st
        st = "LIGHT" if st == "SINGLE" else st
        for w in g:
            for k in {"UP": "u", "DOWN": "d", "LEFT": "l", "RIGHT": "r",
                      "VERTICAL": "ud", "HORIZONTAL": "lr"}.get(w, ""):
                arms[k] = st
    return (arms, arc) if arms else None


class Path(object):
    __slots__ = ("pts", "link", "wmul", "join")

    def __init__(self, pts, link=False, wmul=1.0):
        self.pts, self.link, self.wmul = pts, link, wmul
        self.join = [False] * len(pts)


def box_paths(arms, arc, x0, y0, cw, ch):
    cx, cy = x0 + cw / 2.0, y0 + ch / 2.0
    edge = {"u": (cx, y0), "d": (cx, y0 + ch), "l": (x0, cy), "r": (x0 + cw, cy)}
    if arc and len(arms) == 2:
        a, b = sorted(arms)
        pts = []
        for i in range(9):
            t = i / 8.0
            pts.append(((1 - t) ** 2 * edge[a][0] + 2 * t * (1 - t) * cx + t * t * edge[b][0],
                        (1 - t) ** 2 * edge[a][1] + 2 * t * (1 - t) * cy + t * t * edge[b][1]))
        return [Path(pts, False, 1.8 if "HEAVY" in arms.values() else 1.0)]
    dd = 0.15 * cw
    out = []
    arms = dict(arms)
    for a, b in (("u", "d"), ("l", "r")):                     # straight through: one stroke, no joint
        if a in arms and b in arms and arms[a] == arms[b] != "DOUBLE":
            out.append(Path([edge[a], edge[b]], False, 1.8 if arms[a] == "HEAVY" else 1.0))
            del arms[a], arms[b]
    for d, st in arms.items():
        wm = 1.8 if st == "HEAVY" else 1.0
        vert = d in "ud"
        perp = [k for k in arms if (k in "lr") == vert]
        if st != "DOUBLE":
            out.append(Path([edge[d], (cx, cy)], False, wm))
            continue
        away = {"u": 1, "d": -1, "l": 1, "r": -1}[d]          # which way is "past the centre"
        for s in (-1, 1):
            if not perp or any(arms[k] != "DOUBLE" for k in perp):
                end = 0
            elif len(perp) == 2:
                end = -away * dd
            else:                                              # corner: outer line goes past
                p_side = {"l": -1, "r": 1, "u": -1, "d": 1}[perp[0]]
                end = away * dd if s == -p_side else -away * dd
            if vert:
                out.append(Path([(cx + s * dd, edge[d][1]), (cx + s * dd, cy + end)], False, 1.0))
            else:
                out.append(Path([(edge[d][0], cy + s * dd), (cx + end, cy + s * dd)], False, 1.0))
    return out


def glyph_paths(c, col, row, cw, ch, cache, lonely=True):
    """Strokes of character c at cell (col, row), in pixels; None if c is not a stroke
    character (the caller then renders the font glyph).  lonely: nothing beside it, so a
    + or * is drawn as the mark it is; inside a run it is just a bump in the line."""
    x0, y0 = col * cw, row * ch
    spec = GEOM.get(c)
    if spec is not None and c in "+*" and not lonely:
        spec = spec[:1]
    if spec is None:
        if c in "\u2571\u2572\u2573":
            spec = ([GEOM["/"][0]] if c != "\u2572" else []) + ([GEOM["\\"][0]] if c != "\u2571" else [])
        else:
            if c not in cache:
                cache[c] = box_arms(c) if is_box(c) else None
            ba = cache[c]
            return box_paths(ba[0], ba[1], x0, y0, cw, ch) if ba else None
    out = []
    for s in spec:
        if s[0] == "p":
            out.append(Path([(x0 + u * cw, y0 + v * ch) for u, v in s[1]], bool(s[2])))
        elif s[0] == "d":
            p = (x0 + s[1] * cw, y0 + s[2] * ch)
            out.append(Path([p, p], bool(s[3]) if len(s) > 3 else False))   # a dot: both ends here
        else:
            _k, u, v, rx, ry = s
            pts = [(x0 + (u + rx * math.cos(2 * math.pi * i / 20.0)) * cw,
                    y0 + (v + ry * math.sin(2 * math.pi * i / 20.0)) * ch) for i in range(21)]
            out.append(Path(pts, False, 1.0))
    return out


def link_paths(paths, thr):
    """Join stroke ends that nearly meet.  Returns {(path index, end 0|1): (index, end)}.
    Closest pairs first; an end joins at most one other, never to its own stroke, and never
    by a link that doubles back over the stroke it leaves."""
    ends = []
    for i, p in enumerate(paths):
        if p.link:
            ends.append((i, 0))
            ends.append((i, 1))
    if not ends:
        return {}, []

    def pt(e):
        return paths[e[0]].pts[0 if e[1] == 0 else -1]

    def out_dir(e):
        p = paths[e[0]].pts
        a, b = (p[1], p[0]) if e[1] == 0 else (p[-2], p[-1])
        dx, dy = b[0] - a[0], b[1] - a[1]
        n = math.hypot(dx, dy)
        return (dx / n, dy / n) if n > 1e-6 else None

    cell = max(thr, 1.0)
    bins = {}
    for e in ends:
        x, y = pt(e)
        bins.setdefault((int(x // cell), int(y // cell)), []).append(e)
    cand = []
    for e in ends:
        x, y = pt(e)
        bx, by = int(x // cell), int(y // cell)
        de = out_dir(e)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for f in bins.get((bx + dx, by + dy), ()):
                    if f[0] <= e[0]:
                        continue
                    q = pt(f)
                    vx, vy = q[0] - x, q[1] - y
                    dist = math.hypot(vx, vy)
                    if dist > thr:
                        continue
                    if dist > 0.5:
                        df = out_dir(f)
                        if (de and vx * de[0] + vy * de[1] < -0.2 * dist) or \
                           (df and -(vx * df[0] + vy * df[1]) < -0.2 * dist):
                            continue
                    cand.append((dist, e, f))
    cand.sort()
    links = {}
    for dist, e, f in cand:
        if e not in links and f not in links:
            links[e] = f
            links[f] = e
    # a stroke end that found no partner may still touch a junction: join it by a bare segment
    extras = []
    for e in ends:
        if e in links:
            continue
        x, y = pt(e)
        bx, by = int(x // cell), int(y // cell)
        de = out_dir(e)
        best = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for f in bins.get((bx + dx, by + dy), ()):
                    if f[0] == e[0]:
                        continue
                    q = pt(f)
                    vx, vy = q[0] - x, q[1] - y
                    dist = math.hypot(vx, vy)
                    if dist > 0.8 * thr or (de and dist > 0.5 and vx * de[0] + vy * de[1] < -0.2 * dist):
                        continue
                    if best is None or dist < best[0]:
                        best = (dist, q)
        if best:
            extras.append(([[x, y, False], [best[1][0], best[1][1], False]], 1.0, False))
    return links, extras


def chains(paths, links):
    """Walk the links and return strokes as (points [x, y, joined], pen width, smoothable)."""
    done = [False] * len(paths)
    out = []

    def walk(i, start):
        pts = []
        while True:
            done[i] = True
            p = paths[i]
            seq = list(zip(p.pts, p.join))
            if start == 1:
                seq.reverse()
            for k, (pt, _j) in enumerate(seq):
                pts.append([pt[0], pt[1], k == 0 and bool(pts) or (k == len(seq) - 1 and (i, 1 - start) in links)])
            nxt = links.get((i, 1 - start))
            if nxt is None or done[nxt[0]]:
                return pts
            pts[-1][2] = True
            i, start = nxt

    for i, p in enumerate(paths):
        if done[i]:
            continue
        if not p.link:
            done[i] = True
            out.append(([[x, y, False] for x, y in p.pts], p.wmul, False))     # a ring, a box piece: as is
            continue
        if (i, 0) in links and (i, 1) in links:
            continue                                            # inside a chain or a loop: later
        start = 0 if (i, 0) not in links else 1
        out.append((walk(i, start), p.wmul, True))
    for i, p in enumerate(paths):                                # pure loops
        if not done[i]:
            out.append((walk(i, 0), p.wmul, True))
    return out


def fillet(pts, rcap, max_turn, join_turn):
    """Round the corners of a polyline with quadratic curves.  Corners at joins between
    characters are rounded up to join_turn degrees, corners inside a character to max_turn."""
    clean = [pts[0]]
    for p in pts[1:]:
        if math.hypot(p[0] - clean[-1][0], p[1] - clean[-1][1]) > 0.05:
            clean.append(p)
    if len(clean) < 3:
        return [(p[0], p[1]) for p in clean]
    out = [(clean[0][0], clean[0][1])]
    for i in range(1, len(clean) - 1):
        a, v, b = clean[i - 1], clean[i], clean[i + 1]
        ax, ay, bx, by = a[0] - v[0], a[1] - v[1], b[0] - v[0], b[1] - v[1]
        la, lb = math.hypot(ax, ay), math.hypot(bx, by)
        cosv = max(-1.0, min(1.0, (ax * bx + ay * by) / (la * lb)))
        turn = 180.0 - math.degrees(math.acos(cosv))
        if turn < 3 or turn > (join_turn if v[2] else max_turn):
            out.append((v[0], v[1]))
            continue
        r = min(0.5 * la, 0.5 * lb, rcap)
        p0 = (v[0] + ax / la * r, v[1] + ay / la * r)
        p1 = (v[0] + bx / lb * r, v[1] + by / lb * r)
        for k in range(7):
            t = k / 6.0
            out.append(((1 - t) ** 2 * p0[0] + 2 * t * (1 - t) * v[0] + t * t * p1[0],
                        (1 - t) ** 2 * p0[1] + 2 * t * (1 - t) * v[1] + t * t * p1[1]))
    out.append((clean[-1][0], clean[-1][1]))
    return out


def _turn(a, v, b):
    """How far, in degrees, a path turns at v on its way a -> v -> b."""
    ax, ay, bx, by = a[0] - v[0], a[1] - v[1], b[0] - v[0], b[1] - v[1]
    la, lb = math.hypot(ax, ay), math.hypot(bx, by)
    if la < 1e-9 or lb < 1e-9:
        return 0.0
    return 180.0 - math.degrees(math.acos(max(-1.0, min(1.0, (ax * bx + ay * by) / (la * lb)))))


def _smooth_span(pts, sigma, h):
    """Smooth an open polyline, keeping its two ends where they are.  It is resampled every
    h pixels and low-passed with a Gaussian of `sigma` pixels (a smoothing spline): staircases
    of _ and / become a diagonal, rows of marks a wave, straight runs stay straight.  The
    ends are pinned by reflecting the curve through them (odd extension) before filtering."""
    if len(pts) < 3:
        return [(p[0], p[1]) for p in pts]
    P = np.asarray([(p[0], p[1]) for p in pts], np.float64)
    d = np.concatenate(([0.0], np.cumsum(np.hypot(*np.diff(P, axis=0).T))))
    n = max(2, int(round(d[-1] / h)) + 1)
    if n < 4:
        return [(p[0], p[1]) for p in pts]
    t = np.linspace(0.0, d[-1], n)
    P = np.column_stack([np.interp(t, d, P[:, 0]), np.interp(t, d, P[:, 1])])
    s = max(sigma / h, 0.5)
    r = max(1, int(math.ceil(3.0 * s)))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / s) ** 2)
    k /= k.sum()
    i = np.arange(1, r + 1)
    Q = np.vstack([2 * P[0] - P[np.minimum(i, n - 1)][::-1], P, 2 * P[-1] - P[np.maximum(n - 1 - i, 0)]])
    return list(zip(np.convolve(Q[:, 0], k, mode="valid").tolist(),
                    np.convolve(Q[:, 1], k, mode="valid").tolist()))


def spline_smooth(pts, sigma, h, max_turn, join_turn, step):
    """Smooth a chain [[x, y, joined]] with _smooth_span, but leave the sharp corners alone:
    the chain is cut at them (more than join_turn degrees where two characters meet,
    max_turn inside one: the apex of ^, the tip of <, the corners of [; terraces, two turns
    within `step` pixels, count as smooth up to join_turn) and each stretch
    between is smoothed with both its ends pinned."""
    n = len(pts)
    if n < 3:
        return [(p[0], p[1]) for p in pts]
    # signed turn at every vertex: positive one way, negative the other
    signed = [0.0] * n
    for i in range(1, n - 1):
        a, v, b = pts[i - 1], pts[i], pts[i + 1]
        cross = (v[0] - a[0]) * (b[1] - v[1]) - (v[1] - a[1]) * (b[0] - v[0])
        dot = (v[0] - a[0]) * (b[0] - v[0]) + (v[1] - a[1]) * (b[1] - v[1])
        signed[i] = math.degrees(math.atan2(cross, dot))

    def stepped(i):
        """Is vertex i one half of an S: a turn one way and, within `step` px, one the other
        way (the riser between a _ and a - on the next row)?  That is a terrace to smooth,
        where a single right angle (|_) is a corner to keep."""
        for j in (i - 1, i + 1):
            if 0 < j < n - 1 and signed[j] * signed[i] < 0 and abs(signed[j]) > 40 and \
               math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]) <= step:
                return True
        return False

    def corner(i):
        """The turn at vertex i, with its neighbours' if they turn the same way close by: a
        right angle between two characters is two 45 degree turns with a short link between."""
        t = signed[i]
        for j in (i - 1, i + 1):
            if 0 < j < n - 1 and signed[j] * signed[i] > 0 and \
               math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]) <= step:
                t += signed[j]
        return abs(t)

    def sharp(i):
        if not pts[i][2]:
            return abs(signed[i]) > max_turn
        if stepped(i):
            return abs(signed[i]) > join_turn
        return corner(i) > 85
    cut = [0] + [i for i in range(1, n - 1) if sharp(i)] + [n - 1]
    out = []
    for a, b in zip(cut, cut[1:]):
        seg = _smooth_span(pts[a:b + 1], sigma, h)
        out.extend(seg if not out else seg[1:])
    return out


def hatch_layer(mask, cw, ch, w, space):
    """Diagonal hatching ("/" lines, w pixels wide, `space` pixels apart across the lines)
    filling the cells where mask is true.  The pattern is anchored to the picture, so
    neighbouring shaded regions line up."""
    mask = np.asarray(mask, bool)
    rows, cols = mask.shape
    out = np.zeros((rows * ch, cols * cw), np.float32)
    ys_, xs_ = np.nonzero(mask)
    r0, r1, c0, c1 = max(0, ys_.min() - 1), min(rows, ys_.max() + 2), max(0, xs_.min() - 1), min(cols, xs_.max() + 2)
    # the region follows the cell grid; soften it so slanted edges are slanted, not stepped.
    # Done on 4x4 samples per cell and scaled up smoothly: a wide blur at full size is slow.
    k = 4
    m = np.kron(mask[r0:r1, c0:c1].astype(np.float32), np.ones((k, k), np.float32))
    m = blur(np.pad(m, k, mode="constant"), 0.5 * k, 0.25 * k)[k:-k, k:-k]
    m = np.asarray(Image.fromarray(m).resize(((c1 - c0) * cw, (r1 - r0) * ch), Image.BICUBIC), np.float32)
    m = smoothstep((m - 0.35) / 0.3)
    ys = np.arange(r0 * ch, r1 * ch, dtype=np.float32)[:, None]
    xs = np.arange(c0 * cw, c1 * cw, dtype=np.float32)[None, :]
    period = space * math.sqrt(2.0)
    u = np.mod(xs + ys, period)
    dist = np.minimum(u, period - u) / math.sqrt(2.0)
    out[r0 * ch:r1 * ch, c0 * cw:c1 * cw] = np.clip(0.5 * w - dist + 0.5, 0.0, 1.0) * m
    return out


def draw_strokes(strokes, W, H, w, ss):
    """Antialiased pen strokes: drawn at ss times the size, then box-filtered down."""
    big = Image.new("L", (W * ss, H * ss), 0)
    d = ImageDraw.Draw(big)
    for pts, wmul in strokes:
        if len(pts) == 1:                                        # a dot
            r = 0.9 * w * ss
            x, y = pts[0][0] * ss, pts[0][1] * ss
            d.ellipse([x - r, y - r, x + r, y + r], fill=255)
            continue
        wi = max(1, int(round(w * wmul * ss)))
        r = wi / 2.0                                             # caps as wide as the line, or they show as beads
        P = [(x * ss, y * ss) for x, y in pts]
        for a, b in zip(P, P[1:]):
            if b < a:                                            # PIL rounds a wide line differently
                a, b = b, a                                      # drawn backwards: always go the same way
            d.line([a, b], fill=255, width=wi)
        for x, y in P:
            d.ellipse([x - r, y - r, x + r, y + r], fill=255)
    return np.asarray(big.resize((W, H), Image.BOX), np.float32) / 255.0


# --------------------------------------------------------------------------
# Putting it together
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# Block: ANSI art made of blocks and graphic characters, as the picture it is
# --------------------------------------------------------------------------
def block_image(grid, glyphs, o):
    """The art as an image, as a terminal would show it but with exact cell sizes: every cell is
    its background colour with the character's glyph in its foreground colour on top (blocks and
    braille are exact rectangles, shade characters blend the two colours, other characters are
    font glyphs).  Returns (rgb uint8 (h, w, 3), alpha float32 (h, w)); cells with the terminal's
    default background are transparent wherever the glyph is not."""
    rows, cols = grid.rows, grid.cols
    cw, ch = glyphs.cw, glyphs.ch
    ink_c = tuple(float(v) for v in o.ink)
    paper_c = tuple(float(v) for v in o.paper)

    def rgb(v, default):
        if v is None:
            return default
        if isinstance(v, str):
            return ink_c if v == "fgdef" else paper_c
        return (float(v[0]), float(v[1]), float(v[2]))
    img = np.zeros((rows * ch, cols * cw, 3), np.uint8)
    alpha = np.zeros((rows * ch, cols * cw), np.float32)
    for y in range(rows):
        M = np.concatenate([glyphs.mask(c) for c in grid.ch[y]], axis=1)             # (ch, W)
        fg = np.repeat(np.array([rgb(f, ink_c) for f in grid.fg[y]], np.float32), cw, 0)[None]
        bgl = grid.bg[y]
        has_bg = np.repeat(np.array([b is not None for b in bgl]), cw)[None, :]
        bg = np.repeat(np.array([rgb(b, paper_c) for b in bgl], np.float32), cw, 0)[None]
        Mw = M[..., None]
        col = np.where(has_bg[..., None], bg * (1.0 - Mw) + fg * Mw, fg)
        img[y * ch:(y + 1) * ch] = np.clip(col + 0.5, 0, 255).astype(np.uint8)
        alpha[y * ch:(y + 1) * ch] = np.where(has_bg, 1.0, M)
    return img, alpha


def _soften(img, alpha, sx, sy):
    """Blur a picture with transparency without bleeding the colour of what is not there: the
    colour is blurred premultiplied by alpha and divided by the blurred alpha.  Pillow's own
    Gaussian does it (8 bits, in C, a tenth of the time of doing it in numpy); its radius is one
    number, so the two sigmas are averaged."""
    a8 = np.clip(alpha * 255.0 + 0.5, 0, 255).astype(np.uint8)
    pm = (img.astype(np.float32) * alpha[..., None] + 0.5).astype(np.uint8)
    out = np.asarray(Image.fromarray(np.dstack([pm, a8])).filter(ImageFilter.GaussianBlur(max(0.3, 0.5 * (sx + sy)))))
    af = out[..., 3].astype(np.float32) / 255.0
    col = out[..., :3].astype(np.float32) / np.maximum(af, 1.0 / 255.0)[..., None]
    return np.clip(col + 0.5, 0, 255).astype(np.uint8), af


class Options(object):
    mode = "auto"           # auto | lineart | ansi-block (block) | line | tone | mix
    cell_w = 12             # pixels per character cell
    aspect = 2.0            # cell height / width
    weight = 1.0            # pen thickness, relative
    join = 1.0              # how far apart stroke ends may be and still join, in cell widths
    round_lines = True      # smooth the strokes (False: leave every corner sharp)
    spline = 0.6            # line: how much, as a Gaussian sigma in cell widths (0 = round corners only)
    shade = "X"             # line: runs of these characters are shading (hatched); "" = none
    hatch = 1.0             # line: spacing of that hatching, relative
    text_bold = 0.25        # line: how much letters thicken as the pen gets thicker (0 = not at all)
    smooth = None           # tone: blur in dot pitches, smooths the contours (default 0.7); block: softens the pixels (0.12)
    detail = 0.12           # tone: smallest edge (tone change per dot pitch) that is drawn
    scale = 0.4             # tone: finest outline feature, in dot pitches
    levels = 3              # tone: contour lines through the shading (0 = outlines only)
    dark = None             # tone: default colours are light on dark (None: yes if the art uses colour)
    invert = False          # tone: draw outlines of the negative (affects nothing for edges)
    color = "auto"          # auto: keep the ANSI colours if the art has any | on | off
    ink = None              # the line colour (and what grey / white text becomes).  None: decided from the
    paper = None            # art and filled in by render_grid_color: black on white, but for colour
    #                         block art what a terminal shows, light grey on black
    font = None
    cols = 0                # wrap column for cursor-addressed .ANS art (0: never)
    rows = 24               # height of the screen that cursor addressing and scroll regions refer to
    crop = True
    verbose = False

    def __init__(self, **kw):
        for k, v in kw.items():
            if not hasattr(self, k):
                raise TypeError("unknown option " + k)
            setattr(self, k, v)


def _log(o, *a):
    if o.verbose:
        sys.stderr.write("unascii: " + " ".join(str(x) for x in a) + "\n")


def render_grid_color(grid, o):
    """Grid -> (ink, rgb).  ink: float32 array, 1 = line, rows*cell_h x cols*cell_w (+ margin).
    rgb: uint8 (h, w, 3), the colour of the line wherever there is some, or None when the art is
    drawn in one colour (no colour in it, or color == "off")."""
    cw = max(4, int(o.cell_w))
    cw += cw % 2                                  # half-cell and braille dots need whole pixels
    mode = "block" if o.mode == "ansi-block" else o.mode
    shade = shade_cells(grid, o.shade)
    if mode in ("auto", "lineart"):
        picked, st = classify(grid, shade)
        if mode == "lineart" and picked == "block":
            picked = "tone"                       # asked for lines: outline the picture instead
        _log(o, mode, "->", picked, " ".join("%s=%.2f" % kv for kv in sorted(st.items())))
        mode = picked
    use_color = o.color == "on" or (o.color == "auto" and grid.has_color())
    # Colour block art is drawn the way a terminal shows it: on black, default text light grey.
    dark_picture = mode == "block" and (o.dark if o.dark is not None else grid.has_color())
    if o.paper is None:
        o.paper = (0, 0, 0) if dark_picture else (255, 255, 255)
    if o.ink is None:
        o.ink = ((170, 170, 170) if grid.vga else (229, 229, 229)) if dark_picture else (0, 0, 0)
    budget = 24e6 if mode in ("tone", "mix", "block") else 48e6    # pixels; a huge picture is drawn smaller
    ch = max(4, int(round(cw * o.aspect / 4.0)) * 4)
    while cw > 4 and (grid.rows * ch + 2 * cw) * (grid.cols * cw + 2 * cw) > budget:
        cw -= 2
        ch = max(4, int(round(cw * o.aspect / 4.0)) * 4)
        _log(o, "big picture: cell width cut to", cw)
    glyphs = Glyphs(cw, ch, o.font)
    _log(o, "font:", glyphs.path)
    pad = cw
    W, H = grid.cols * cw + 2 * pad, grid.rows * ch + 2 * pad
    ink = np.zeros((H, W), np.float32)
    wpx = 0.12 * cw * o.weight
    ink_rgb = np.array(o.ink, np.float32)
    rgb = None
    if use_color or mode == "block":
        rgb = np.empty((H, W, 3), np.uint8)
        rgb[:] = np.clip(legible(ink_rgb, ink_rgb, o.paper) + 0.5, 0, 255).astype(np.uint8)

    def put(layer, target=None, dy=pad, dx=pad):
        t = ink if target is None else target
        h, w = layer.shape
        t[dy:dy + h, dx:dx + w] = np.maximum(t[dy:dy + h, dx:dx + w], layer)

    if mode == "block":
        img, alpha = block_image(grid, glyphs, o)
        px, py = pitch_of(grid, cw, ch)
        sm = 0.12 if o.smooth is None else o.smooth
        if sm > 0:
            img, alpha = _soften(img, alpha, sm * px, sm * py)
        h, w = alpha.shape
        if o.color == "off":                                     # greys instead of colours
            grey = np.rint(img.astype(np.float32).dot(np.array([0.299, 0.587, 0.114], np.float32)))
            img = np.repeat(grey[..., None], 3, 2).astype(np.uint8)
        ink[pad:pad + h, pad:pad + w] = alpha
        rgb[pad:pad + h, pad:pad + w] = img
        _log(o, "block picture %dx%d, smoothing %.2f" % (grid.cols, grid.rows, sm))

    if mode == "tone" or mode == "mix":
        if mode == "tone":
            only = None
        else:
            def only(c):
                return c in DENSE or is_block(c) or is_braille(c)
        px, py = pitch_of(grid, cw, ch)
        ix, iy = max(1, int(round(px))), max(1, int(round(py)))
        dark = o.dark if o.dark is not None else grid.has_color()
        P = dot_field(grid, glyphs, only, dark, max(1, cw // ix), max(1, ch // iy))
        tone, sparse = tone_lines(P, ix, iy, wpx, o, use_color)
        put(tone)
        if sparse is not None:
            ys, xs, col = sparse
            rgb[ys + pad, xs + pad] = np.clip(legible(col, ink_rgb, o.paper) + 0.5, 0, 255).astype(np.uint8)
    if mode == "line" or mode == "mix":
        paths, cache = [], {}
        layer = np.zeros((grid.rows * ch, grid.cols * cw), np.float32)
        text = word_cells(grid, shade)
        lifted = bubble_bottoms(grid)
        for y in range(grid.rows):
            for x in range(grid.cols):
                c = grid.ch[y][x]
                if c == " " or (shade and shade[y][x]):
                    continue
                if mode == "mix" and (c in DENSE or is_block(c) or is_braille(c)):
                    continue
                row = grid.ch[y]
                lonely = (x == 0 or row[x - 1] == " ") and (x == grid.cols - 1 or row[x + 1] == " ")
                if (y, x) in lifted:                             # speech bubble: close it at the bottom
                    ps = [Path([(x * cw, y * ch + 0.07 * ch), ((x + 1) * cw, y * ch + 0.07 * ch)], True)]
                else:
                    ps = None if text[y][x] else glyph_paths(c, x, y, cw, ch, cache, lonely)
                if ps is not None:
                    paths.extend(ps)
                else:                                            # letters etc.: the font's glyph
                    m = glyphs.mask(c)
                    if o.weight > 1.2:
                        m = np.clip(blur(m, 0.25 * wpx) * min(1.6, 1.0 + (o.weight - 1.0) * o.text_bold), 0, 1)
                    layer[y * ch:(y + 1) * ch, x * cw:(x + 1) * cw] = m
        for p in paths:
            p.pts = [(a + pad, b + pad) for a, b in p.pts]
        links, extras = link_paths(paths, o.join * cw)
        strokes = chains(paths, links) + extras
        done = []
        for pts, wm, smoothable in strokes:
            clean = [pts[0]]
            for p in pts[1:]:
                if math.hypot(p[0] - clean[-1][0], p[1] - clean[-1][1]) > 0.05:
                    clean.append(p)                              # (a lone dot ends up as one point)
            if not smoothable:
                done.append(([(p[0], p[1]) for p in clean], wm))
            elif o.round_lines and len(clean) > 2 and o.spline > 0:
                done.append((spline_smooth(clean, o.spline * cw, max(1.0, 0.1 * cw), 80, 100, 1.1 * cw), wm))
            elif o.round_lines and len(clean) > 2:
                done.append((fillet(clean, 0.6 * cw, 80, 100), wm))
            else:
                done.append(([(p[0], p[1]) for p in clean], wm))
        strokes = done
        ss = max(1, min(4, int(math.sqrt(16e6 / float(W * H)))))
        lines = draw_strokes(strokes, W, H, wpx, ss)
        put(layer, lines)
        if shade:
            space = 0.55 * cw * o.hatch
            put(hatch_layer(shade, cw, ch, min(0.55 * wpx, 0.3 * space), space), lines)
        if use_color:                                            # each stroke in its cell's colour
            cmap = cell_color_map(grid, ink_rgb, o.paper)
            ys, xs = np.nonzero(lines > 0.02)
            rgb[ys, xs] = cmap[np.clip((ys - pad) // ch, 0, grid.rows - 1), np.clip((xs - pad) // cw, 0, grid.cols - 1)]
        np.maximum(ink, lines, out=ink)
        _log(o, "strokes: %d paths, %d joins, %d chains%s" % (len(paths), len(links) // 2, len(strokes),
                                                            ", shaded" if shade else ""))
    if o.crop:
        ys, xs = np.nonzero(ink > 0.02)
        if len(ys):
            m = 0 if mode == "block" else int(0.5 * cw)       # a picture runs to its edges
            y0, y1, x0, x1 = max(0, ys.min() - m), ys.max() + m + 1, max(0, xs.min() - m), xs.max() + m + 1
            ink = ink[y0:y1, x0:x1]
            rgb = rgb[y0:y1, x0:x1] if rgb is not None else None
    return ink, rgb


def render_grid(grid, o):
    """Grid -> ink picture (float32, 1 = line); see render_grid_color for the colours."""
    return render_grid_color(grid, o)[0]


def _grid_of(data, o):
    text, enc = decode2(data)
    return parse(text, o.cols, rows=o.rows, glyphs=enc == "cp437")


def render(data, **kw):
    """text/bytes -> ink array (1 = ink).  Keyword arguments are Options fields."""
    o = Options(**kw)
    return render_grid(_grid_of(data, o), o)


def render_color(data, **kw):
    """text/bytes -> (ink, rgb), see render_grid_color."""
    o = Options(**kw)
    return render_grid_color(_grid_of(data, o), o)


def to_image(ink, fg=(0, 0, 0), bg=(255, 255, 255), transparent=False, rgb=None):
    """PIL image from an ink picture: fg lines on bg, or, with rgb (from render_color), lines in
    their own colours."""
    a = np.clip(ink, 0, 1)
    if transparent:
        out = np.zeros(a.shape + (4,), np.uint8)
        out[..., :3] = fg if rgb is None else rgb
        out[..., 3] = (a * 255 + 0.5).astype(np.uint8)
        return Image.fromarray(out)
    f = np.array(fg, np.float32) if rgb is None else rgb.astype(np.float32)
    b = np.array(bg, np.float32)
    out = b + (f - b) * a[..., None]
    return Image.fromarray((out + 0.5).astype(np.uint8))


def mask(data, cell_w, cell_h=None, **kw):
    """For other programs (bidet3d): the drawing as a PIL 'L' mask, 255 = ink, cropped to the
    drawing.  cell_w / cell_h are the size of one character cell in pixels."""
    kw.setdefault("cell_w", cell_w)
    kw.setdefault("color", "off")
    kw.setdefault("mode", "lineart")                 # a shape to extrude is lines, not a picture
    if cell_h:
        kw["aspect"] = cell_h / float(cell_w)
    ink = render(data, **kw)
    return Image.fromarray((np.clip(ink, 0, 1) * 255 + 0.5).astype(np.uint8))


# --------------------------------------------------------------------------
# SIXEL out (ink picture -> a ramp from paper to ink, so both are exact)
# --------------------------------------------------------------------------
def _rle_rows(bits):
    """SIXEL run-length coding of every row of a (K, W) uint8 array of sixel characters, as K
    strings.  Runs of 1-3 are written out, longer ones as !<count><char>.  All K rows are done
    together with array operations (a big picture has hundreds of thousands of runs, and numpy
    costs too much per call to do them a row at a time)."""
    K, W = bits.shape
    flat = bits.reshape(-1)
    brk = np.zeros(flat.size, bool)
    brk[::W] = True                                         # a run never crosses a row
    brk[1:] |= flat[1:] != flat[:-1]
    starts = np.flatnonzero(brk)
    lens = np.diff(np.append(starts, flat.size))
    chars = flat[starts]
    long_ = lens > 3
    ndig = 1 + (lens >= 10) + (lens >= 100) + (lens >= 1000) + (lens >= 10000)
    size = np.where(long_, ndig + 2, lens)
    off = np.cumsum(size) - size
    out = np.empty(int(size.sum()), np.uint8)
    sh = ~long_
    if sh.any():                                            # a short run: its char, lens times
        n = lens[sh]
        base = np.repeat(off[sh] - (np.cumsum(n) - n), n)
        out[base + np.arange(int(n.sum()))] = np.repeat(chars[sh], n)
    if long_.any():                                         # a long run: ! digits char
        o, n, nd = off[long_], lens[long_], ndig[long_]
        out[o] = 33
        for k in range(5):
            has = nd > k                                    # digit k from the right, if the count has one
            out[(o + nd - k)[has]] = (n[has] // 10 ** k) % 10 + 48
        out[o + nd + 1] = chars[long_]
    text = out.tobytes().decode("ascii")
    first = np.searchsorted(starts, np.arange(K) * W)       # the first run of each row
    bounds = np.append(off, out.size)[np.append(first, len(starts))].tolist()
    return [text[bounds[i]:bounds[i + 1]] for i in range(K)]


def _sixel_stream(idx, palette, transparent):
    """SIXEL bytes for an array of palette indices (uint8; index 0 is the paper, left unpainted
    when transparent) and the palette, a list of (r, g, b) 0..255."""
    H, W = idx.shape
    out = ["\x1bP0;%d;0q\"1;1;%d;%d" % (1 if transparent else 0, W, H)]
    for i, c in enumerate(palette):
        out.append("#%d;2;%d;%d;%d" % (i, int(round(c[0] * 100 / 255.0)), int(round(c[1] * 100 / 255.0)),
                                       int(round(c[2] * 100 / 255.0))))
    weights = (1 << np.arange(6)).astype(np.uint8)[None, :, None]
    tail = re.compile(r"!\d+\?$")
    for top in range(0, H, 6):
        band = idx[top:top + 6]
        if band.shape[0] < 6:
            band = np.vstack([band, np.full((6 - band.shape[0], W), 255, np.uint8)])
        present = [c for c in np.unique(band).tolist() if c != 255 and not (transparent and c == 0)]
        # for each colour present: which of the six pixels in a column have it, as one sixel character
        bits = ((band[None] == np.array(present, np.uint8)[:, None, None]).astype(np.uint8) * weights).sum(1)
        rows = _rle_rows((bits + 63).astype(np.uint8))
        for n, (c, s) in enumerate(zip(present, rows)):
            # a trailing "nothing here" is not needed.  A long run "!72?" goes whole (stripping only its "?"
            # left "!72" before the "$", which a strict decoder reads as 72 x "$"); a short one is written out
            s = tail.sub("", s).rstrip("?")
            out.append("#%d%s%s" % (c, s, "$" if n < len(present) - 1 else ""))
        out.append("-")
    out.append("\x1b\\")
    return "".join(out).encode("ascii")


def sixel(ink, fg=(0, 0, 0), bg=(255, 255, 255), levels=16, transparent=False, rgb=None, ncolors=24, shades=6,
          image=None):
    """SIXEL stream (bytes) for an ink picture.  Pixels are painted in `levels` blends of
    bg -> fg; with transparent=True the bg pixels are left unpainted.  With rgb (from
    render_color) the lines keep their colours: those are reduced to `ncolors`, each painted
    in `shades` blends with the paper, which keeps the paper exact and the lines antialiased.
    A picture that covers much of the area (block art; image=True forces it) is composited on the
    paper and painted with its own colours: exactly if it has at most 254, else median-cut."""
    ink = np.clip(ink, 0, 1)
    bg = np.array(bg, np.float64)

    def blend(c, t):
        return bg + (np.array(c, np.float64) - bg) * t
    sel = ink > 0.25
    if rgb is not None and (image or (image is None and sel.mean() > 0.25)):
        H, W = ink.shape
        comp = np.clip(bg + (rgb.astype(np.float64) - bg) * ink[..., None] + 0.5, 0, 255).astype(np.uint8)
        flat = comp.reshape(-1, 3).astype(np.int32)
        key = (flat[:, 0] << 16) | (flat[:, 1] << 8) | flat[:, 2]
        uniq, inv = np.unique(key, return_inverse=True)
        if len(uniq) <= 254:
            pal = [((k >> 16) & 255, (k >> 8) & 255, k & 255) for k in uniq.tolist()]
            idx = inv.reshape(H, W)
        else:
            q = Image.fromarray(comp).quantize(254, Image.MEDIANCUT)
            p = q.getpalette()[:254 * 3]
            pal = [tuple(p[i:i + 3]) for i in range(0, len(p), 3)]
            idx = np.asarray(q)
        idx = (idx + 1).astype(np.uint8)
        if transparent:
            idx[ink < 0.02] = 0
        return _sixel_stream(idx, [bg] + pal, transparent)
    if rgb is None or not sel.any():
        idx = np.clip(np.rint(ink * (levels - 1)), 0, levels - 1).astype(np.uint8)
        return _sixel_stream(idx, [blend(fg, i / float(levels - 1)) for i in range(levels)], transparent)
    r = rgb.astype(np.int32)
    key = ((r[..., 0] >> 5) << 6) | ((r[..., 1] >> 5) << 3) | (r[..., 2] >> 5)        # 8x8x8 colour cells
    w, k = ink[sel].astype(np.float64), key[sel]
    count = np.bincount(k, weights=w, minlength=512)
    chosen = np.argsort(-count)[:ncolors]
    chosen = chosen[count[chosen] > 0]
    sums = [np.bincount(k, weights=w * r[sel][:, c], minlength=512) for c in range(3)]
    centres = np.stack([sums[c][chosen] / count[chosen] for c in range(3)], 1)         # (K, 3)
    cells = np.arange(512)
    cell_rgb = np.stack([(cells >> 6) * 32 + 16, ((cells >> 3) & 7) * 32 + 16, (cells & 7) * 32 + 16], 1)
    lut = ((cell_rgb[:, None, :] - centres[None]) ** 2).sum(2).argmin(1)               # cell -> nearest colour
    level = np.rint(ink * (shades - 1)).astype(np.int32)
    idx = np.where(level == 0, 0, 1 + lut[key] * (shades - 1) + level - 1).astype(np.uint8)
    palette = [bg] + [blend(c, s / float(shades - 1)) for c in centres for s in range(1, shades)]
    return _sixel_stream(idx, palette, transparent)


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------
def _color(s):
    from PIL import ImageColor
    try:
        return ImageColor.getrgb(s)[:3]
    except ValueError:
        sys.exit("unascii: bad colour '%s'" % s)


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="unascii", description="Turn ASCII/ANSI terminal art back into a line drawing "
        "(PNG, or SIXEL for the terminal).")
    ap.add_argument("file", nargs="?", default="-", help="art file (default: stdin)")
    ap.add_argument("-o", "--output", metavar="FILE", help="write a PNG here ('-' = stdout)")
    ap.add_argument("-s", "--sixel", action="store_true",
                    help="print SIXEL to stdout (default when stdout is a terminal)")
    ap.add_argument("-m", "--mode", choices=["auto", "lineart", "ansi-block", "block", "line", "tone", "mix"], default="auto",
                    help="lineart: line drawing (cowsay, figlet; picture-style art is outlined); ansi-block: "
                         "block/graphic-character art as the coloured picture it is; auto picks one (default). "
                         "line, tone, mix: force one lineart method")
    ap.add_argument("-c", "--cell", type=int, default=12, metavar="PX",
                    help="width of one character cell in output pixels (default 12)")
    ap.add_argument("-a", "--aspect", type=float, default=2.0,
                    help="cell height / width (default 2.0)")
    ap.add_argument("-w", "--weight", type=float, default=1.0, help="pen thickness (default 1)")
    ap.add_argument("-j", "--join", type=float, default=1.0, metavar="CELLS",
                    help="line mode: join stroke ends this close (cell widths, default 1; 0 = never)")
    ap.add_argument("--no-round", action="store_true", help="line mode: no smoothing, keep every corner sharp")
    ap.add_argument("--spline", type=float, default=0.6, metavar="F",
                    help="line mode: spline smoothing of joined strokes, in cell widths (default 0.6; "
                         "0 = only round the corners)")
    ap.add_argument("--shade", default="X", metavar="CHARS",
                    help="line mode: runs of these characters are shading and get hatched (default X; "
                         "'' = none)")
    ap.add_argument("--text-bold", type=float, default=0.25, metavar="F",
                    help="line mode: how much letters thicken with --weight above 1.2 (default 0.25; 0 = never)")
    ap.add_argument("--hatch", type=float, default=1.0, metavar="F",
                    help="line mode: spacing of the hatching (default 1)")
    ap.add_argument("--smooth", type=float, default=None,
                    help="tone: blur in dot pitches (default 0.7); ansi-block: softening of the pixels (default 0.12, 0 = crisp)")
    ap.add_argument("--detail", type=float, default=0.12,
                    help="tone: smallest tonal step that gets an outline (0..1, default 0.12)")
    ap.add_argument("--scale", type=float, default=0.4,
                    help="tone: finest outline feature in dot pitches (default 0.4)")
    ap.add_argument("--levels", type=int, default=3,
                    help="tone: contour lines through the shading (default 3, 0 = outlines only)")
    ap.add_argument("--dark", action="store_true", default=None,
                    help="tone: the art is light on dark (default colours); on by itself when the art uses colour")
    ap.add_argument("--color", "--colour", dest="color", choices=["auto", "on", "off"], default="auto",
                    help="keep the ANSI colours: auto = if the art has any (default), on, off")
    ap.add_argument("--mono", dest="color", action="store_const", const="off",
                    help="draw in one colour (--ink) even if the art has colours")
    ap.add_argument("--invert", action="store_true", help="tone: outline the negative")
    ap.add_argument("--ink", default=None,
                    help="line colour, and what grey / white text becomes (default black; light grey for colour block art)")
    ap.add_argument("--paper", default=None,
                    help="background colour (default white; black for colour block art, as a terminal shows it)")
    ap.add_argument("--transparent", action="store_true", help="PNG/SIXEL with a transparent background")
    ap.add_argument("--width", type=int, metavar="PX", help="scale the picture to this width")
    ap.add_argument("--font", help="monospace font file (default: look for DejaVu Sans Mono, Consolas, ...)")
    ap.add_argument("--encoding", help="input encoding (default: UTF-8, else CP437)")
    ap.add_argument("--cols", type=int, default=0, help="wrap column for .ANS art (default: none; 80 for .ans)")
    ap.add_argument("--rows", type=int, default=24,
                    help="screen height for cursor addressing and scroll regions (default 24)")
    ap.add_argument("--no-crop", action="store_true", help="keep the margin around the drawing")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("-V", "--version", action="version", version="unascii " + VERSION)
    a = ap.parse_args(argv)

    if a.file == "-":
        if sys.stdin.isatty():
            ap.error("no input: give a file or pipe the art in")
        data = sys.stdin.buffer.read()
    else:
        with open(a.file, "rb") as f:
            data = f.read()
    fg, bg = (_color(a.ink) if a.ink else None), (_color(a.paper) if a.paper else None)
    o = Options(mode=a.mode, cell_w=a.cell, aspect=a.aspect, weight=a.weight, join=a.join * 1.0,
                round_lines=not a.no_round, spline=a.spline, shade=a.shade, hatch=a.hatch,
                text_bold=a.text_bold, smooth=a.smooth, detail=a.detail, scale=a.scale, levels=a.levels,
                dark=a.dark, invert=a.invert, font=a.font, rows=a.rows, color=a.color, ink=fg, paper=bg,
                cols=a.cols or (80 if a.file.lower().endswith(".ans") else 0),
                crop=not a.no_crop, verbose=a.verbose)
    if a.join <= 0:
        o.join = 0.0
    text, enc = decode2(data, a.encoding)
    try:
        grid = parse(text, o.cols, rows=o.rows, glyphs=enc in ("cp437", "437") or a.file.lower().endswith(".ans"))
    except ValueError as e:
        sys.exit("unascii: %s" % e)
    ink, rgb = render_grid_color(grid, o)
    fg, bg = o.ink, o.paper                  # decided from the art unless given (see Options)
    if a.width and a.width != ink.shape[1]:
        h = max(1, int(round(ink.shape[0] * a.width / float(ink.shape[1]))))
        im = Image.fromarray((np.clip(ink, 0, 1) * 255 + 0.5).astype(np.uint8))
        ink = np.asarray(im.resize((a.width, h), Image.LANCZOS), np.float32) / 255.0
        if rgb is not None:
            rgb = np.asarray(Image.fromarray(rgb).resize((a.width, h), Image.NEAREST))

    out = sys.stdout.buffer
    want_sixel = a.sixel or (not a.output and sys.stdout.isatty())
    if a.output:
        img = to_image(ink, fg, bg, a.transparent, rgb)
        if a.output == "-":
            buf = io.BytesIO()
            img.save(buf, "PNG")
            out.write(buf.getvalue())
            out.flush()
        else:
            img.save(a.output, "PNG")
    if want_sixel or not a.output and not sys.stdout.isatty():
        if want_sixel:
            out.write(sixel(ink, fg, bg, transparent=a.transparent, rgb=rgb) + b"\n")
        else:
            buf = io.BytesIO()
            to_image(ink, fg, bg, a.transparent, rgb).save(buf, "PNG")
            out.write(buf.getvalue())
        out.flush()


if __name__ == "__main__":
    main()
