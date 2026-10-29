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
exec "${TTYD:-ttyd}" -W -i "${IFACE:-lo}" -p "${PORT:-7682}" -m "${MAX_CLIENTS:-4}" \
  -T xterm-256color -t enableSixel=true -t titleFixed="BIDeT 4D" ${BASE:+-b "$BASE"} \
  "$here/bidet-web.sh"
