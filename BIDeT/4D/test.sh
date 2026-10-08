#!/bin/sh
# Run the BIF tests: the library and reference files, the renderer / SIXEL / bifout, the importer / bifin, the
# tone tracer, then the parity gate against the frozen v3 in tests/reference.  Self-contained: nothing here needs
# the legacy ../3D (which now holds gfx-conv/ and unascii/); only the optional SIXEL decoder test looks in it.
#   ./test.sh            everything, including the full parity matrix (about 10 minutes)
#   ./test.sh --quick    the same suites, but a smoke subset of the parity gate (about 3 minutes in all)
#   ./test.sh --regen    regenerate testdata/ first (only when the spec or the generator changed)
cd "$(dirname "$0")" || exit 1
PY=${PYTHON:-python3}
command -v "$PY" >/dev/null 2>&1 || PY=python
for a in "$@"; do
    case "$a" in
        --regen) "$PY" tests/make_testdata.py || exit 1 ;;
        --quick) PARITY_QUICK=1; export PARITY_QUICK ;;
        *) echo "usage: $0 [--quick] [--regen]" >&2; exit 2 ;;
    esac
done
"$PY" -W ignore tests/test_bif.py || exit 1
"$PY" -W ignore tests/test_bifout.py || exit 1
"$PY" -W ignore tests/test_bifin.py || exit 1
"$PY" -W ignore tests/test_tonetrace.py || exit 1
"$PY" -W ignore tests/test_bifop.py || exit 1
exec "$PY" -W ignore tests/test_parity.py
