"""bifin_regions: art that is several kinds of art at once.

A message of the day, a neofetch screen, a banner with a caption: one file holds a logo in line art,
a figlet title, a picture of half blocks and a few lines of plain text.  One method for the whole grid
(bifin_text.classify) gets some of it wrong: the text is blurred with the picture, or traced as outlines,
or its digits are eaten as shading.  This module cuts the grid into regions, gives each the method that suits
it, and bifin_text.import_grid draws each region with that method (the methods are the old ones, run on
a copy of the grid that holds only the region's cells) and puts the layers together.

    text    prose: lines of words (and the numbers and punctuation between them), set in the font
    block   cells that are pixels: half blocks, braille, shades, cells with a colour behind them
    line    figlet, cowsay, line drawings           (bifin_text's `line`)
    tone    shaded pictures made of ordinary characters    (`tone`)
    mix     dense fill characters with strokes among them  (`mix`)

Nothing here changes what a single-method picture comes out as: `plan` says "one method" and import_grid
goes on as before.  `python bifin_regions.py FILE` prints the map (T text, B block, L line, N tone, X mix).
"""
from __future__ import print_function

import copy
import re
import sys

import bifin_text as T

BLACK = (0, 0, 0)
GAP_TEXT = 2            # blank cells that still join two words into one line of text
GAP_ART = 3             # blank cells (across) between two pieces of art that still make one piece
GAP_ART_Y = 1           # and blank rows
MIN_TEXT_CHARS = 5      # a lone word shorter than this is not a line of text
MAX_PUNCT = 0.25        # a line of text is mostly letters and digits: this share of it at most is punctuation
PIXEL_SHARE = 0.3       # a piece of art that is more than this much pixels is a picture (bifin_text.classify's own limit)
TINY = 6                # a piece of art of fewer characters than this is drawn as line art, whatever it looks like alone
MIN_PIECE = 8           # a piece of a `mix` drawing of fewer characters than this stays with the fill (as `mix`)
FLANK = 2             # drawing this near (blank cells) to the side of a line of text makes it part of the drawing
GAP_NUMBER = 9         # a number this near a line of text (columns of a tab) belongs to it
_NUMBER = re.compile(r"^[0-9][0-9.:/,-]*[0-9]$")

TEXT, BLOCK, LINE, TONE, MIX = "text", "block", "line", "tone", "mix"
SYMBOL = {TEXT: "T", BLOCK: "B", LINE: "L", TONE: "N", MIX: "X"}
ORDER = (BLOCK, TONE, MIX, LINE, TEXT)          # bottom first


class Plan(object):
    """labels[y][x]: None (blank) or one of the method names above; `modes` the set of those in use."""

    def __init__(self, labels):
        self.labels = labels
        self.modes = set(m for row in labels for m in row if m)

    def count(self, mode):
        return sum(1 for row in self.labels for m in row if m == mode)

    @property
    def mixed(self):
        """More than one method needed?  Line art with its words is one: bifin_text's line mode sets words in the font
        (with the extra text cells from the plan)."""
        return len(self.modes - set([TEXT])) > 1 or (TEXT in self.modes and bool(self.modes - set([TEXT, LINE])))

    def cells(self, mode):
        return [[m == mode for m in row] for row in self.labels]


# --------------------------------------------------------------------------
# What a cell is
# --------------------------------------------------------------------------
def kind_of(c, bg):
    """'b' blank, 'p' a pixel (block, braille, a colour behind it), 'c' a character."""
    if c == " ":
        if bg is None or bg == BLACK:
            return "b"
        return "p"
    if T.is_block(c) or T.is_braille(c):
        return "p"
    if bg is not None and bg != BLACK:
        return "p"
    return "c"


def kinds(grid):
    return [[kind_of(grid.ch[y][x], grid.bg[y][x]) for x in range(grid.cols)] for y in range(grid.rows)]


# --------------------------------------------------------------------------
# Text: words and what lies between them
# --------------------------------------------------------------------------
_INSIDE = set(".-_/:',+")       # what may stand inside a word or a number: 4.9.232-ga8, x86_64, /dev/tty, can't, 7,1
_VOWELS = set("aeiouAEIOU")


