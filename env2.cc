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
#include "env2lib.hh"
#include <unistd.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <regex>
//#include <malloc.h>
#include <errno.h>
#include <libgen.h>
#ifdef MAKE_EXE
#include "env2.hh"
#endif

using namespace std;

#ifdef MAKE_EXE
// Define Globals
char *Argv0;                   // Name of program
int   Debug;                   // Debug flag
hash_t flags;                  // Place for flags xxx
#endif

// Constants
#define VERSION   "1.1"
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
 * read_hashbang - read #! line from script file
 **************************************************************/
argv_t read_hashbang(argv_t ia) {
  char *line        = NULL;
  char *linep;
  size_t linesze    = 0;
  int read          = 0;
  char *interpreter = NULL;
  char *script      = NULL;
  FILE *fh          = NULL;
  int i             = 0;
  int j             = 0;
  int scr_loc       = 0;
  argv_t oa;
  int start;
  
#ifdef MAKE_EXE
  start=1;
#if UNAME == SunOS
  if(ia.argv[1][0] == '-') {
    interpreter = (char *)"found";
  }
#endif
#else
  start=0;
#endif
  
  for(i=0; i < ia.argc; i++) {
    if(Debug) printf("Debug: arg%d='%s'\n",i,ia.argv[i]);
    if(
      (strlen(ia.argv[i]))   &&
      (i>=start+1)                  &&
      (interpreter != NULL)  &&
      (script == NULL)       &&
      (ia.argv[i][0] != '-') &&
      (access( ia.argv[i], F_OK ) != -1)
    ) {
      script = ia.argv[i];      // <-- script xxx may not be script
      scr_loc = i;
    }
    else if(
      (strlen(ia.argv[i]))   &&
      (i>=start)                  &&
      (interpreter == NULL)  &&
      (ia.argv[i][0] != '-')
    ) {
      interpreter = ia.argv[i]; // <-- interpreter (may not be set on Solaris!)
    }
    else {
      ; // flag or arg
    }
  }
  if( script != NULL) {
    if((fh = fopen(script,"r")) == NULL) {
      throw StdException("script file not readable: ", script);
      fh = NULL;
    }
  }
  else {
    throw StdException("unable to determine script filename");
    fh = NULL;
  }
  if(fh != NULL) {
    read = getline(&line, &linesze, fh);
    if(
      (read < 5)                      ||
      ( strncmp(line, "#!/", 3) != 0 )
    ) {
      throw StdException("script file #! line not correct: ", script);
    }
    fclose(fh);
  }
  
  line = strchr(line, ' ')+1; // skip over interpreter
  linep = line+strlen(line)-1;
  *linep = '\0';
  if(Debug) printf("Debug: hashbang='%s'\n", line);
  oa.argc = 0;
  oa.argv = (char **)calloc(MAX_STR_CONST, sizeof(char *));
  oa.argv[0] = ia.argv[0];
  oa.argv[1] = strdup(line);
  j=2;
  for(i=scr_loc;i < ia.argc; i++) {
    oa.argv[j++] = ia.argv[i];
  }
  oa.argv[j] = NULL;
  oa.argc = j;
  
  return(oa);
}

/****************************************************************
 * env2 - construct the correct argv[] array
 **************************************************************/
