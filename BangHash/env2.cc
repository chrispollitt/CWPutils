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
#include <errno.h>
#include <libgen.h>
#include <iterator>
#include <regex>
#ifdef MAKE_EXE
#include "env2.hh"
#endif

using namespace std;

#ifdef MAKE_EXE
// Define Globals
char *Argv0;                   // Name of program
int   Debug;                   // Debug flag
hash_t flags;                  // Place for flags 
#endif

#define DEF_TO_STR2(s) #s
#define DEF_TO_STR(s) DEF_TO_STR2(s)

// Constants
#define VERSION   "1.3"
#define YEAR      "2020"

#ifndef PREFIX
#define PREFIX /usr/local
#endif
#define PREFIX_S DEF_TO_STR(PREFIX)

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
 * set_dash - set the dash regular expression depending on flags["allow"] - PRIVATE
 **************************************************************/
regex set_dash() {
  regex dash;
  string re1 = string(R"(^['"]?[-)");
  string re2 = string(R"(])");    
  
  if( flags["allow"].l() ) {
     string re = re1 + flags["allow"].s().front() + re2;
     dash= regex( re );
  } else {
     string re = re1 + re2;
     dash= regex( re );
  }
  
  return(dash);
}

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
  regex dash        = set_dash();
  
  if(Debug>=2) printf("Debug: Func=read_hashbang\n");
  
#ifdef MAKE_EXE
  start=1;
#if UNAME == UNAME_SOLARIS
  // Solaris strips off interpreter args past the first one
  if(regex_search(ia.argv[1], dash)) {
    interpreter = (char *)"found";
    if(Debug>=2) printf("Debug: Solaris stripped interpreter\n");
  }
#endif
#else
  start=0;
