# BangHash
Unix / Linux Utilities

This is a collection of small utilities for Unix/Linux systems. They also work under Cygwin.

`env2` is an `env(1)` replacement aimed at `#!` lines. Its key feature is
splitting the interpreter argument string (which many kernels pass as a single
argument) into separate arguments. It can also read per-interpreter settings
from `~/.env2rc`, and under Cygwin the `w` flag converts the script path to
Windows format (like `cygpath -w`) for native Windows interpreters.

    #!/usr/local/bin/env2 -n perl -w
    #!/usr/local/bin/env2 -w python

Run `env2 -h` for the list of flags and `env2 -v` for the version.

Since version 2.0 `env2` splits the `#!` arguments like Perl's `shellwords()` by default.
The original splitter is still there as `-L` (and is selected by `-s`, `-p` and `-x`, so
older `#!` lines keep working); see the COMPATIBILITY section of the man page.

See HISTORY for how the project got here, and TODO for what is left.

BUILD AND TEST
* `./configure`   - detect platform and kernel `#!` behaviour
* `make`          - build
* `make test`     - run the unit tests, plus configure tested against simulated
                    kernels (`make check` is the same; slow under Cygwin)
* `make install`  - install under `PREFIX` (default /usr/local)
* `make clean` / `make distclean` - remove built files / also configure output

See INSTALL for requirements.

SOURCES
* array_utils.cc           - split string into array and merge arrays
* dumpargs.cc              - Print the argv array
* env2.cc                  - env2 itself (flag parsing, arg assembly, main)
* shellwords.cc            - split_shellwords(): a port of Perl's shellwords(), env2's default splitter
* sample_interpreter.cc    - Sample interpreters that use env2 components (variation 3 shows
                            how to parse your own #! switches with parse_switches())
* switches.cc             - parse_switches(): table-driven #! switch parser (used by env2)
* vars2.cc                 - read the config file and set env vars + interpreter flags
* da.cc                    - tiny helper that `configure` uses to probe kernel `#!` splitting

EXECUTABLES
* dumpargs                 - Dump the arguments to a shebang line
* env2                     - An env(1) replacement with more features
* sample_interpreter       - A sample interpreter that uses env2 components
* sample_script.si         - A sample script that calls the sample interpreter
