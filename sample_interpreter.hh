#pragma once

// Declare Globals ////////////////

// System vars and functions
extern void perror(const char *s);
extern int errno;

#if MAIN_VARIATION == 3

#include "config.hh"
#include <string>
#include <map>
#include <exception>

#define MAX_STR_CONST 255
#define MAX_LINE_LEN 1024

typedef std::map<std::string, std::string> hash_t;
typedef struct argv {
  int argc;
  char **argv;
} argv_t;

// Global vars
extern char  *Argv0;                           // Name of program
extern int    Debug;                           // Debug flag
extern hash_t flags;                           // Place for flags  xxx

// from merge_arrays.cc
extern char* join_array(char *strings[], int count, char sep=' ');

#endif

// Local functions
extern void usage(int ret);
extern argv_t load_script(char *scriptname);
extern void run_bash(argv_t ia, argv_t sa);