def _token_class(tok):
    """'S' a word (3 letters or more, clean, not one repeated fill character, not random letters), 'W' a number or
    a short code (`OS:`, `19H4`, `i7`), 'P' punctuation and drawing characters.  The letters of shading art
    (`loolloddol`, `PHPnIgBm`, `,tyxfyi`) are meant to fail."""
    n = len(tok)
    alnum = [i for i, c in enumerate(tok) if c.isalnum()]
    if not alnum:
        return "P"
    lo, hi = alnum[0], alnum[-1]
    core = tok[lo:hi + 1]
    if lo > 2 or n - 1 - hi > 2 or lo + n - 1 - hi > 3:
        return "P"                                        # `.;loddo:'`: more drawing than word
    if any(not (c.isalnum() or c in _INSIDE) for c in core):
        return "P"                                        # `\Xt`, `"m|`, `0%|,,>Xz`
    letters = [c for c in core if c.isalpha()]
    if len(letters) < 3:
        return "W"
    if not any(c in _VOWELS for c in letters) and not all(c.isupper() for c in letters):
        return "W"                                        # gHz, nHr: letters, but not a word
    caps = 0
    while caps < len(letters) and letters[caps].isupper():
        caps += 1
    if len(letters) == 3 and caps not in (0, 3) and not (caps == 1 and letters[1].islower() and letters[2].islower()):
        return "W"                                        # ABz, OBr: three letters, but not Aaa, AAA or aaa
    if len(letters) == 3 and caps == 0 and not all(c.islower() for c in letters):
        return "W"                                        # gBe
    if caps >= 3 and caps < len(letters) and len(letters) - caps < caps - 1:
        return "W"                                        # IRDDc: capitals with one lower-case letter after them
    if len(alnum) < 0.6 * n:
        return "P"
    top = max(core.count(c) for c in set(core))
    if len(core) >= 4 and top >= 0.6 * len(core):
        return "P"                                        # MMMMMMMM, 88888: fill, not a word
    if all(c in T._SHAPEY for c in letters):
        return "P"                                        # (oo) vv
    if len(core) >= 6 and len(set(core)) < 0.4 * len(core):
        return "P"                                        # a few letters over and over
    flips = sum(1 for a, b in zip(letters, letters[1:]) if a.isupper() != b.isupper())
    if flips > 3:
        return "P"                                        # PHPnIgBm: not a word
    return "S"


def _runs(row, kind, gap):
    """Lines of tokens on one row: [[(x0, x1, token), ...], ...], words joined while the blank between them is `gap`
    cells or less.  Only 'c' cells make tokens."""
    cols = len(row)
    toks = []
    x = 0
    while x < cols:
        if kind[x] != "c":
            x += 1
            continue
        e = x
        while e < cols and kind[e] == "c" and row[e] != " ":
            e += 1
        toks.append((x, e, "".join(row[x:e])))
        x = e
    runs = []
    for t in toks:
        if runs and t[0] - runs[-1][-1][1] <= gap:
            runs[-1].append(t)
        else:
            runs.append([t])
    return runs