argv_t env2(argv_t o) {
  argv_t n = {0, (char **)NULL};
  argv_t c = {0, (char **)NULL};
  argv_t e = {0, (char **)NULL};
  int i, j, k;               // Loop counters
  int set;                   // cnf args set or add
  int int_loc = 0;           // interpreter nargv location
  int scr_loc = 0;           // script      nargv location
  int oscr_loc = 0;
  string interpreter_base;   // basename of interpreter
  int nstart;
  hash_t add_args;

  // main() should check for this - make sure we have the right number of args
  if(o.argc == 1) {
    throw StdException("No args found");
  }
  
#if   KERNEL_SPLIT == 0
  ;  // nothing extra to do
#elif KERNEL_SPLIT == 1
  o = read_hashbang(o);  // get hashbang line from script
#elif KERNEL_SPLIT == 2
#error "KERNEL_SPLIT == 2 support not yet written"
#else
#error "Must define KERNEL_SPLIT as 0, 1, or 2"
#endif
  
  // split up argv[1] (from #! line) ///////////////////////////////////////////
  n = split_string(o.argv[1]);

  // check that we have an interpreter from #! /////////////////////////////////
#ifdef MAKE_EXE
  ;
#else
  // Set flags for lib call
  flags["found"]  = "-1";  // E inter found (-1 means inter==o.argv[0])
  flags["nstart"] = "0";   // E after env2 flags
#endif
  nstart = stoi(flags["nstart"]);
  if(stoi(flags["found"]) == 1) {
    int_loc = nstart;
    oscr_loc = 2;
    interpreter_base = basename(n.argv[int_loc]);
  } else if(stoi(flags["found"]) == -1) {
    int_loc = 0;
    oscr_loc = 1;
    interpreter_base = basename(o.argv[int_loc]);
  } else {
    // find int location in o.argv
    int_loc = 1;
    while(int_loc<o.argc && o.argv[int_loc][0] == '-') {
      int_loc++;
    }
    if(int_loc == o.argc || o.argv[int_loc][0] == '-') {
      throw StdException("No interpreter found");
    } else {
      interpreter_base = basename(o.argv[int_loc]);
    }
  }

  // look for args meant for script, not interpreter ///////////////////////////
  flags["found"] = "0";
  if(flags["delim"].length()) {
    for(i=nstart; i < n.argc; i++) {
      // options
      if(strncmp(n.argv[i], flags["delim"].c_str(), MAX_STR_CONST-1 )==STRCMP_TRUE) {
        flags["found"] = to_string(i+1);
        break;
      }
    }
  }

  // check that we have a script next //////////////////////////////////////////
  // find script location
  while(oscr_loc<o.argc && o.argv[oscr_loc][0] == '-') {
    oscr_loc++;
  }
  if((oscr_loc == o.argc) || (o.argv[oscr_loc][0] == '-')) {
    throw StdException("No script found");
  }
  if(Debug) fprintf(stderr, "Debug: oscr_loc: %d\n", oscr_loc);

  // add script  ///////////////////////////////////////////////////////////////
  if(stoi(flags["found"])) {
    scr_loc = stoi(flags["found"])-1;
    n.argv[scr_loc] = strndup( o.argv[oscr_loc], MAX_STR_CONST-1);
  } else {
    if(oscr_loc == 2) {
      scr_loc = n.argc;
      n.argv[scr_loc] = strndup( o.argv[oscr_loc], MAX_STR_CONST-1);
      n.argc++;
    } else {
      scr_loc = n.argc + (oscr_loc-2);
      // o.argv[oscr_loc] will be added below
    }
  }

  // add remaining args for script (from user) /////////////////////////////////
  for(j = (oscr_loc == 2) ? 3 : 2; j<o.argc; j++) {
    n.argv[n.argc] = strndup( o.argv[j], MAX_STR_CONST-1);
    n.argc++;
  }

  // prep conf args ////////////////////////////////////////////////////////////
  e.argc = n.argc-nstart;
  if(!flags["norc"].length()) {
    add_args = vars2();
    if(Debug) fprintf(stderr, "Debug: interpreter_base: %s\n", interpreter_base.c_str());
    if(add_args.find(interpreter_base) != add_args.end()) {
      char *add_args_s = (char *)add_args[interpreter_base].c_str();

      c = split_string(add_args_s);
      e.argc += c.argc;
    }
  }

  // copy from cargv & nargv to eargv //////////////////////////////////////////
  i=nstart; // nargv (nstart is first non-env2 flag arg)
  j=0;      // eargv
  k=0;      // cargv
  e.argv = (char **)calloc(MAX_STR_CONST, sizeof(char *));

  // add interpreter
  e.argv[j++] = n.argv[i++];
  // add remaining args
  set = 0;
  while(j < e.argc) {
    // add config args ////////////////////////////////////
    if(c.argc && k<c.argc) {
      // if set_arg
      if(strncmp(c.argv[k],"~~",2)==STRCMP_TRUE) {
        set = 1;
        // if empty string
        if (!strlen(c.argv[k]+2) && !flags["pre"].length()) {
          if(Debug) fprintf(stderr, "Debug: skipping empty cfg interprter arg at %d\n", k);
          k++;
          // set it
        } else {
          if(Debug) fprintf(stderr, "Debug: setting cfg interprter arg: %s\n", c.argv[k]+2);
          e.argv[j++] = c.argv[k++]+2;
        }
        // else add_arg
      } else {
        // if empty string
        if (!strlen(c.argv[k]) && !flags["pre"].length()) {
          if(Debug) fprintf(stderr, "Debug: skipping empty cfg interprter arg at %d\n", k);
          k++;
          // add it
        } else {
          if(Debug) fprintf(stderr, "Debug: adding cfg interprter arg: %s\n", c.argv[k]);
          e.argv[j++] = c.argv[k++];
        }
      }
      // add nargv args //////////////////////////////////////
    } else {
      if(set && i < scr_loc ) {
        if(Debug) fprintf(stderr, "Debug: skipping nargv interprter arg: %s\n", n.argv[i]);
        i++;
      } else {
        e.argv[j++] = n.argv[i++];
      }
    }
  }
  e.argv[j] = NULL;

  // dump args /////////////////////////////////////////////////////////////////
  if(Debug) fprintf(stderr, "Debug: hashbang=%s\n", o.argv[1]);
  if(Debug && !flags["dump"].length()) {
    for(i=0; i<j; i++) fprintf(stderr, "Debug: argv[%d]='%s'\n", i, e.argv[i]);
  }
  if(flags["dump"].length()) {
    printf("------env-----\n");
    printf("arg%d='%s'\n",0,o.argv[0]);
    for(i=0; i<nstart; i++) {
      printf("arg%d='%s'\n",i+1,n.argv[i]);
    }
    dumpargs(j, e.argv);
  }

  /// return new vars ////////////////////////////////////////////////
  return(e);
}

