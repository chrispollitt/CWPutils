#!/bin/sh
# Serve bidet in a browser tab through ttyd (xterm.js), with SIXEL turned on in
# the client.  The session runs bidet-web.sh (a prompt, not a shell), but it is
# still a writable terminal, so keep it on one interface, "lo" by default, and
# put an SSH tunnel or an authenticating reverse proxy in front of it.
#
#   ./ttyd/run-ttyd.sh                  # http://127.0.0.1:7682/
#   BIDET_PY=$HOME/venvs/bidet/bin/python PORT=8082 ./ttyd/run-ttyd.sh
here=$(cd "$(dirname "$0")" && pwd)
if [ -z "$BIDET_PY" ] && [ -x "$HOME/venvs/bidet/bin/python" ]; then
  BIDET_PY=$HOME/venvs/bidet/bin/python
fi
export BIDET_PY
# Client options, to make the tab feel like a terminal and not a web page:
#   windowOptions  lets xterm.js answer CSI 14/16 t (pixel sizes), which bidet uses to size
#                  SIXEL pictures to the window; without it they are drawn too wide and cropped
#   disable*       no "leave this page?" prompt, no "80x24" overlay while resizing
#   macOptionIsMeta  Option acts as Meta, as in Terminal.app
# For no browser chrome at all, use F11, or the browser's "install as app" / "create shortcut".
exec "${TTYD:-ttyd}" -W -i "${IFACE:-lo}" -p "${PORT:-7682}" -m "${MAX_CLIENTS:-4}" \
  -T xterm-256color ${BASE:+-b "$BASE"} \
  -t enableSixel=true -t titleFixed="BIDeT 4D" \
  -t 'windowOptions={"getWinSizePixels":true,"getCellSizePixels":true,"getWinSizeChars":true}' \
  -t disableLeaveAlert=true -t disableResizeOverlay=true -t macOptionIsMeta=true \
  -t cursorBlink=true -t scrollback=10000 -t fontSize=15 \
  -t 'fontFamily=Cascadia Mono, Consolas, DejaVu Sans Mono, Menlo, monospace' \
  -t 'theme={"background":"#000000","foreground":"#e5e5e5"}' \
  "$here/bidet-web.sh"