def text_cells(grid, kind):
    """Cells that are prose.  A line of words is text when it holds two words, or a word and a number (`Uptime: 5
    hours`), and the punctuation and numbers between its words come with them; punctuation at its ends does not
    (the `<` `>` of a cowsay bubble stay drawing).  A line of one word is text too when nothing but text is
    beside it (a caption under a logo), not when it sits in a drawing."""
    rows, cols = grid.rows, grid.cols
    text = [[False] * cols for _ in range(rows)]
    clean = {}                                            # rows of text with nothing trimmed from their ends
    lone, rules, numbers = [], [], []

    def mark(y, toks):
        classes = [_token_class(t[2]) for t in toks]
        lo, hi = 0, len(toks) - 1
        while lo <= hi and classes[lo] == "P":
            lo += 1
        while hi >= lo and classes[hi] == "P":
            hi -= 1
        for t in toks[lo:hi + 1]:
            for x in range(t[0], t[1]):
                text[y][x] = True
        if lo == 0 and hi == len(toks) - 1:
            clean.setdefault(y, []).append((toks[0][0], toks[-1][1]))

    def punctuation(run):
        chars = "".join(t[2] for t in run)
        return sum(1 for c in chars if not c.isalnum()) / float(len(chars))

    def pieces(y):
        """The runs of the row, cut at any long stretch of drawing characters (`vR&5)z@Hv`): that is not between words."""
        for run in _runs(grid.ch[y], kind[y], GAP_TEXT):
            part = []
            for t in run:
                if len(t[2]) > 3 and _token_class(t[2]) == "P":
                    if part:
                        yield part
                    part = []
                    yield [t]
                else:
                    part.append(t)
            if part:
                yield part

    for y in range(rows):
        for run in pieces(y):
            classes = [_token_class(t[2]) for t in run]
            s, w = classes.count("S"), classes.count("W")
            if (s >= 2 or (s >= 1 and w >= 1)) and punctuation(run) <= MAX_PUNCT:
                mark(y, run)
            elif s == 1 and len(run) <= 2 and sum(len(t[2]) for t in run) >= MIN_TEXT_CHARS and punctuation(run) <= MAX_PUNCT:
                lone.append((y, run))
            elif len(run) == 1 and len(run[0][2]) >= 3 and len(set(run[0][2])) == 1 and not run[0][2][0].isalnum():
                rules.append((y, run[0][0], run[0][1]))   # ----- or ===== : an underline, perhaps
            elif len(run) <= 2 and all(_NUMBER.match(t[2]) for t in run):
                numbers.append((y, run))
    for y, run in numbers:                                # 11.4 after a word, a tab away
        a, b = run[0][0], run[-1][1]
        if any(text[y][x] for x in range(max(0, a - GAP_NUMBER), min(cols, b + GAP_NUMBER))):
            mark(y, run)
    rule_cells = set((y, x) for y, a, b in rules for x in range(a, b))
    for y, run in lone:                                   # a single word: text if only text is near it
        x0, x1 = run[0][0], run[-1][1]
        near = False
        for yy in range(max(0, y - 1), min(rows, y + 2)):
            for xx in range(max(0, x0 - GAP_TEXT), min(cols, x1 + GAP_TEXT)):
                if (kind[yy][xx] != "b" and not text[yy][xx] and not (yy == y and x0 <= xx < x1)
                        and (yy, xx) not in rule_cells):
                    near = True
        if not near:
            mark(y, run)
    for y, a, b in rules:                                 # an underline of a line of text (not a cowsay bubble's edge)
        for yy in (y - 1, y + 1):
            if any(a <= x1 and x0 < b for x0, x1 in clean.get(yy, ())):
                for x in range(a, b):
                    text[y][x] = True
    # Words with drawing right beside them are part of the drawing (shading made of letters, a cowsay bubble): the
    # drawing characters within FLANK blanks of a line of text on either side take it back.
    for y in range(rows):
        x = 0
        while x < cols:
            if not text[y][x]:
                x += 1
                continue
            a, b = x, x + 1                              # a segment [a, b): text cells less than GAP_TEXT blanks apart
            k = b
            while k < cols and k <= b + GAP_TEXT:
                if text[y][k]:
                    b = k + 1
                k += 1
            beside = list(range(max(0, a - FLANK - 1), a)) + list(range(b, min(cols, b + FLANK + 1)))
            if any(kind[y][k] != "b" and not text[y][k] for k in beside):
                for k in range(a, b):
                    text[y][k] = False
            x = b
    return text


# --------------------------------------------------------------------------
# Pieces: cells that lie close together
# --------------------------------------------------------------------------
def components(mask, gx, gy):
    """Groups of True cells, a cell joining any other within gx columns and gy rows: [[(y, x), ...], ...]."""
    rows, cols = len(mask), len(mask[0]) if mask else 0
    seen = [[False] * cols for _ in range(rows)]
    out = []
    for y0 in range(rows):
        for x0 in range(cols):
            if not mask[y0][x0] or seen[y0][x0]:
                continue
            seen[y0][x0] = True
            stack, comp = [(y0, x0)], []
            while stack:
                y, x = stack.pop()
                comp.append((y, x))
                for yy in range(max(0, y - gy), min(rows, y + gy + 1)):
                    srow, mrow = seen[yy], mask[yy]
                    for xx in range(max(0, x - gx), min(cols, x + gx + 1)):
                        if mrow[xx] and not srow[xx]:
                            srow[xx] = True
                            stack.append((yy, xx))
            out.append(comp)
    return out


def masked(grid, keep, plain=False):
    """A copy of the grid that holds only the cells where `keep` is True.  plain: without the black behind a
    character (a terminal screen that says `black` for every cell is not a picture of pixels)."""
    ch = [[grid.ch[y][x] if keep[y][x] else " " for x in range(grid.cols)] for y in range(grid.rows)]
    fg = [[grid.fg[y][x] if keep[y][x] else None for x in range(grid.cols)] for y in range(grid.rows)]
    bg = [[grid.bg[y][x] if keep[y][x] and not (plain and kind_of(ch[y][x], grid.bg[y][x]) != "p") else None
           for x in range(grid.cols)] for y in range(grid.rows)]
    return T.Grid(ch, fg, bg, grid.vga)


