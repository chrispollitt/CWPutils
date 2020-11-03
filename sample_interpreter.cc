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
hash_t flags;                  // Place for flags

using namespace std;

// * usage *****************************************************
void usage(int ret) {
  printf("Usage\n");
  exit(ret);
}

int main(int argc, char **argv) {
  int nstart;
  int argc2 = 3;
  char **argv2 = (char **)calloc(4, sizeof(char *));
  char *argv1  = (char *)malloc(MAX_LINE_LEN);
  int i = 0;
  int j = 0;

  // set global vars
  Argv0 = argv[0];
  Debug = 0;
  setvbuf(stdout, NULL, _IONBF, 0);

  snprintf(argv1, MAX_LINE_LEN-1, "%s %s %s",
           "-d",                      // flags to env2
           argv[0],                   // this prog name
           argv[1]                    // combined are for this program
          );

  argv2[0] = (char *)argv[0];  // this prog name
  argv2[1] = (char *)argv1;    // combined ars for this program
  argv2[2] = (char *)argv[2];  // the script name
  argv2[3] = (char *)NULL;     // end of argv

  /////////////////////////////////////

  // Split argv[1] and merge back into argv
  //split_and_merge();

  // Call the main env2() function
  try {
    env2(&argc, &argv, 1); // xxx
  } catch (StdException &e) {
    fprintf(stderr, "%s error: %s\n", Argv0, e.what());
    usage(1);
  }

  //////////////////////////////////

  for(i=0; i<argc2; i++) {
    printf("argv[%i]='%s'\n",j++,argv2[i]);
  }
  for(i=3; i<argc; i++) {
    printf("argv[%i]='%s'\n",j++,argv[i]);
  }
  return(0);
}

#endif

// #############################################################################

#if MAIN_VARIATION == 2


// *************************************************************
// * main2 - Call split_string()
// ************************************************************

#include "env2lib.hh"
#include "sample_interpreter.hh"

// Define Globals
char *Argv0;                   // Name of program
int   Debug;                   // Debug flag
hash_t flags;                  // Place for flags

using namespace std;

// * usage *****************************************************
void usage(int ret) {
  printf("Usage\n");
  exit(ret);
}

int main(int argc, char **argv) {
  argv_t n, e;
  int i = 0;

  // set global vars
  Argv0 = argv[0];
  Debug = 0;
  setvbuf(stdout, NULL, _IONBF, 0);

  // split_and_merge()
  n.argc = argc;
  n.argv = argv;
  e = split_and_merge(n, NULL, 1);

  //////////////////////////////////////////////////////////////////////////////
  for(i=0; i<e.argc; i++) {
    printf("argv[%i]='%s'\n",i,e.argv[i]);
  }

  return(0);
}

#endif

// #############################################################################

#if MAIN_VARIATION == 3

// *************************************************************
// * main3 - Call own parse_flags() modeled on one from env2.cc
// ************************************************************

#include "sample_interpreter.hh"

#define STRCMP_TRUE    0
#define COMMENT       '#'
#define ENDOFSTR      '\0'

// Define Globals
char *Argv0;                   // Name of program
int   Debug;                   // Debug flag
hash_t flags;                  // Place for flags

using namespace std;

// * usage *****************************************************
void usage(int ret) {
  printf("Usage\n");
  exit(ret);
}

// * parse_flags ***********************************************
int my_parse_flags(char *flags_str) {
  int nstart = 0;                        // nargv start element
  int j = 0;

  flags["found"] = "";                   // found non flag arg
  flags["aaa"] = "";                     // aaa flag
  flags["bbb"] = "";                     // bbb flag
  flags["ccc"] = "";                     // ccc flag

  // strip off args meant for me (from #! line) ////////////////////////////////
  while(*flags_str != ENDOFSTR) {
    j=0;
    // options
    if        (strcmp(flags_str,"--help")==STRCMP_TRUE) {
      usage(0);
    } else if (strcmp(flags_str,"--version")==STRCMP_TRUE) {
      usage(2);
    } else if (*flags_str == '-') {
      j=1;
      while(*(flags_str+j) != ENDOFSTR && *(flags_str+j) != ' ') {

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
          flags["aaa"] = "1";
          if(Debug) fprintf(stderr, "Debug: bbb mode activated\n");
        }
        // ccc
        else if(*(flags_str+j) == 'c') {
          flags["ccc"] = "1";
          if(Debug) fprintf(stderr, "Debug: aaa mode activated\n");
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
    flags_str += j+1;
  } // while
  return nstart;
}

// * main 3 ******************************************************
int main(int argc, char **argv) {
  // define local vars
  int code, nstart;

  // set global vars
  Argv0 = argv[0];
  Debug = 0;
  setvbuf(stdout, NULL, _IONBF, 0);

  // make sure we have the right number of args
  if(argc == 1) {
    fprintf(stderr, "%s error: No interpreter found\n", Argv0);
    usage(1);
  }

  // Parse out my flags
  nstart = my_parse_flags(argv[1]);

  // test parsing
  printf("flag groupings=%d\n", nstart);
  printf("Argv0=%s\n", Argv0);

  return(0);
}

#endif
