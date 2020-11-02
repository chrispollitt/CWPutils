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
#include <malloc.h>
#include <errno.h>
#include <libgen.h>
#include "env2lib.hh"
#ifdef MAKE_EXE
#include "env2.hh"
#endif

using namespace std;

#ifdef MAKE_EXE
// Define Globals
char *Argv0;                   // Name of program
int   Debug;                   // Debug flag
hash_t add_args;               // Set in vars2()
hash_t flags;                  // Place for flags
#endif

// Constants
#define VERSION   "1.0"
#define YEAR      "2020"

#define STRCMP_TRUE    0
#define COMMENT       '#'
#define ENDOFSTR      '\0'
#define SPACE         ' '
#define TAB           '\t'
#define NEWLINE       '\n'
#define RETURN        '\r'
#define SINGLEQUOTE   '\''
#define DOUBLEQUOTE   '\"'
#define BACKSLASH     '\\'


/****************************************************************
 * env2
 **************************************************************/
void env2 (int *argcp, char ***argvp, int nstart) {
//  argv_t o;
  char **argv;                               // Orig argv
  int    argc;                               // size of argv
  argv_t n;
  char  **nargv; // New  argv (as array of arrays)
  int   nargc = 0;                           // size of nargv
  argv_t c;
  char  **cargv; // config  argv (as array of arrays)
  int   cargc = 0;                           // size of cargv
//  argv_t e;
  char **eargv;                // New  argv (as array of pointers)
  int   eargc = 0;                           // size of eargv
  int i, j, k;                               // Loop counters
  int set;                                   // cnf args set or add
  int int_loc = 0;                           // interpreter nargv location
  int scr_loc = 0;                           // script      nargv location
  string interpreter_base;                   // basename of interpreter

  argv = *argvp;                       // Orig argv
  argc = *argcp;                       // size of argv

  // main() should check for this - make sure we have the right number of args
  if(argc == 1) {
    throw StdException("No args found");
  }

  // split up argv[1] (from #! line) ///////////////////////////////////////////
  n = split_string(argv[1]);
  nargv = n.argv;
  nargc = n.argc;

  // if sbs mode, strip off excess backslashes from nargs  /////////////////////
  if(flags["sbs"].length()) {
    for(i=0; i< nargc; i++) {
      char *nargvx = (char *)malloc(MAX_STR_CONST);
      k=0;
      j=0;

      while(nargv[i][j] != ENDOFSTR) {
        if(nargv[i][j] == BACKSLASH) {
          if(nargv[i][j+1] == BACKSLASH) {
            nargvx[k++] = nargv[i][j];
            j++;
          }
        } else {
          nargvx[k++] = nargv[i][j];
        }
        j++;
      }
      nargvx[k++] = ENDOFSTR;
      nargv[i] = strndup( nargvx, MAX_STR_CONST-1);
    }
  }

  // check that we have an interpreter from #! /////////////////////////////////
  if(!flags["found"].length()) {
    throw StdException("No interpreter found");
  }
  int_loc = nstart;

  // look for args meant for script, not interpreter ///////////////////////////
  flags["found"] = "";
  if(flags["delim"].length()) {
    for(i=nstart; i < nargc; i++) {
      // options
      if(strncmp(nargv[i], flags["delim"].c_str(), MAX_STR_CONST-1 )==STRCMP_TRUE) {
        flags["found"] = to_string(i+1);
        break;
      }
    }
  }

  // check that we have a script next //////////////////////////////////////////
  if(argc<3 || argv[2][0] == '-') {
    throw StdException("No script found");
  }

  // add script  ///////////////////////////////////////////////////////////////
  if(flags["found"].length()) {
    scr_loc = stoi(flags["found"])-1;
    nargv[scr_loc] = strndup( argv[2], MAX_STR_CONST-1);
  } else {
    scr_loc = nargc;
    nargv[nargc++] = strndup( argv[2], MAX_STR_CONST-1);
  }

  // add remaining args for script (from user) /////////////////////////////////
  for(j=3; j<argc; j++) {
    nargv[nargc++] = strndup( argv[j], MAX_STR_CONST-1);
  }

  // prep conf args ////////////////////////////////////////////////////////////
  eargc = nargc-nstart;
  if(!flags["norc"].length()) {
    vars2();
    interpreter_base = basename(nargv[int_loc]);
    if(Debug) fprintf(stderr, "Debug: interpreter_base: %s\n", interpreter_base.c_str());
    if(add_args.find(interpreter_base) != add_args.end()) {
      char *add_args_s = (char *)add_args[interpreter_base].c_str();

      c = split_string(add_args_s);
      cargc = c.argc;
      cargv = c.argv;
      eargc += cargc;
    }
  }

  // copy from cargv & nargv to eargv //////////////////////////////////////////
  i=nstart; // nargv (nstart is first non-env2 flag arg)
  j=0;      // eargv
  k=0;      // cargv
  eargv = (char **)calloc(MAX_STR_CONST, sizeof(char *));

  // add interpreter
  eargv[j++] = nargv[i++];
  // add remaining args
  set = 0;
  while(j < eargc) {
    // add config args ////////////////////////////////////
    if(cargc && k<cargc) {
      // if set_arg
      if(strncmp(cargv[k],"~~",2)==STRCMP_TRUE) {
        set = 1;
        // if empty string
        if (!strlen(cargv[k]+2) && !flags["pre"].length()) {
          if(Debug) fprintf(stderr, "Debug: skipping empty cfg interprter arg at %d\n", k);
          k++;
          // set it
        } else {
          if(Debug) fprintf(stderr, "Debug: setting cfg interprter arg: %s\n", cargv[k]+2);
          eargv[j++] = cargv[k++]+2;
        }
        // else add_arg
      } else {
        // if empty string
        if (!strlen(cargv[k]) && !flags["pre"].length()) {
          if(Debug) fprintf(stderr, "Debug: skipping empty cfg interprter arg at %d\n", k);
          k++;
          // add it
        } else {
          if(Debug) fprintf(stderr, "Debug: adding cfg interprter arg: %s\n", cargv[k]);
          eargv[j++] = cargv[k++];
        }
      }
      // add nargv args //////////////////////////////////////
    } else {
      if(set && i < scr_loc ) {
        if(Debug) fprintf(stderr, "Debug: skipping nargv interprter arg: %s\n", nargv[i]);
        i++;
      } else {
        eargv[j++] = nargv[i++];
      }
    }
  }
  eargv[j] = NULL;

  // dump args /////////////////////////////////////////////////////////////////
  if(Debug) fprintf(stderr, "Debug: hashbang=%s\n", argv[1]);
  if(Debug && !flags["dump"].length()) {
    for(i=0; i<j; i++) fprintf(stderr, "Debug: argv[%d]='%s'\n", i, eargv[i]);
  }
  if(flags["dump"].length()) {
    printf("------env-----\n");
    printf("arg%d='%s'\n",0,argv[0]);
    for(i=0; i<nstart; i++) {
      printf("arg%d='%s'\n",i+1,nargv[i]);
    }
    dumpargs(j, eargv);
  }

  /// move pointers to new vars ////////////////////////////////////////////////
  *argvp = eargv;
  *argcp = eargc;
}