def _mask_of(rows, cols, cells):
    m = [[False] * cols for _ in range(rows)]
    for y, x in cells:
        m[y][x] = True
    return m


def plan(grid, o=None):
    """Which method suits each cell: a Plan.  `o`: bifin_text.Options (the shade characters)."""
    rows, cols = grid.rows, grid.cols
    labels = [[None] * cols for _ in range(rows)]
    if not rows or not cols:
        return Plan(labels)
    kind = kinds(grid)
    text = text_cells(grid, kind)
    art = [[kind[y][x] != "b" and not text[y][x] for x in range(cols)] for y in range(rows)]
    for y in range(rows):
        for x in range(cols):
            if text[y][x]:
                labels[y][x] = TEXT
    shade = o.shade if o is not None else "X"
    for comp in components(art, GAP_ART, GAP_ART_Y):
        pix = [(y, x) for y, x in comp if kind[y][x] == "p"]
        if len(pix) > PIXEL_SHARE * len(comp):                # a picture (that has a few characters in it)
            for y, x in comp:
                labels[y][x] = BLOCK
            continue
        for y, x in pix:
            labels[y][x] = BLOCK
        rest = [(y, x) for y, x in comp if kind[y][x] == "c"]
        if len(rest) < TINY:
            picked = LINE                                     # a stray character or two: with the drawing round it
        else:
            sub = masked(grid, _mask_of(rows, cols, rest), plain=True)
            picked, _st = T.classify(sub, T.shade_cells(sub, shade))
            if picked == "block":
                picked = TONE
        if picked == MIX:
            split_mix(grid, rest, labels, shade)
            continue
        for y, x in rest:
            labels[y][x] = picked
    return Plan(labels)


def split_mix(grid, rest, labels, shade):
    """A piece of art that came out `mix` (fill characters and strokes together) often is two things that touch: a
    shaded logo and a title in figlet beside it.  The fill (a run of dense characters and what clings to it) becomes
    `tone`; every other piece of at least MIN_PIECE characters is classified by itself (figlet: `line`).  What is
    left over (the commas and quotes that stand among the 8s of a toilet-style title) stays with the fill, as `mix`."""
    rows, cols = grid.rows, grid.cols
    base = set((y, x) for y, x in rest if grid.ch[y][x] in T.DENSE)
    run = set(c for c in base if (c[0], c[1] - 1) in base or (c[0], c[1] + 1) in base)
    fill = set(run)
    for y, x in base - run:                               # a lone @ on the edge of a run (the antennae)
        if any((y + dy, x + dx) in run for dy in (-1, 0, 1) for dx in (-1, 0, 1)):
            fill.add((y, x))
    others = [c for c in rest if c not in fill]
    pieces, leftover = [], []
    if len(fill) >= MIN_PIECE:
        mask = [[False] * cols for _ in range(rows)]
        for y, x in others:
            mask[y][x] = True
        for comp in components(mask, 2, 1):
            (pieces if len(comp) >= MIN_PIECE else leftover).extend([comp] if len(comp) >= MIN_PIECE else comp)
    if not pieces:
        for y, x in rest:
            labels[y][x] = MIX
        return
    for comp in pieces:
        sub = masked(grid, _mask_of(rows, cols, comp), plain=True)
        picked, _st = T.classify(sub, T.shade_cells(sub, shade))
        picked = LINE if picked in (BLOCK, MIX) else picked
        for y, x in comp:
            labels[y][x] = picked
    for y, x in fill:
        labels[y][x] = MIX if leftover else TONE
    for y, x in leftover:
        labels[y][x] = MIX if leftover else LINE


def show(plan_):
    return "\n".join("".join(SYMBOL.get(m, " ") if m else " " for m in row).rstrip() for row in plan_.labels)


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------
def _cell_size(grid, o, modes):
    """The cell width import_grid would end up with (a huge picture is drawn smaller) when the strictest budget of
    the methods in use applies."""
    cw = max(4, int(o.cell_w))
    cw += cw % 2
    budget = 24e6 if modes & set([TONE, MIX, BLOCK]) else 48e6
    ch = max(4, int(round(cw * o.aspect / 4.0)) * 4)
    while cw > 4 and (grid.rows * ch + 2 * cw) * (grid.cols * cw + 2 * cw) > budget:
        cw -= 2
        ch = max(4, int(round(cw * o.aspect / 4.0)) * 4)
    return cw


