#!/usr/bin/env bash
# Smoke test: every sample in each mode to PNG, SIXEL framing, the pipeline into bidet3d, ANSI parsing.
cd "$(dirname "$0")"
py=${PYTHON:-python3}; command -v "$py" >/dev/null || py=python
out=$(mktemp -d)
fail=0
for f in samples/*.txt samples/*.ans; do
  b=$(basename "$f")
  for m in auto line tone mix; do
    $py unascii.py -m $m "$f" -o "$out/$b.$m.png" && [ -s "$out/$b.$m.png" ] || { echo "FAIL $b -m $m"; fail=1; }
  done
done
echo "rendered $(ls "$out"/*.png | wc -l) PNGs in $out"
$py unascii.py samples/cow.txt -s | head -c 2 | grep -q $'\x1bP' || { echo "FAIL sixel header"; fail=1; }
$py unascii.py samples/cow.txt -s | tail -c 3 | grep -q $'\x1b\\\\' || { echo "FAIL sixel terminator"; fail=1; }
$py - <<'EOF' || fail=1
import sys
import numpy as np
import unascii as u
# mode choice on the shipped samples
want = {"cow": "line", "turkey": "line", "figlet_std": "line", "tone80": "tone", "tone100_inv": "tone",
        "braille": "tone"}
for name, mode in want.items():
    g = u.parse(u.decode(open("samples/%s.txt" % name, "rb").read()))
    got = u.classify(g)[0]
    if got != mode:
        sys.exit("FAIL classify %s: %s, want %s" % (name, got, mode))
# cowsay bubbles close at the bottom: the - run is found (one and several rows), other dashes are not
for art, rows in ((" _____\n< hi! >\n -----\n", {2}), (" ______\n/ a    \\\n\\ b    /\n ------\n", {3}),
                  (" --- x ---\n   -----\n", set())):
    got = {y for y, x in u.bubble_bottoms(u.parse(art))}
    assert got == rows, (art, got)
# runs of X are shading (a lone X, and the X in a word, are not); words made of them are not text
sh = u.shade_cells(u.parse("-XXX(\n  X  \nX Y Xe"), "X")
assert sh[0][1:4] == [True] * 3 and sh[1][2] and not sh[0][0] and not sh[2][0] and not sh[2][4], sh
assert u.shade_cells(u.parse("a b c"), "X") is None
assert not any(any(r) for r in u.word_cells(u.parse("XXX"), u.shade_cells(u.parse("XXX"), "X")))
# the spline keeps its ends and corners, straightens a staircase, and leaves a right angle alone
st = [[0, 0, False], [12, 0, True], [12, 10, True], [24, 10, True], [24, 20, True], [36, 20, False]]
sm = u.spline_smooth(st, 8, 1.2, 80, 100, 13)
assert abs(sm[0][0]) < 1e-6 and abs(sm[-1][0] - 36) < 1e-6 and abs(sm[-1][1] - 20) < 1e-6
dev = lambda pts: max(abs(p[1] - p[0] * 20 / 36.0) for p in pts)
assert len(sm) > len(st) and dev(sm) < 0.7 * dev(st), (dev(sm), dev(st))        # hugs the diagonal
ell = [[0, 0, False], [30, 0, True], [30, 30, False]]
assert [(round(p[0]), round(p[1])) for p in u.spline_smooth(ell, 8, 1.2, 80, 100, 13)] == [(0, 0), (30, 0), (30, 30)]
# ANSI: colours, cursor movement, reverse video, CP437 + SAUCE
g = u.parse("\x1b[31mA\x1b[0m\x1b[3CB\x1b[2;1HC")
assert (g.rows, g.cols) == (2, 5) and g.fg[0][0] == u.xterm_color(1) and g.ch[0][4] == "B" and g.ch[1][0] == "C"
assert u.decode(b"\xdb\xdf\x1aSAUCE00" + b"\0" * 120) == "█▀"
# words are text, eyes are not
t = u.word_cells(u.parse("Moo (oo)"))
assert t[0][0] and t[0][2] and not t[0][5] and not t[0][6]
# mask API: right size, ink only where lines are
m = u.mask("/\\\n\\/", 12, 24)
assert m.mode == "L" and 0 < m.getextrema()[1] <= 255 and m.size[0] > 20
# sixel is well framed and every band ends with a line feed
s = u.sixel(u.render("-+-", cell_w=8))
assert s.startswith(b"\x1bP") and s.endswith(b"\x1b\\") and b"-" in s
# a terminal, not a text file: cursor addressing is clamped to the screen (ESC[9999;1H), OSC strings
# are swallowed, scrolling keeps the history, a scroll region scrolls alone, DEC line drawing, CP437 pictures
g = u.parse("\x1b[9999S\x1b[9999;1H\x1b]4;16;rgb:00/00/00\x1b\\ok")
assert g.rows < 30 and "".join(g.ch[-1]).strip() == "ok", g.rows
g = u.parse("\n".join("line%d" % i for i in range(40)))
assert g.rows == 40 and "".join(g.ch[0]).strip() == "line0"
assert "".join(u.parse("\x1b(0lqqk\x1b(B").ch[0]) == "┌──┐"
g = u.parse("T\x1b[2;4r\x1b[2;1Ha\nb\nc\nd", rows=6)
assert ["".join(r).strip() for r in g.ch] == ["T", "b", "c", "d"], g.ch
assert u.parse("A\x1b[2;1HB\x1bM\x1b[1;1HC", rows=3).ch[0][0] == "C"
assert u.parse("\x03", glyphs=True).ch[0][0] == "♥" and u.parse("\x03").ch[0][0] == " "
# colour: strokes keep their cell's colour, uncoloured art has none, grey becomes the ink and
# yellow is darkened to be readable on white, a coloured SIXEL is framed and the right size
ink, rgb = u.render_color("\x1b[31m/\\\\\x1b[0m\n", mode="line", cell_w=12)
assert rgb is not None and rgb.shape[:2] == ink.shape
red = rgb[ink > 0.5].astype(float).mean(0)
assert red[0] > 150 and red[1] < 60 and red[2] < 60, red
assert u.render_color("/\\\\", mode="line")[1] is None and u.render_color("\x1b[31m/\\\\", color="off")[1] is None
lg = u.legible(np.array([[255., 255., 0.], [200., 200., 200.], [0., 0., 238.]]), (0, 0, 0), (255, 255, 255))
assert u.lum(lg[0]) <= 0.6 and tuple(lg[1]) == (0, 0, 0) and lg[2][2] == 238
assert u.render_color("\x1b[41m    \x1b[44m    \n" * 3, mode="tone", cell_w=8)[1] is not None
sx = u.sixel(ink, rgb=rgb)
assert sx.startswith(b"\x1bP") and sx.endswith(b"\x1b\\") and (b'"1;1;%d;%d' % (ink.shape[1], ink.shape[0])) in sx
print("library checks ok")
EOF
if [ -f ../3D/bidet3d.py ]; then
  $py unascii.py samples/cow.txt -w 2 -o - | $py ../3D/bidet3d.py -b black --png "$out/pipe.png" && [ -s "$out/pipe.png" ] \
    || { echo "FAIL pipe into bidet3d"; fail=1; }
  echo "pipe into bidet3d ok"
fi
[ $fail = 0 ] && echo PASS || { echo FAILED; exit 1; }