// #############################################################################

#ifdef MAKE_EXE

/**************************************************************
 * parse_flags - parse my flags
 **************************************************************/
hash_t parse_flags(char *flags_str) { 
  int nstart = 0;                            // nargv start element
  int j = 0;

  flags["found"]    = "0";                    // [internal] a found non-flag arg
  flags["nstart"]   = "0";                    // [internal] end of env2 args
//      "Debug"                               // turn on debug mode
//      "Help"                                // show usage
//      "Version"                             // show version
  flags["cmt"]      = "";                     // allow comments
  flags["delim"]    = "";                     // Delimiter to sep interpreter args from script args
  flags["dump"]     = "";                     // Dump args flag
  flags["exp"]      = "";                     // Expand standard backslash-escaped characters
  flags["norc"]     = "";                     // Do not read rc file
  flags["pre"]      = "";                     // preserve empty args
  flags["sbs"]      = "";                     // Strip backslashes

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
  flags["nstart"] = to_string(nstart);
  if(Debug) fprintf(stderr, "Debug: found: %s\n", flags["found"].c_str());
  if(Debug) fprintf(stderr, "Debug: nstart: %s\n", flags["nstart"].c_str());
  return flags;
}

/****************************************************************
 * usage - print my usage
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
 * main - main function
 **************************************************************/
int main(int argc, char **argv) {
  // define local vars
  int code;
  argv_t o, e;
  o.argc = argc;
  o.argv = argv;

  // define global vars
  Argv0 = o.argv[0];
  Debug = 0;
  setvbuf(stdout, NULL, _IONBF, 0);

  // make sure we have at least one arg
  if(o.argc < 2) {
    usage(1);
  }

  // Parse out my flags
  flags   = parse_flags(o.argv[1]);

  // Call the main env2() function
  try {
    e = env2(o);
  } catch (StdException &exc) {
    fprintf(stderr, "%s error: %s\n", Argv0, exc.what());
    usage(1);
  }

  // Exec the interpreter
  code = execvp(e.argv[0], e.argv);

  // Oh dear, there was an error
  fprintf(stderr, "%s error: exec() failed: ", Argv0);
  perror(e.argv[0]);
  return(code);
}

#endif