def _dark_page(grid, o, pl):
    """Is the page black?  As for colour block art: when there is a picture of pixels in colour, or the art says it
    is a dark screen (nearly every cell has a black background of its own)."""
    if o.paper is not None:
        return sum(o.paper) < 3 * 128
    dark = o.dark if o.dark is not None else grid.has_color()
    if BLOCK in pl.modes and dark:
        return True
    occupied = black = 0
    for y in range(grid.rows):
        for x in range(grid.cols):
            if pl.labels[y][x]:
                occupied += 1
                if grid.bg[y][x] == BLACK:
                    black += 1
    return bool(dark and occupied and black >= 0.5 * occupied)


def import_mixed(grid, o, info, pl):
    """Grid + plan -> bif.Picture: each method draws its own cells, on one canvas, one palette."""
    import bif
    import bifop

    if info is None:
        info = {}
    modes = [m for m in ORDER if m in pl.modes]
    cw = _cell_size(grid, o, pl.modes)
    dark = _dark_page(grid, o, pl)
    paper_c = o.paper if o.paper is not None else ((0, 0, 0) if dark else (255, 255, 255))
    ink_c = o.ink if o.ink is not None else (((170, 170, 170) if grid.vga else (229, 229, 229)) if dark else (0, 0, 0))
    use_color = o.color == "on" or (o.color == "auto" and grid.has_color())
    if info.get("palette") is None:
        info["palette"] = T._Palette(ink_c, paper_c)
    T._log(o, "mixed:", ", ".join("%s %d" % (m, pl.count(m)) for m in modes), "cells; page", "dark" if dark else "light")

    so = copy.copy(o)
    so.cell_w, so.ink, so.paper, so.crop, so.cells, so.keep_source = cw, ink_c, paper_c, False, False, False
    so.dark = dark if o.dark is None else o.dark
    so.color = "on" if use_color else "off"
    pics = []
    for m in modes:
        sub = masked(grid, pl.cells(m))
        so.mode = m
        sinfo = dict(info)
        if m in (LINE, MIX):                             # the line art's words: from the font, whatever the characters
            sinfo["text_cells"] = pl.cells(TEXT)
        pics.append((m, T.import_grid(sub, so, sinfo)))
    base = pics[0][1]
    seen = {}
    layers = []
    for m, p in pics:
        for L in p.frames[0].layers:
            n = seen.get(L.id, 0)
            seen[L.id] = n + 1
            if n:
                L.props["id"] = "%s-%s" % (L.id, m)
            layers.append(L)
    order = {"picture": 0, "tone": 0, "hatch": 1, "text-mask": 2, "text": 2, "strokes": 3}
    layers.sort(key=lambda L: order.get(str(L.id).split("-")[0], 9))
    base.frames[0].layers = layers
    base.palette = info["palette"].entries
    if o.cells and grid.rows and grid.cols:
        base.frames[0].layers.append(T._cells_layer(grid))
    base.meta["mode"] = "mixed"
    base.meta["polarity"] = "light-on-dark" if dark else "dark-on-light"
    base.meta["regions"] = dict((m, pl.count(m)) for m in modes)
    gen = base.meta.setdefault("generator", {})
    gen["args"] = T._dict_of_options(o)
    if o.keep_source and isinstance(info.get("data"), bytes):
        import os
        base.source = (os.path.basename(o.name or ""), info["data"])
    if o.crop:
        m = 0 if modes == [BLOCK] else int(0.5 * cw)
        bifop.op_crop(base, bifop.Notes(), margin=m, box=None)
    return base


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        sys.exit("usage: bifin_regions.py FILE [cols]")
    with open(argv[0], "rb") as f:
        data = f.read()
    text, enc = T.decode2(data, None)
    grid = T.parse(text, int(argv[1]) if len(argv) > 1 else 0, rows=24, glyphs=enc in ("cp437", "437"))
    pl = plan(grid, T.Options())
    print(show(pl))
    print("modes:", sorted(pl.modes), "mixed" if pl.mixed else "one method")


if __name__ == "__main__":
    main()
