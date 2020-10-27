# CWPutils
Unix / Linux Utilities

This is a collection of small utilities for Unix/Linix systems. They also works under Cygwin.

SOURCES
dumpargs.cc              - Print the argv array
env2.cc                  - The main() function for env2
env2lib.cc               - Split out a string into an argv array
parse_flags.cc           - Parse out the flags to env2
vars2.cc                 - read the config file and set env vars + interpreter flags
sample_interpreter.cc    - A sample interpreter that uses env2 components
sample_script.si         - A sample script that calls the sample interpreter

EXECUTABLES
env2                     - An env(1) replacement with more features
sample_interpreter.exe   - A sample interpreter that uses env2 components
