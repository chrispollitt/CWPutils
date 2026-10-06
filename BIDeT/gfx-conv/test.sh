#!/usr/bin/env bash
# Smoke test: decode a generated SIXEL picture and run every converter on it.
# Checks the byte-level framing; whether a terminal draws it is for your eyes.
cd "$(dirname "$0")"
py=${PYTHON:-python3}; command -v "$py" >/dev/null || py=python
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
fail=0
ok() { [ -s "$1" ] || { echo "FAIL $2"; fail=1; }; }

# a small picture with a transparent background: red disc, green square
$py - "$tmp/t.six" <<'PY' || { echo "FAIL make sixel"; exit 1; }
import sys
w, h = 60, 36
rows = []
for y in range(h):
    row = []
    for x in range(w):
        if (x - 30) ** 2 + (y - 18) ** 2 < 150: row.append(1)
        elif x < 10 and y < 10: row.append(2)
        else: row.append(0)
    rows.append(row)
out = ['\x1bPq"1;1;%d;%d#1;2;100;0;0#2;2;0;100;0' % (w, h)]
for top in range(0, h, 6):
    for c in (1, 2):
        s = ''
        for x in range(w):
            v = 0
            for k in range(6):
                if top + k < h and rows[top + k][x] == c: v |= 1 << k
            s += chr(63 + v)
        out.append('#%d%s$' % (c, s))
    out.append('-')
out.append('\x1b' + chr(92))
open(sys.argv[1], 'w', newline='').write(''.join(out))
PY
$py - "$tmp/t.six" <<'PY' || { echo "FAIL decode"; fail=1; }
import sys; sys.path.insert(0, '.')
import sixeldec
w, h, rgba = sixeldec.decode_rgba(open(sys.argv[1], 'rb').read())
px = lambda x, y: tuple(rgba[4 * (y * w + x):4 * (y * w + x) + 4])
assert (w, h) == (60, 36), (w, h)
assert px(30, 18) == (255, 0, 0, 255), px(30, 18)
assert px(2, 2) == (0, 255, 0, 255), px(2, 2)
assert px(55, 30)[3] == 0, px(55, 30)
PY
for m in hatch dots contour; do
  $py sixel2tek.py -m $m "$tmp/t.six" > "$tmp/$m.tek"; ok "$tmp/$m.tek" "sixel2tek $m"
done
for g in half quad blocks braille; do
  $py sixel2ans.py -x 30 -g $g "$tmp/t.six" > "$tmp/a.$g"; ok "$tmp/a.$g" "sixel2ans $g"
done
n=$($py sixel2ans.py -x 30 "$tmp/t.six" | wc -l)
[ "$n" -ge 5 ] || { echo "FAIL sixel2ans rows ($n)"; fail=1; }
grep -q $'\[' "$tmp/a.blocks" || { echo "FAIL sixel2ans has no colour codes"; fail=1; }
$py sixel2kitty.py "$tmp/t.six" > "$tmp/k"; ok "$tmp/k" kitty
$py sixel2iterm.py "$tmp/t.six" > "$tmp/i"; ok "$tmp/i" iterm
head -c 8 "$tmp/k" | grep -q $'^\033_Ga=T' || { echo "FAIL kitty header"; fail=1; }
head -c 20 "$tmp/i" | grep -q $'^\033\]1337;File=' || { echo "FAIL iterm header"; fail=1; }
[ $fail = 0 ] && echo PASS
exit $fail
