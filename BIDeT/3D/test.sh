#!/usr/bin/env bash
# Smoke test: every preset, a few shapes/views, and animation, all to PNG/stdout.
cd "$(dirname "$0")"
py=${PYTHON:-python3}; command -v "$py" >/dev/null || py=python
out=$(mktemp -d)
fail=0
for p in $($py bidet3d.py --list-presets | tr -d '\r'); do
  $py bidet3d.py -P "$p" --png "$out/$p.png" "WordArt" && [ -s "$out/$p.png" ] || { echo "FAIL $p"; fail=1; }
done
$py bidet3d.py --shape wave --yaw -30 --pitch 12 --png "$out/wave.png" "Wave" || fail=1
$py bidet3d.py -b white -P arc --png "$out/white.png" "On white" || fail=1
echo "rendered $(ls "$out"/*.png | wc -l) PNGs in $out"
# the other output formats (the gfx-conv converters); need no libsixel
for f in kitty iterm ansi tek tek-dots tek-contour; do
  $py bidet3d.py -F $f --cell 9x18 --max-width 400 "Hi" > "$out/f.$f" && [ -s "$out/f.$f" ] || { echo "FAIL --format $f"; fail=1; }
done
head -c 8 "$out/f.kitty" | grep -q $'^\x1b_Ga=T' || { echo "FAIL --format kitty header"; fail=1; }
echo "output formats ok"
# ASCII art: redrawn as a line drawing by unascii (the default in art mode), the old glyphs,
# and a picture piped in from unascii as the shape
if [ -f unascii/unascii.py ]; then
  art=$'  ___\n (o o)\n  \\_/ \n /| |\\\n  | |'
  printf '%s\n' "$art" | $py bidet3d.py --png "$out/art.png" && [ -s "$out/art.png" ] || { echo "FAIL art lineart"; fail=1; }
  printf '%s\n' "$art" | $py bidet3d.py --no-lineart --png "$out/art-glyphs.png" && [ -s "$out/art-glyphs.png" ] || { echo "FAIL art --no-lineart"; fail=1; }
  printf '%s\n' "$art" | $py bidet3d.py --lineart=tone --pen 3 --png "$out/art-tone.png" || { echo "FAIL --lineart=tone"; fail=1; }
  printf '%s\n' "$art" | $py unascii/unascii.py -w 2 -o - | $py bidet3d.py --png "$out/art-pipe.png" && [ -s "$out/art-pipe.png" ] \
    || { echo "FAIL unascii | bidet3d"; fail=1; }
  echo "lineart + image input ok"
fi
if command -v img2sixel >/dev/null || $py -c "import libsixel" 2>/dev/null; then
  $py bidet3d.py -P chrome "Hello, SIXEL" > "$out/t.six" && head -c 2 "$out/t.six" | grep -q $'\x1bP' || { echo "FAIL sixel"; fail=1; }
  $py bidet3d.py --spin --frames 3 --fps 5 --spin-speed 120 -P superhero "Spin" >/dev/null || fail=1
    tm=$($py bidet3d.py --time-machine --stage-time 0.05 --frames 2 --fps 5 --force -b black "Hi" 2>/dev/null)
  case $tm in *1983*1991*2004*2020*2026*) ;; *) echo "FAIL time-machine"; fail=1;; esac
  echo "sixel + animation + time-machine ok"
else
  echo "(no libsixel found: skipping SIXEL checks)"
fi
[ $fail = 0 ] && echo PASS || { echo FAILED; exit 1; }
