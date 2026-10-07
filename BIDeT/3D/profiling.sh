#!/bin/bash
#
# Profile BIDeT3D: where does the time go as the picture gets bigger?
#
#   profiling.sh [scale|compare|all]      (default: all)
#
#   scale    How render cost grows with font size (-s), terminal limit removed.
#            Per size: layer and final image size, build and render stage times
#            (from -d), wall/user/sys, and the slope of log(build+render) against
#            log(size) between rows (1 = linear, 2 = per-pixel, 3 = what -s 100
#            cost before fit_px(); more than ~2.5 deserves a look).
#   compare  bidet / bidet2 / bidet3d at default settings, SIXEL to /dev/null.
#
# Environment:
#   BIDET3D   program to test (default: the bidet3d.py next to this script; set it to
#             "bidet3d" to test the installed copy instead)
#   SIZES     sizes for 'scale' (default "16 24 32 48 64 80")
#   RUNS      repetitions per row (default 2)
#   NEWINPUT  set to regenerate profiling-input.txt (a fresh cowsay fortune); otherwise the
#             existing file is reused so runs are comparable

cd "$(dirname "$0")" || exit 1

mode=${1:-all}
BIDET3D=${BIDET3D:-./bidet3d.py}
SIZES=${SIZES:-16 24 32 48 64 80}
RUNS=${RUNS:-2}
LOG=profiling.log
INPUT=profiling-input.txt

command -v "$BIDET3D" >/dev/null || [ -x "$BIDET3D" ] || { echo "profiling.sh: $BIDET3D not found" >&2; exit 1; }

if [ -n "$NEWINPUT" ] || [ ! -s "$INPUT" ]; then
  fortune -s | cowsay > "$INPUT"
fi

err=$(mktemp) png=$(mktemp --suffix=.png)
trap 'rm -f "$err" "$png"' EXIT

: > "$LOG"
say() { tee -a "$LOG"; }

# run_avg RUNS cmd...   stdin from $INPUT, stderr kept in $err (last run).
# Sets avg_real avg_user avg_sys.
run_avg() {
  local n=$1 i out r u s sr=0 su=0 ss=0
  shift
  for ((i = 0; i < n; i++)); do
    out=$( { time -p "$@" < "$INPUT" 2>"$err" >/dev/null; } 2>&1 )
    r=$(awk '/^real/ {print $2}' <<<"$out")
    u=$(awk '/^user/ {print $2}' <<<"$out")
    s=$(awk '/^sys/  {print $2}' <<<"$out")
    sr=$(awk "BEGIN {print $sr + $r}"); su=$(awk "BEGIN {print $su + $u}"); ss=$(awk "BEGIN {print $ss + $s}")
  done
  avg_real=$(awk "BEGIN {printf \"%.2f\", $sr / $n}")
  avg_user=$(awk "BEGIN {printf \"%.2f\", $su / $n}")
  avg_sys=$(awk "BEGIN {printf \"%.2f\", $ss / $n}")
}

do_scale() {
  local save_term=$TERM
  # A huge virtual terminal (200x60 cells of 40x80 px; TERM=dumb because bidet3d caps
  # xterm at 1000 px wide) so that nothing is clamped
  # to the screen and -s really changes how many pixels get rendered.
  export COLUMNS=200 LINES=60 TERM=dumb
  echo "== scale: $BIDET3D -s N, $RUNS runs, input $(wc -l < "$INPUT") lines ==" | say
  printf '%5s %11s %11s %7s %7s %7s %7s %7s %6s\n' \
    size layer final build render real user sys slope | say
  local s prev_s= prev_w= w
  for s in $SIZES; do
    run_avg "$RUNS" "$BIDET3D" -d -s "$s" --cell 40x80 --png "$png" -
    local layer build render final capped
    layer=$(sed -n 's/.*layer=\([0-9x]*\).*/\1/p' "$err" | tail -1)
    build=$(sed -n 's/.*build=\([0-9.]*\)s.*/\1/p' "$err" | tail -1)
    render=$(sed -n 's/^render=\([0-9.]*\)s.*/\1/p' "$err" | tail -1)
    final=$(sed -n 's/.*final=\([0-9x]*\).*/\1/p' "$err" | tail -1)
    capped=$(grep -c 'does not fit' "$err")
    w=$(awk "BEGIN {print ${build:-0} + ${render:-0}}")
    local slope=-
    if [ -n "$prev_s" ]; then
      slope=$(awk "BEGIN {if ($prev_w > 0.05 && $w > 0) printf \"%.2f\", log($w / $prev_w) / log($s / $prev_s); else print \"-\"}")
    fi
    printf '%5s %11s %11s %7s %7s %7s %7s %7s %6s%s\n' \
      "$s" "$layer" "$final" "$build" "$render" "$avg_real" "$avg_user" "$avg_sys" "$slope" \
      "$([ "$capped" -gt 0 ] && echo '  CAPPED by terminal size: not measuring -s')" | say
    prev_s=$s prev_w=$w
  done
  unset COLUMNS LINES; export TERM=$save_term
  echo "(build and render are the in-process stages; real adds Python/Pillow startup and PNG save)" | say
}

do_compare() {
  echo "== compare: default settings, SIXEL to /dev/null, $RUNS runs ==" | say
  printf '%-10s %7s %7s %7s\n' prog real user sys | say
  local prog
  for prog in bidet bidet2 "$BIDET3D"; do
    command -v "$prog" >/dev/null || [ -x "$prog" ] || { echo "($prog not installed: skipped)" | say; continue; }
    local extra=
    [ "$prog" = "$BIDET3D" ] && extra="--force"
    run_avg "$RUNS" "$prog" $extra -
    printf '%-10s %7s %7s %7s\n' "$(basename "$prog")" "$avg_real" "$avg_user" "$avg_sys" | say
  done
}

case $mode in
  scale)   do_scale ;;
  compare) do_compare ;;
  all)     do_scale; echo | say; do_compare ;;
  *) echo "usage: $0 [scale|compare|all]" >&2; exit 2 ;;
esac
