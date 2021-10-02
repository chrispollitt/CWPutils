#pragma once

// Declare Globals ////////////////

// System vars and functions
extern void perror(const char *s);
extern int errno;

// Local functions
extern void usage(int ret);
extern argv_t load_script(char *scriptname);
extern void run_bash(argv_t ia, argv_t sa);
