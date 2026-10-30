#!/bin/bash
# What runs behind ttyd: bidetsh.py, an imitation of a bash prompt.  It is not a shell: only bidet, a few text toys
# (figlet, toilet, cowsay, fortune ...) and some builtins run, joined by | ; && ||; text is always forced (-t) so
# nothing can name a file or a raw option, and nothing is written to disk.  See bidetsh.py.
here=$(cd "$(dirname "$0")" && pwd)
py=${BIDET_PY:-python3}
export BIDET_PY=$py
exec "$py" "$here/bidetsh.py"
