// Includes
#include "config.hh"
#include <unistd.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
//#include <malloc.h>
#include <errno.h>
#include <libgen.h>

#if MAIN_VARIATION == 1 || MAIN_VARIATION == 2
#include "env2lib.hh"
#endif
#include "sample_interpreter.hh"

// #############################################################################

// * load_script *****************************************************
argv_t load_script(char *scriptname) {
  char *lineptr = NULL;
  size_t linesze = 0;
  int read;
  int i=0;
  int max_script_lines = 1024;
  argv_t sc;
  sc.argv = (char **)calloc(max_script_lines, sizeof(char *));

  // open files
  FILE *script = fopen(scriptname, "r");
  if(script == NULL) {
    fprintf(stderr, "%s error: file open failed for '%s'\n", Argv0, scriptname);
    exit(1);
  }

  // read file
  while((read = getline(&lineptr, &linesze, script)) != -1) {
    sc.argv[i++] = strdup(lineptr);
    if(i==max_script_lines-2) {
      fprintf(stderr, "%s error: script exceeded max lines '%d' tuncating\n", Argv0, max_script_lines);
      break;
    }
  }
  sc.argv[i] = NULL;
  sc.argc = i;
  free(lineptr);
  fclose(script);

  return(sc);
}

// * run_bash *****************************************************
void run_bash(argv_t ia, argv_t sa) {
  char *iargvs;
  char *sargvs;
  argv_t sc;
  int i;

  iargvs = join_array(ia.argv, ia.argc);
  sargvs = join_array(sa.argv+1, sa.argc-1);

  sc = load_script(sa.argv[0]);
  // open files
#if 1
  FILE *shell  = popen("/bin/bash --norc --noprofile -s", "w");
#else
  FILE *shell  = popen("/bin/bash --norc --noprofile -i", "w");
#endif
  if(shell == NULL) {
    fprintf(stderr, "%s error: pipe open failed for '%s'\n", Argv0, "bash");
    exit(1);
  }


  // set vars
  fprintf(shell, "typeset -a argv=(%s)\n", iargvs);
  fprintf(shell, "BASH_ARGV0=%s\n", sa.argv[0]);  // bash v5 feature
  fprintf(shell, "set -- %s\n", sargvs);

  // execute script
  for (i=0;i<sc.argc;i++) {
    fprintf(shell, "%s\n", sc.argv[i]);
  }
  pclose(shell);
}

// #############################################################################

#if MAIN_VARIATION == 1

// *************************************************************
// * main1 - Call env2()
// ************************************************************

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

  // set flags (S=split_string E=env2 V=vars2)
  init_flags();
  flags["delim"]  = "~~";  // E search

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

  /// PARSE SCRIPT /////////////////////////////////////////////////////////////
  // fix up iargv and sargv
  argv_t ia;
  ia.argv    =  (char **)calloc(e.argc, sizeof(char *));
  ia.argv[0] = o.argv[0];
  for(i=1;i<scr_loc+1;i++) ia.argv[i] = e.argv[i-1];
  ia.argv[i] = NULL;
  ia.argc    = scr_loc+1;

  argv_t sa;
  sa.argv = e.argv+= scr_loc;
  sa.argc = e.argc-scr_loc;
  // call run_bash
  run_bash(ia, sa);

  return(0);
}

// #############################################################################

#elif MAIN_VARIATION == 2


// *************************************************************
// * main2 - Call split_and_merge()
// ************************************************************


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
  o.argc = argc;
  o.argv = argv;
  int i = 0;

  // set global vars
  Argv0 = o.argv[0];
  Debug = 1;
  setvbuf(stdout, NULL, _IONBF, 0);

  // make sure we have the right number of args
  if(o.argc == 1) {
    usage(1);
  }

  // set flags (S=split_string E=env2 V=vars2)
  init_flags();

  try {
#if KERNEL_SPLIT == 1
  o = read_hashbang(o);    // get hashbang line from script
#endif
#if KERNEL_SPLIT != 2
  e = split_and_merge(o);  // split up argv[1]
#else
  e = o;
#endif
  } catch (StdException &exc) {
    fprintf(stderr, "%s error: %s\n", Argv0, exc.what());
    usage(1);
  } catch (...) {
    fprintf(stderr, "%s error: caught unknown exception\n", Argv0);
    exit(1);
  }

  /// DUMP ARAGS //////////////////////////////////////////////////////////////
  for(i=0; i<e.argc; i++) {
    printf("argv[%i]='%s'\n",i,e.argv[i]);
  }

  /// PARSE SCRIPT //////////////////////////////////////////////////////////////
  //run_bash(ia, sa);

  return(0);
}

// #############################################################################

#elif MAIN_VARIATION == 3

// *************************************************************
// * main3 - Call own parse_flags() modeled on one from env2.cc
// * 
// * NOTES on my_parse_flags():
// *   - This implimentation is a copy of env2's. It sucks.  Should really copy the way Perl does it.
// *   - This is useless for Solaris as the only way to get all inter args is to read #! line 
// *       directly from script the way env2 does it so might as well just use env2.
// ************************************************************