#endif
  
  for(i=0; i < ia.argc; i++) {
    if(Debug>=2) printf("Debug: arg%d='%s'\n",i,ia.argv[i]);
    if(
      (strlen(ia.argv[i]))              &&
      (i>=start+1)                      &&
      (interpreter != NULL)             &&
      (script == NULL)                  &&
      (!regex_search(ia.argv[i], dash)) &&
      (access( ia.argv[i], F_OK ) != -1)
    ) {
      script = ia.argv[i];      // <-- script may not be script
      scr_loc = i;
    }
    else if(
      (strlen(ia.argv[i]))   &&
      (i>=start)             &&
      (interpreter == NULL)  &&
      (!regex_search (ia.argv[i], dash))
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
  if(Debug>=2) printf("Debug: hashbang='%s'\n", line);
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
  argv_t n     = {0, (char **)NULL}; //
  argv_t c     = {0, (char **)NULL}; //
  argv_t e     = {0, (char **)NULL}; //
  int set      = 0;                  // cnf args set or add
  int int_loc  = 0;                  // interpreter nargv location
  int oscr_loc = 0;                  //
  int nscr_loc  = 0;                  // script      nargv location
  int escr_loc = 0;                  //
  int i, j, k;                       // Loop counters
  int found, nstart;                 //
  string interpreter_base;           // basename of interpreter
  hash_t add_args;                   //
  regex dash   = set_dash();         //
  
  if(Debug>=2) printf("Debug: Func=env2\n");

  /****************************************
   * inline helper function to reduce duplicated code for splitting args on '~'
   ****************************************/
  auto split_sc = [&](int cfg) {
    char *arg;
    char *pos;
    char *arg1;
    char *arg2;
    
    // cfg=1 use c (config)
    if(cfg) {
      arg = c.argv[k++];
    // cfg=0 use n (new)
    } else {
      arg = n.argv[i++];
    }
    
    // if arg has embedded '~' then split into two args
    // Allow for interpreter flags to have args seperated by space, not just = or :
    // e.g. -a~foo   becomes -a foo  (now 2 seperate args)
    //      -a:foo   no-chng
    //      -a=foo   no-chng
    // Or allow non-dashed prefixed flag
    // e.g. ~arg     becomes arg
    pos = strchr(arg, '~');
    if(flags["allow"].l() && pos) {
      // ~ is ghost flag marker
      if(pos == arg) {
        e.argv[j++] = arg+1;
      // ~ is split maker
      } else {
        *pos = '\0';
        arg1 = arg;
        arg2 = pos+1;
        e.argv[j++] = arg1;
        e.argv[j++] = arg2;
      }
    } else {
      e.argv[j++] = arg;
    }
  };

  /****************************************
   * body of env2()
   ****************************************/
  
  // main() should check for this - make sure we have the right number of args
  if(o.argc == 1) {
    throw StdException("No args found");
  }
  
#if   KERNEL_SPLIT == 0
  // split up argv[1] (from #! line) ///////////////////////////////////////////
  n = split_string(o.argv[1]);
#elif KERNEL_SPLIT == 1
  // get hashbang line from script
  o = read_hashbang(o);  
  // split up argv[1] (from #! line) ///////////////////////////////////////////
  n = split_string(o.argv[1]);
#elif KERNEL_SPLIT == 2
  // Yes this is silly to redo the work the kernel already did right, but
  //  a) it's too much work to accommodate KERNEL_SPLIT == 2 "correctly"
  //  b) i have yet to find a kernel that does KERNEL_SPLIT == 2 
  // get hashbang line from script
  o = read_hashbang(o);  
  // split up argv[1] (from #! line) ///////////////////////////////////////////
  n = split_string(o.argv[1]);
#else
#error "Must define KERNEL_SPLIT as 0, 1, or 2"
#endif

  // check that we have an interpreter from #! /////////////////////////////////
#ifdef MAKE_EXE
  // flags["nstart"]  set by parse_flags()      // E after env2 flags
  oscr_loc         = 2;                         // first possible place for script
  // Set flags for exe call
  nstart           = flags["nstart"].i();       // after env2 flags
  int_loc          = nstart;                    // interpreter
  interpreter_base = basename(n.argv[int_loc]); // from n
#else
  flags["nstart"]  = 0;                         // direct call
  oscr_loc         = 1;                         // first possible place for script
  // Set flags for lib call
  nstart           = flags["nstart"].i();       // after env2 flags
  int_loc          = nstart;                    // interpreter
  interpreter_base = basename(o.argv[int_loc]); // from o
#endif

  // look for args meant for script, not interpreter ///////////////////////////
  found=0;  // did we find the delim ~~
  if( flags["delim"].l() ) {
    for(i=nstart; i < n.argc; i++) {
      // options
      if( strcmp(n.argv[i], flags["delim"].c() )==STRCMP_TRUE) {
        found = i+1;
        break;
      }
    }
  }

  // check that we have a script next //////////////////////////////////////////
  // find script location
  while( 
    (oscr_loc < o.argc) && 
    regex_search(o.argv[oscr_loc], dash)
  ) {
    oscr_loc++;
  }
  if(
    (oscr_loc == o.argc) || 
    regex_search(o.argv[oscr_loc], dash)
  ) {
    throw StdException("No script found");
  }
  if(Debug) fprintf(stderr, "Debug: oscr_loc: %d\n", oscr_loc);

  // add script  ///////////////////////////////////////////////////////////////
  if(found) {
    nscr_loc = found-1;
    n.argv[nscr_loc] = strndup( o.argv[oscr_loc], MAX_STR_CONST-1);
  } else {
    if(oscr_loc == 2) {
      nscr_loc = n.argc;
      n.argv[nscr_loc] = strndup( o.argv[oscr_loc], MAX_STR_CONST-1);
      n.argc++;
    } else {
      nscr_loc = n.argc + (oscr_loc-2);
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
  if( !flags["norc"].i() ) {
    add_args = vars2();
    if(Debug) fprintf(stderr, "Debug: interpreter_base: %s\n", interpreter_base.c_str());
    if(add_args.find(interpreter_base) != add_args.end()) {
      char *add_args_s = (char *)add_args[interpreter_base].c();

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
  set = 0;  // set=1 or add=0
  while(j < e.argc) {
    // add config args ////////////////////////////////////
    if(c.argc && k<c.argc) {
      // if set_arg - vars2() prepends special marker ~~ to let us know this is a set, not add
      if(strncmp(c.argv[k],"~~",2)==STRCMP_TRUE) {
        set = 1;         // this is a set, not append
        c.argv[k] += 2;  // skip over special marker
        // if empty string
        if ( !strlen(c.argv[k]) && !flags["pre"].i() ) {
          if(Debug) fprintf(stderr, "Debug: skipping empty cfg interprter arg at %d\n", k);
          k++;
          // set it
        } else {
          if(Debug) fprintf(stderr, "Debug: setting cfg interprter arg: %s\n", c.argv[k]);
          split_sc(1);
        }
      // else add_arg
      } else {
        // if empty string
        if ( !strlen(c.argv[k]) && !flags["pre"].i() ) {
          if(Debug) fprintf(stderr, "Debug: skipping empty cfg interprter arg at %d\n", k);
          k++;
          // add it
        } else {
          if(Debug) fprintf(stderr, "Debug: adding cfg interprter arg: %s\n", c.argv[k]);
          split_sc(1);
        }
      }
    // add nargv args //////////////////////////////////////
    } else {
      // skip intr args
      if(set && i < nscr_loc ) {
        if(Debug) fprintf(stderr, "Debug: skipping nargv interprter arg: %s\n", n.argv[i]);
        i++;
      // add intr args
      } else {
        split_sc(0);
        if( i-1 == nscr_loc ) {
          escr_loc = j-1;
        }
      }
    }
  }
  e.argv[j] = NULL;

  // dump args /////////////////////////////////////////////////////////////////
  if(Debug) fprintf(stderr, "Debug: hashbang='%s'\n", o.argv[1]);
  if( Debug && !flags["dump"].i() ) {
    for(i=0; i<j; i++) fprintf(stderr, "Debug: argv[%d]='%s'\n", i, e.argv[i]);
  }
  if( flags["dump"].i() ) {
    printf("------env-----\n");
    printf("arg%d='%s'\n",0,o.argv[0]);
    for(i=0; i<nstart; i++) {
      printf("arg%d='%s'\n",i+1,n.argv[i]);
    }
    dumpargs(j, e.argv, escr_loc);
  }

  /// return new vars ////////////////////////////////////////////////
  return(e);
}

void init_flags(int found, int nstart) {
  flags["nstart"]   = nstart;     // [internal] end of env2 args
  flags["cmt"]      = 0;          // allow comments #
  flags["delim"]    = string(""); // Delimiter to sep interpreter args from script args
  flags["dump"]     = 0;          // Dump args flag
  flags["exp"]      = 0;          // Expand standard backslash-escaped characters
  flags["norc"]     = 0;          // Do not read rc file
  flags["pre"]      = 0;          // preserve empty args
  flags["sbs"]      = 0;          // Strip backslashes
  flags["allow"]    = string(""); // Allow hints to this prog so as not to split on wrong spaces
}

// #############################################################################

#ifdef MAKE_EXE

/**************************************************************
 * parse_flags - parse my flags
 **************************************************************/
hash_t parse_flags(char *flags_str) { 
  int nstart = 0;                            // nargv start element
  int j = 0;

  init_flags();

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
        // allow split on '~' and allow ~ as non-dashed flag prefix marker
        else if(*(flags_str+j) == 'a') {
          flags["allow"] = string("~");
          if(Debug) fprintf(stderr, "Debug: Allow split on '~' activated\n");
        }
        // comment
        else if(*(flags_str+j) == 'c') {
          flags["cmt"] = 1;
          if(Debug) fprintf(stderr, "Debug: Comment mode activated\n");
        }
        // debug
        else if(*(flags_str+j) == 'd') {
          Debug++;
          if(Debug==1) fprintf(stderr, "Debug: Debug mode activated\n");
        }
        // emit (dump) - this is really a debug thing
        else if(*(flags_str+j) == 'e' || *(flags_str+j) == 'D' ) {
          flags["dump"] = 1;
          if(Debug) fprintf(stderr, "Debug: Dump mode activated\n");
        }
        // find (delim)
        else if(*(flags_str+j) == 'f') {
#ifdef F_TAKES_ARG
          if(*(flags_str+j+1) == '=' || *(flags_str+j+1) == ':') {
            char delim[40];
            strcpy(delim, (char *)flags_str+j+2);
            flags["delim"] = delim;
            b=1;
          } else
#endif
            flags["delim"] = string( "~~") ;
          if(Debug) fprintf( stderr, "Debug: Delim mode activated with '%s'\n", flags["delim"].c() );
          // if delim spec'd, break as this delim string must term with a space
          if (b) {
            b=0;
            break; // from inner while
          }
        }
        // no rc file
        else if(*(flags_str+j) == 'n' ) {
          flags["norc"] = 1;
          if(Debug) fprintf(stderr, "Debug: No rc file mode activated\n");
        }
        // preserve empty args (why on earth?) -- feature overload
        else if(*(flags_str+j) == 'p') {
          flags["pre"] = 1;
          if(Debug) fprintf(stderr, "Debug: Perserve empty args mode activated\n");
        }
        // strip backslashes (why not by default?) -- feature overload
        else if(*(flags_str+j) == 's' ) {
          flags["sbs"] = 1;
          if(Debug) fprintf(stderr, "Debug: Strip mode activated\n");
        }
        // expand backslash-escaped chars
        else if(*(flags_str+j) == 'x' ) {
          flags["exp"] = 1;
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
    // found non-flag argument (may not find in Solaris)
    else {
      break; // from outter while
    }
    flags_str += j;
  } // while
  flags["nstart"] = to_string(nstart);
  if(Debug) fprintf( stderr, "Debug: nstart: %s\n", flags["nstart"].c() );
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
    char Argv0I[MAX_STR_CONST];
    
    snprintf(Argv0I, MAX_STR_CONST-1, "%s/%s", PREFIX_S, basename(Argv0));
    out = ret==0 ? stdout : stderr;
    fprintf(out,
            "Usage:                                                                  \n"
            "  #!%1$s [-flags] <interpreter> [<interpreter_args>]                    \n"
            "  #!%1$s -[flags]f <interpreter> [<interpreter_args>] ~~ <script_args>  \n\n"
            "Where flags are one or more of:                                         \n"
            "  a     : Allow ~ to mark non-dashed flag AND allow space sep flag args \n"
            "  c     : Comments mode (stuff after # is discarded)                    \n"
            "  d     : Debug mode (repeat for more)                                  \n"
            "  e     : Emit mode (call dumpargs)                                     \n"
#ifdef F_TAKES_ARG
            "  f[=S] : Find script opts separated by delim (S=~~ if not specified)   \n"
#else
            "  f     : Find script opts separated by delimiter ~~                    \n"
#endif
            "  n     : No rc file read                                               \n"
            "  p     : Preserve empty args                                           \n"
            "  s     : Strip backslashes                                             \n"
            "  x     : eXpand standard backslash-escaped characters                  \n"
            "  v     : print the Version of this program                             \n"
            "  h     : this Help                                                     \n\n"
            "Notes:                                                                  \n"
            "  * all flags must be combined into one string                          \n\n"
            "Examples:                                                               \n"
            "  #!%1$s -sn perl -w                                                    \n"
            "  #!%1$s bash -x -v                                                     \n"
#ifdef F_TAKES_ARG
            "  #!%1$s -def=@@ python @@ -sf                                          \n"
#endif
            "  #!%1$s -c python # -*-Python-*-                                       \n",
            Argv0I
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
