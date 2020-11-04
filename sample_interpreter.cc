// Includes
#include <unistd.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <malloc.h>
#include <errno.h>
#include <libgen.h>

// #############################################################################

#if MAIN_VARIATION == 1

// *************************************************************
// * main1 - Call env2()
// ************************************************************

#include "env2lib.hh"
#include "sample_interpreter.hh"

// Define Globals
char *Argv0;                   // Name of program
int   Debug;                   // Debug flag
hash_t flags;                  // Place for flags (xxx move to private var)

using namespace std;

// * usage *****************************************************
void usage(int ret) {
  printf("Usage\n");
  exit(ret);
}

// * main1 *****************************************************
int main(int argc, char **argv) {
  /// PARSE ARAGS //////////////////////////////////////////////////////////////
  // define local vars
  int i, scr_loc;
  argv_t o, e;
  char *iargvs;
  char *sargvs;
  
  o.argc = argc;
  o.argv = argv;

  // set global vars
  Argv0 = o.argv[0];
  Debug = 1;
  setvbuf(stdout, NULL, _IONBF, 0);

  // make sure we have at least one arg
  if(o.argc < 2) {
    usage(1);
  }

  // Set flags
  flags["found"]  = "-1";  // E inter found
  flags["nstart"] = "0";   // E after env2 flags

  // set flags (S=split_string E=env2 V=vars2)
  flags["cmt"]    = "";    // S comments
  flags["delim"]  = "~~";  // E search
  flags["dump"]   = "";    // E dump
  flags["exp"]    = "";    // S expand
  flags["norc"]   = "";    // V no rc
  flags["pre"]    = "";    // S preserve empty
  flags["sbs"]    = "";    // S strip escapes

  // Call the main env2() function
  try {
    e = env2(o);
  } catch (StdException &exc) {
    fprintf(stderr, "%s error: %s\n", Argv0, exc.what());
    usage(1);
  } catch (...) {
    fprintf(stderr, "%s error: caught unknown exception\n", Argv0);
    exit(1);
  }

  /// DUMP ARAGS //////////////////////////////////////////////////////////////
  printf("argv[0]='%s'\n",o.argv[0]);
  for(i=0; i<e.argc; i++) {
    printf("argv[%i]='%s'\n",i+1,e.argv[i]);
    if((i>0) && (e.argv[i][0] != '-')) scr_loc=i;
  }

  /// PARSE SCRIPT //////////////////////////////////////////////////////////////
#ifndef RUN_BASH
  // open files
  FILE *script = fopen(e.argv[scr_loc], "r");
  FILE *shell  = popen("/bin/bash --norc --noprofile -s", "w");
  char *lineptr = NULL;
  size_t linesze = 0;
  int read;

  // set vars vvvvvvvvvvvv
  iargvs = (char *)"sample_interpreter1 -a -b -c";  // xxx hardcoded!
  sargvs = (char *)"-1 -2 -3";                      // xxx hardcoded! 
  fprintf(shell, "typeset -a argv=(%s)\n", iargvs);
  fprintf(shell, "BASH_ARGV0=%s\n", e.argv[scr_loc]); // bash v5 feature
  fprintf(shell, "set -- %s\n", sargvs);
  // ^^^^^^^^^^^^^^^^^^^^^

  // execute script
  while((read = getline(&lineptr, &linesze, script)) != -1) {
    fprintf(shell, "%s\n", lineptr);
  }
  free(lineptr);
  pclose(shell);
  fclose(script);
#endif

  return(0);
}

// #############################################################################

#elif MAIN_VARIATION == 2


// *************************************************************
// * main2 - Call split_and_merge()
// ************************************************************

#include "env2lib.hh"
#include "sample_interpreter.hh"

// Define Globals
char *Argv0;                   // Name of program
int   Debug;                   // Debug flag
hash_t flags;                  // Place for flags (xxx move to private var)

using namespace std;

// * usage *****************************************************
void usage(int ret) {
  printf("Usage\n");
  exit(ret);
}

// * main2 *****************************************************
int main(int argc, char **argv) {
  /// PARSE ARAGS //////////////////////////////////////////////////////////////
  argv_t o, e;
  int i = 0;

  // set global vars
  Argv0 = argv[0];
  Debug = 0;
  setvbuf(stdout, NULL, _IONBF, 0);

  // make sure we have the right number of args
  if(argc == 1) {
    usage(1);
  }

  // set flags (S=split_string E=env2 V=vars2)
  flags["cmt"]    = "";    // S comments
  flags["exp"]    = "";    // S expand
  flags["pre"]    = "";    // S preserve empty
  flags["sbs"]    = "";    // S strip escapes

  // split_and_merge()
  o.argc = argc;
  o.argv = argv;
  e = split_and_merge(o, NULL, 1);

  /// DUMP ARAGS //////////////////////////////////////////////////////////////
  for(i=0; i<e.argc; i++) {
    printf("argv[%i]='%s'\n",i,e.argv[i]);
  }

  /// PARSE SCRIPT //////////////////////////////////////////////////////////////
  //xxx

  return(0);
}