// #############################################################################

#ifdef MAKE_EXE

/**************************************************************
 * parse_flags
 **************************************************************/
int parse_flags(argv_t e) { // xxx change to all of argv after split_and_merge()
  int nstart = 0;                            // nargv start element
  int j = 0;

  flags["cmt"]      = "";                     // allow comments
  flags["pre"]      = "";                     // preserve empty args
  flags["dump"]     = "";                     // Dump args flag
  flags["sbs"]      = "";                     // Strip backslashes
  flags["norc"]     = "";                     // Do not read rc file
  flags["delim"]    = "";                     // Delimiter to sep interpreter args from script args
  flags["exp"]      = "";                     // Expand standard backslash-escaped characters
  flags["found"]    = "";                     // [internal] found non flag

  // strip off args meant for me (from #! line) ////////////////////////////////
  for(int i=1; i<e.argc; i++) {
    char *flags_str = e.argv[i];
    if(*flags_str != '-') {
      flags["found"] = "1";
      break;
    }
    while(*flags_str != ENDOFSTR) {
      j=1;
      // options
      if        (strcmp(flags_str,"--help")==STRCMP_TRUE) {
        usage(0);
      } else if (strcmp(flags_str,"--version")==STRCMP_TRUE) {
        usage(2);
      } else if (*flags_str == '-') {
        while(*(flags_str+j) != ENDOFSTR && *(flags_str+j) != ' ') {
          int b=0;

          // help
          if     (*(flags_str+j) == 'h') {
            usage(0);
          }
          // comment
          else if(*(flags_str+j) == 'c') {
            flags["cmt"] = "1";
            if(Debug) fprintf(stderr, "Debug: Comment mode activated\n");
          }
          // debug
          else if(*(flags_str+j) == 'd') {
            Debug = 1;
            if(Debug) fprintf(stderr, "Debug: Debug mode activated\n");
          }
          // emit (dump)
          else if(*(flags_str+j) == 'e' || *(flags_str+j) == 'D' ) {
            flags["dump"] = "1";
            if(Debug) fprintf(stderr, "Debug: Dump mode activated\n");
          }
          // find (delim)
          else if(*(flags_str+j) == 'f') {
#ifdef F_TAKES_ARG
            if(*(flags_str+j+1) == '=' || *(flags_str+j+1) == ':') {
              char delim[40];
              long l = (long) (strchr((char *)flags_str+j+2,' ') - (flags_str+j+2));
              strncpy(delim, (char *)flags_str+j+2, l); // Segfault!
              delim[l] = '\0';
              flags["delim"] = delim;
              j += l+2;
              b=1;
            } else
#endif
              flags["delim"] = (char *) "~~";
            if(Debug) fprintf(stderr, "Debug: Delim mode activated with '%s'\n", flags["delim"].c_str());
            // if delim spec'd, break as this delim string must term with a space
            if (b) {
              b=0;
              break; // from inner while
            }
          }
          // no rc file
          else if(*(flags_str+j) == 'n' ) {
            flags["norc"] = "1";
            if(Debug) fprintf(stderr, "Debug: No rc file mode activated\n");
          }
          // preserve empty args
          else if(*(flags_str+j) == 'p') {
            flags["pre"] = "1";
            if(Debug) fprintf(stderr, "Debug: Perserve empty args mode activated\n");
          }
          // strip backslashes
          else if(*(flags_str+j) == 's' ) {
            flags["sbs"] = "1";
            if(Debug) fprintf(stderr, "Debug: Strip mode activated\n");
          }
          // expand backslash-escaped chars
          else if(*(flags_str+j) == 'x' ) {
            flags["exp"] = "1";
            if(Debug) fprintf(stderr, "Debug: Expand mode activated\n");
          }
          // illegal
          else {
            fprintf(stderr, "%s error: unrecognized flag %c\n", Argv0, *(flags_str+j));
            usage(1);
          }
          j++;
        } // while
        // inc new start position
        nstart++;
      } // if -
      // found a blank
      else if(*(flags_str) == ' ') {
        ; // do nothing
      }
      // found non-flag argument
      else {
        flags["found"] = "1";
        break; // from outter while
      }
      flags_str += j;
    } // while
  }
  return nstart;
}

