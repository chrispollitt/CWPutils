#!/bin/sh
# Run the BIF tests: the library and reference files, the renderer / SIXEL / bifout, the importer / bifin,
# then the parity gate against the frozen v3 in tests/reference (a few minutes).  Self-contained: nothing
# here needs the legacy ../3D (which now holds gfx-conv/ and unascii/); only the optional SIXEL decoder test looks in it.
#   ./test.sh            the tests
#   ./test.sh --regen    regenerate testdata/ first (only when the spec or the generator changed)
cd "$(dirname "$0")" || exit 1
PY=${PYTHON:-python3}
command -v "$PY" >/dev/null 2>&1 || PY=python
[ "$1" = "--regen" ] && { "$PY" tests/make_testdata.py || exit 1; }
"$PY" -W ignore tests/test_bif.py || exit 1
"$PY" -W ignore tests/test_bifout.py || exit 1
"$PY" -W ignore tests/test_bifin.py || exit 1
exec "$PY" -W ignore tests/test_parity.py