// #############################################################################

#elif MAIN_VARIATION == 3

// *************************************************************
// * main3 - Call own parse_flags() modeled on one from env2.cc
// * 
// * NOTES on my_parse_flags():
// *   This implimentation is a copy of env2's. It sucks.
// *   Should really copy the way Perl does it.
// ************************************************************

#include "sample_interpreter.hh"

#define STRCMP_TRUE    0
#define COMMENT       '#'
#define ENDOFSTR      '\0'

// Define Globals
char *Argv0;                   // Name of program
int   Debug;                   // Debug flag
hash_t flags;                  // Place for my_flags (xxx move to private var)

using namespace std;

// * usage *****************************************************
void usage(int ret) {
  printf("Usage\n");
  exit(ret);
}

// * parse_flags ***********************************************
hash_t my_parse_flags(char *flags_str) { 
  int nstart = 0;                        // nargv start element
  int j = 0;

  flags["found"]    = "0";                    // [internal] a found non-flag arg
  flags["nstart"]   = "0";                    // [internal] end of env2 args
//      "Debug"                               // turn on debug mode
//      "Help"                                // show usage
//      "Version"                             // show version
  flags["aaa"] = "";                     // aaa flag
  flags["bbb"] = "";                     // bbb flag
  flags["ccc"] = "";                     // ccc flag

  // strip off args meant for me (from #! line) ////////////////////////////////
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
        // aaa
        else if(*(flags_str+j) == 'a') {
          flags["aaa"] = "1";
          if(Debug) fprintf(stderr, "Debug: aaa mode activated\n");
        }
        // bbb
        else if(*(flags_str+j) == 'b') {
          flags["bbb"] = "1";
          if(Debug) fprintf(stderr, "Debug: bbb mode activated\n");
        }
        // ccc
        else if(*(flags_str+j) == 'c') {
#ifdef F_TAKES_ARG
          if(*(flags_str+j+1) == '=' || *(flags_str+j+1) == ':') {
            char delim[40];
            long l = (long) (strchr((char *)flags_str+j+2,' ') - (flags_str+j+2));
            strncpy(delim, (char *)flags_str+j+2, l); // Segfault!
            delim[l] = '\0';
            flags["ccc"] = delim;
            j += l+2;
            b=1;
          } else
#endif
            flags["ccc"] = (char *) "~~";
          if(Debug) fprintf(stderr, "Debug: ccc mode activated with '%s'\n", flags["ccc"].c_str());
          // if delim spec'd, break as this delim string must term with a space
          if (b) {
            b=0;
            break; // from inner while
          }
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
  flags["nstart"] = to_string(nstart);
  if(Debug) fprintf(stderr, "Debug: found: %s\n", flags["found"].c_str());
  if(Debug) fprintf(stderr, "Debug: nstart: %s\n", flags["nstart"].c_str());
  return flags;
}

// * main3 *****************************************************
int main(int argc, char **argv) {
  /// PARSE ARAGS //////////////////////////////////////////////////////////////
  // set global vars
  Argv0 = argv[0];
  Debug = 0;
  setvbuf(stdout, NULL, _IONBF, 0);

  // make sure we have the right number of args
  if(argc == 1) {
    usage(1);
  }

  // Parse out my flags
  flags = my_parse_flags(argv[1]); // xxx what if inter was called from cmd line?

  printf("Debug: nstart='%s'\n",flags["nstart"].c_str());
  
  /// DUMP ARAGS //////////////////////////////////////////////////////////////
  printf("argv[0]='%s'\n",argv[0]);
  for (auto it = flags.begin(); it != flags.end(); ++it) {
    if(it->first != "found" && it->first != "nstart")
      printf("flag[%s]='%s'\n",it->first.c_str(), it->second.c_str());
  }
  int scr_loc = 0;
  for(int i=1; i<argc; i++) {
    if(argv[i][0] == '-') {
      if(scr_loc) printf("argv[%i]='%s'\n",i,argv[i]);
    } else {
      printf("argv[%i]='%s'\n",i,argv[i]);
      scr_loc = i;
    }
  }

  /// PARSE SCRIPT //////////////////////////////////////////////////////////////
  //xxx

  return(0);
}

#else
  
#error "Must define MAIN_VARIATION as 1, 2, or 3"

#endif