#define STRCMP_TRUE    0
#define COMMENT       '#'
#define ENDOFSTR      '\0'

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

// * parse_flags ***********************************************
// NOTES:
//   - Does not handle flag args with embedded spaces xxx
hash_t my_parse_flags(argv_t a) { 
  hash_t my_flags;                  // Place for my_flags 
  int nstart = 0;                        // nargv start element
  int j = 0;

  my_flags["found"]    = "0";                    // [internal] a found non-flag arg
  my_flags["nstart"]   = "0";                    // [internal] end of env2 args
//      "Debug"                               // turn on debug mode
//      "Help"                                // show usage
//      "Version"                             // show version
  my_flags["aaa"] = "";                          // aaa flag
  my_flags["bbb"] = "";                          // bbb flag
  my_flags["ccc"] = "";                          // ccc flag

  // strip off args meant for me (from #! line) ////////////////////////////////
  
  // loop through argv[]
  for(int i = 1; i< a.argc ;i++) {
    char *flags_str = a.argv[i];
    // loop through char flag clusters (sep by space)
    while(*flags_str != ENDOFSTR) {
      j=1;
      // options
      if        (strcmp(flags_str,"--help")==STRCMP_TRUE) {
        usage(0);
      } else if (strcmp(flags_str,"--version")==STRCMP_TRUE) {
        usage(2);
      } else if (*flags_str == '-') {
        // loop through individual char flags (final flag in cluster can have arg [with no embedded spaces])
        while(
          *(flags_str+j) != ENDOFSTR &&   // not end of string
          *(flags_str+j) != ' '           // not a cluster seperating space
        ) {
          int b=0;
  
          // help
          if     (*(flags_str+j) == 'h') {
            usage(0);
          }
          // aaa
          else if(*(flags_str+j) == 'a') {
            my_flags["aaa"] = "1";
            if(Debug) fprintf(stderr, "Debug: aaa mode activated\n");
          }
          // bbb
          else if(*(flags_str+j) == 'b') {
            my_flags["bbb"] = "1";
            if(Debug) fprintf(stderr, "Debug: bbb mode activated\n");
          }
          // ccc
          else if(*(flags_str+j) == 'c') {
#ifndef F_TAKES_ARG
            if(*(flags_str+j+1) == '=' || *(flags_str+j+1) == ':') {
              char delim[40];
              strcpy(delim, (char *)flags_str+j+2); 
              my_flags["ccc"] = delim;
              b=1;
            } else
#endif
              my_flags["ccc"] = (char *) "~~";
            if(Debug) fprintf(stderr, "Debug: ccc mode activated with '%s'\n", my_flags["ccc"].c_str());
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
        } // inner while
        // inc new start position
        nstart++;
      } // if "-"
      // found a blank
      else if(*(flags_str) == ' ') {
        ; // beginning of new char flag cluster
      }
      // found non-flag argument
      else {
        my_flags["found"] = "1";
        break; // from outter while
      }
      flags_str += j;
    } // outter while
    if(my_flags["found"] == "1") break;
  } // for
  my_flags["nstart"] = to_string(nstart);
  if(Debug) fprintf(stderr, "Debug: found: %s\n", my_flags["found"].c_str());
  if(Debug) fprintf(stderr, "Debug: nstart: %s\n", my_flags["nstart"].c_str());
  return my_flags;
}

// * main3 *****************************************************
int main(int argc, char **argv) {
  hash_t my_flags;                  // Place for my_flags 
  /// PARSE ARAGS //////////////////////////////////////////////////////////////
  argv_t o;
  o.argc = argc;
  o.argv = argv;
  
  // set global vars
  Argv0 = o.argv[0];
  Debug = 1;

  setvbuf(stdout, NULL, _IONBF, 0);

  // make sure we have the right number of args
  if(o.argc == 1) {
    usage(1);
  }

  // Parse out my flags
  my_flags = my_parse_flags(o);
  
  /// DUMP ARAGS //////////////////////////////////////////////////////////////
  printf("argv[0]='%s'\n",o.argv[0]);
  for (auto it = my_flags.begin(); it != my_flags.end(); ++it) {
    if(it->first != "found" && it->first != "nstart")
      printf("flag[%s]='%s'\n",it->first.c_str(), it->second.c_str());
  }
  int scr_loc = 0;
  for(int i=1; i < o.argc; i++) {
    if(o.argv[i][0] == '-') {
      if(scr_loc) printf("argv[%i]='%s'\n",i,o.argv[i]);
    } else {
      printf("argv[%i]='%s'\n",i,o.argv[i]);
      scr_loc = i;
    }
  }

  /// PARSE SCRIPT //////////////////////////////////////////////////////////////
  //run_bash(ia, sa);

  return(0);
}

#else
  
#error "Must define MAIN_VARIATION as 1, 2, or 3"

#endif
