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

`env2` has three modes for splitting the `#!` arguments (version 2.2); pick one with a flag:

    -S  --shellwords   like Perl's shellwords()           (the default since 2.0)
    -C  --classic      env2's original splitter           (implied by -s, -p, -x, so
                                                           older #! lines keep working)
    -W  --wordexp      like a POSIX shell, via wordexp()  (no commands are ever run)

See the QUOTING AND ESCAPES and COMPATIBILITY sections of the man page.

With `-E` (version 2.1), `${NAME}` in the `#!` line is replaced by the value of that
environment variable, as in GNU `env -S`; it is off unless a script asks for it.

See HISTORY for how the project got here, and TODO for what is left.

BUILD AND TEST
* `./configure`   - detect platform and kernel `#!` behaviour
* `make`          - build
* `make test`     - run the unit tests, plus configure tested against simulated
                    kernels (`make check` is the same; slow under Cygwin)
* `make lab`      - build env2 for each KERNEL_SPLIT, for shebanglab's env2 rows
* `make install`  - install under `PREFIX` (default /usr/local)
* `make clean` / `make distclean` - remove built files / also configure output

See INSTALL for requirements.

TESTED ON (`./configure && make test` passes; GNU make is `gmake` on Solaris)
* Cygwin (g++), Linux (g++, glibc), Solaris 11.4 (Studio `CC`), macOS 10.15 (Apple clang 12).
* Not tried: the BSDs.  They should behave like Linux (the kernel does not split the line), but
  note that the scripts use `#!/bin/bash`, and the BSD `make` is not GNU make.

SOURCES
* array_utils.cc           - split_args() (picks the splitter), join and merge arrays
* classic.cc               - split_classic(): env2's original splitter (-C)
* dumpargs.cc              - Print the argv array
* env2.cc                  - env2 itself (flag parsing, arg assembly, main)
* shellwords.cc            - split_shellwords(): a port of Perl's shellwords(), env2's default splitter
* sample_interpreter.cc    - Sample interpreters that use env2 components (variation 3 shows
                            how to parse your own #! switches with parse_switches())
* switches.cc             - parse_switches(): table-driven #! switch parser (used by env2)
* vars2.cc                 - read the config file and set env vars + interpreter flags
* wordexp.cc               - split_wordexp(): a POSIX shell's rules via wordexp() (env2 -W)
* da.cc                    - tiny helper that `configure` uses to probe kernel `#!` splitting

EXECUTABLES
* dumpargs                 - Dump the arguments to a shebang line
* env2                     - An env(1) replacement with more features
* shebanglab               - Perl tool: what a #! line gives the interpreter under different
                            kernels and helpers (direct, env, env2); see its man page
* sample_interpreter       - A sample interpreter that uses env2 components
* sample_script.si         - A sample script that calls the sample interpreter
