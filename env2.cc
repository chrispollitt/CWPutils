/*****************************************************************
 * env replacement
 *
 * Has these features over and above the classic env(1):
 * - splits out interpreter arg string into seperate args
 * - has a config file that allows for
 *   ~ environment variables to be set
 *   ~ interpreter args to be added in per interpreter
 * - can call dumpargs(1) if desired
 * - has an optional section for hardcoded script args
 * - can ignore comments on #! line
 ****************************************************************/

// Includes
#include <unistd.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <libgen.h>
#include "env2lib.hh"
#include "env2.hh"

using namespace std; 

// Define Globals
char *Argv0;                   // Name of program
int   Debug;                   // Debug flag
hash_t add_args;               // Set in vars5()
hash_t flags;                  // Place for flags

// Constants
#define VERSION   "1.0"
#define YEAR      "2020"

/****************************************************************
 * print usage
 **************************************************************/
void usage(int ret) {
  if(ret==2) {
    printf(
"env2 (CWP utils) version %s                                             \n"
"Copyright (C) %s Universal Laughter                                     \n"
"License GPLv3+: GNU GPL version 3 or later.                             \n"
"This is free software: you are free to change and redistribute it.      \n"
"There is NO WARRANTY, to the extent permitted by law.                   \n"
"                                                                        \n"
"Written by Chris Pollitt                                                \n",
      VERSION,
      YEAR
    );
    exit(0);
  } else {
    FILE *out;
    out = ret==0 ? stdout : stderr;
    fprintf(out,
"Usage:                                                                  \n"
"  #!%1$s [flags] <interpreter> [<interpreter_args>]                     \n"
"  #!%1$s [flags] -f <interpreter> [<interpreter_args>] ~~ <script_args> \n"
"Where [flags] are one or more of:                                       \n"
"  -c     : comments mode                                                \n"
"  -d     : debug mode                                                   \n"
"  -e     : emit (dump) mode                                             \n"
"  -f[=S] : find (delim) mode using opt string S (S=~~ if not specified) \n"
"  -n     : no rc file                                                   \n"
"  -p     : preserve empty args                                          \n"
"  -s     : strip backslashes                                            \n"
"  -x     : expand standard backslash-escaped characters                 \n"
"  -h     : this help                                                    \n"
"Notes:                                                                  \n"
"  * flags can be combined in one string                                 \n"
"  * all flags are off by default                                        \n"
"  * if using debug flag, best to put it first                           \n"
"  * if using find flag, best to put it last                             \n"
"Examples:                                                               \n"
"  #!%1$s -s -n perl -w                                                  \n"
"  #!%1$s bash -x -v                                                     \n"
"  #!%1$s -def=@@ python @@ -sf                                          \n",
      Argv0
    );
    exit(ret);
  }
}

/**************************************************************
 * main
 **************************************************************/
int main(int argc, char **argv) {
  int code;

  Argv0 = argv[0];
  Debug = 0;
  setvbuf(stdout, NULL, _IONBF, 0);

  env2(&argc, &argv);
  code = execvp(argv[0], argv);
  fprintf(stderr, "%s error: ", argv[0]);
  perror(argv[0]);
  return(code);
}
