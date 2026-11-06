// Includes
#include "config.hh"
#include <unistd.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
//#include <malloc.h>
#include <errno.h>
#include <libgen.h>

#if MAIN_VARIATION == 1 || MAIN_VARIATION == 2 || MAIN_VARIATION == 3
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
  int i, scr_loc = 0;
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
  Flags flags;
  flags.delim = "~~";  // E search

  // Call the main env2() function
  try {
    e = env2(flags, o);
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
  Flags flags;

  try {
#if KERNEL_SPLIT == 1
  o = read_hashbang(flags, o);    // get hashbang line from script
#endif
  e = split_and_merge(flags, o);  // split up argv[1]
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
// * main3 - Parse my own #! switches with parse_switches()
// *
// * This is how a custom interpreter can use the env2 library to handle
// * its switches the way Perl does: a table of switches, clustered letters
// * (-ab), several clusters in one string ("-ab -c=x"), and parsing that
// * stops at the first non-switch word.  parse_switches() has no globals
// * and never exits; it throws StdException on a bad switch.
// *
// * Try:  ./sample_interpreter3 "-ab -c=x perl -w" script
// ************************************************************

// Define Globals
char *Argv0;                   // Name of program
int   Debug;                   // Debug flag

using namespace std;

// * usage *****************************************************
void usage(int ret) {
  printf("Usage\n");
  exit(ret);
}

// * main3 *****************************************************
int main(int argc, char **argv) {
  argv_t o;
  o.argc = argc;
  o.argv = argv;

  // set global vars
  Argv0 = o.argv[0];
  Debug = 0;
  setvbuf(stdout, NULL, _IONBF, 0);

  // make sure we have the right number of args
  if(o.argc < 2) {
    usage(1);
  }

  // my switches: -a, -b (plain) and -c (may take an attached arg: -c=x)
  const vector<SwitchSpec> spec = {
    {'a', "aaa", false},
    {'b', "bbb", false},
    {'c', "ccc", true },
  };

  Flags flags;                     // only needed by read_hashbang()
  try {
#if KERNEL_SPLIT == 1
    o = read_hashbang(flags, o);   // get the #! line from the script itself
#endif
    SwitchResult r = parse_switches(o.argv[1], spec);

    /// DUMP ////////////////////////////////////////////////////////////////
    for(size_t i=0; i < r.given.size(); i++) {
      printf("switch -%c", r.given[i].letter);
      if(r.given[i].hasarg) printf(" arg='%s'", r.given[i].arg.c_str());
      printf("\n");
    }
    printf("clusters=%d\n", r.clusters);
    printf("rest='%s'\n", r.rest.c_str());
  } catch (StdException &exc) {
    fprintf(stderr, "%s error: %s\n", Argv0, exc.what());
    usage(1);
  }

  return(0);
}

// #############################################################################

#else
  
#error "Must define MAIN_VARIATION as 1, 2 or 3"

#endif