/****************************************************************
 * print usage
 **************************************************************/
void usage(int ret) {
  if(ret==2) {
    printf(
      "env2 (CWPutils) version %s                                              \n"
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
#ifdef F_TAKES_ARG
            "  -f[=S] : find (delim) mode using opt string S (S=~~ if not specified) \n"
#else
            "  -f     : find script opts separated by delimiter ~~                   \n"
#endif
            "  -n     : no rc file                                                   \n"
            "  -p     : preserve empty args                                          \n"
            "  -s     : strip backslashes                                            \n"
            "  -x     : expand standard backslash-escaped characters                 \n"
            "  -h     : this help                                                    \n"
            "Notes:                                                                  \n"
            "  * flags can be combined in one string                                 \n"
            "  * all flags are off by default                                        \n"
            "Examples:                                                               \n"
            "  #!%1$s -s -n perl -w                                                  \n"
            "  #!%1$s bash -x -v                                                     \n"
#ifdef F_TAKES_ARG
            "  #!%1$s -def=@@ python @@ -sf                                          \n"
#endif
            "  #!%1$s -c python # -*-Python-*-                                       \n",
            Argv0
           );
    exit(ret);
  }
}

/**************************************************************
 * main
 **************************************************************/
int main(int argc, char **argv) {
  // define local vars
  int code, nstart;
  argv_t n, e;

  // define global vars
  Argv0 = argv[0];
  Debug = 0;
  setvbuf(stdout, NULL, _IONBF, 0);

  // make sure we have the right number of args
  if(argc == 1) {
    usage(1);
  }

  // Split argv[1] and merge back into argv
  n.argc = argc;
  n.argv = argv;
  e = split_and_merge(n, NULL, 1);

  // Parse out my flags
  nstart = parse_flags(e);

  // Call the main env2() function
  try {
    env2(&argc, &argv, nstart);
  } catch (StdException &e) {
    fprintf(stderr, "%s error: %s\n", Argv0, e.what());
    usage(1);
  }

  // Exec the interpreter
  code = execvp(argv[0], argv);

  // Oh dear, there was an error
  fprintf(stderr, "%s error: ", argv[0]);
  perror(argv[0]);
  return(code);
}

#endif
