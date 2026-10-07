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
print("library checks ok")
EOF
if [ -f ../3D/bidet3d.py ]; then
  $py unascii.py samples/cow.txt -w 2 -o - | $py ../3D/bidet3d.py -b black --png "$out/pipe.png" && [ -s "$out/pipe.png" ] \
    || { echo "FAIL pipe into bidet3d"; fail=1; }
  echo "pipe into bidet3d ok"
fi
[ $fail = 0 ] && echo PASS || { echo FAILED; exit 1; }
