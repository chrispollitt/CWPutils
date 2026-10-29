#!/bin/bash
# A prompt for bidet to run behind ttyd.  It is not a shell: a line is text to
# draw, optionally after "preset[,preset]:".  Text is always forced (-t), so a
# line can name no file and no raw option, and nothing is written to disk.
here=$(cd "$(dirname "$0")/.." && pwd)
py=${BIDET_PY:-python3}
maxlen=200

# --foreground: without it bidet is stopped (SIGTTIN) when it asks the terminal what it is
bidet() { timeout --foreground 30 "$py" "$here/bidet.py" "$@"; }

trap : INT
presets=$(bidet -l | awk '{print $1}')

cat <<'EOF'
BIDeT 4D on the web: text in, picture out.

  Hello                    draw "Hello"
  arc,matrix: Hello        with presets (arc, then matrix)
  presets                  list the presets
  help                     this text      quit  (or Ctrl-D): leave

EOF

while IFS= read -e -r -p 'bidet> ' line; do
  case $line in
    ''|*[![:print:]]*) continue ;;
    quit|exit) break ;;
    help) echo "text, or  preset[,preset]: text ;  presets ; quit"; continue ;;
    presets) bidet -l; continue ;;
  esac
  args=()
  text=$line
  if [[ $line =~ ^([A-Za-z0-9_,-]+):[[:space:]]*(.+)$ ]]; then
    text=${BASH_REMATCH[2]}
    IFS=, read -ra names <<<"${BASH_REMATCH[1]}"
    for p in "${names[@]}"; do
      grep -qx -- "$p" <<<"$presets" || { echo "no such preset: $p (try: presets)"; continue 2; }
      args+=(-P "$p")
    done
  fi
  if (( ${#text} > maxlen )); then echo "too long (max $maxlen characters)"; continue; fi
  bidet "${args[@]}" -t -- "$text"
done
