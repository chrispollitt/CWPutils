/*****************************************************************
 * env replacement
 *
 * Has these features over and above the classic env(1):
 * - splits out interpreter arg string into separate args
 * - has a config file that allows for
 *   ~ environment variables to be set
 *   ~ interpreter args to be added in per interpreter
 * - can call dumpargs(1) if desired
 * - has an optional section for hardcoded script args
 * - can ignore comments on #! line
 * - can convert the script path to Windows format (Cygwin, -w)
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
#ifdef __CYGWIN__
#include <sys/cygwin.h>
#endif
#ifdef MAKE_EXE
#include "env2.hh"
#endif

using namespace std;

#ifdef MAKE_EXE
// Define Globals
char *Argv0;                   // Name of program
int   Debug;                   // Debug flag
#endif

#define DEF_TO_STR2(s) #s
#define DEF_TO_STR(s) DEF_TO_STR2(s)

// Constants
#define VERSION   "2.0"
#define YEAR      "2020-2026"

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
 * set_dash - set the dash regular expression depending on flags.allow - PRIVATE
 **************************************************************/
regex set_dash(const Flags &flags) {
  regex dash;
  string re1 = string(R"(^['"]?[-)");
  string re2 = string(R"(])");    
  
  if( !flags.allow.empty() ) {
     string re = re1 + flags.allow.front() + re2;
     dash= regex( re );
  } else {
     string re = re1 + re2;
     dash= regex( re );
  }
  
  return(dash);
}

/****************************************************************
 * read_hashbang - read #! line from script file
 *   input  = ia (argv_t)
 *   output = oa (argv_t) 
 **************************************************************/
argv_t read_hashbang(const Flags &flags, argv_t ia) {
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
  regex dash        = set_dash(flags);
  
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
    }
  }
  else {
    throw StdException("unable to determine script filename");
  }
  read = getline(&line, &linesze, fh);
  fclose(fh);
  if(
    (read < 5)                      ||
    ( strncmp(line, "#!/", 3) != 0 )
  ) {
    throw StdException("script file #! line not correct: ", script);
  }

  // skip over interpreter
  linep = strchr(line, ' ');
  if(linep == NULL) {
    throw StdException("script file #! line has no interpreter arguments: ", script);
  }
  line = linep+1;
  // strip trailing newline (and CR), but nothing else
  linep = line+strlen(line);
  while(linep > line && (linep[-1] == '\n' || linep[-1] == '\r')) {
    linep--;
  }
  *linep = '\0';
  if(Debug>=2) printf("Debug: hashbang='%s'\n", line);
  oa.argc = 0;
  oa.argv = (char **)calloc(ia.argc + 3, sizeof(char *));
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
argv_t env2(const Flags &flags, argv_t o) {
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
  regex dash   = set_dash(flags);         //
  
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
    // Allow for interpreter flags to have args separated by space, not just = or :
    // e.g. -a~foo   becomes -a foo  (now 2 separate args)
    //      -a:foo   no-change
    //      -a=foo   no-change
    // Or allow non-dashed prefixed flag
    // e.g. ~arg     becomes arg
    pos = strchr(arg, '~');
    if(!flags.allow.empty() && pos) {
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
  n = split_args(flags, o.argv[1]);
#elif KERNEL_SPLIT == 1
  // The kernel splits the #! line but mangles escaped spaces, so re-read the
  //   #! line from the script.  (A kernel that splits it perfectly would not
  //   need this, but none is known, and this is correct for it too.)
  // get hashbang line from script
  o = read_hashbang(flags, o);
  // split up argv[1] (from #! line) ///////////////////////////////////////////
  n = split_args(flags, o.argv[1]);
#else
#error "Must define KERNEL_SPLIT as 0 or 1"
#endif

  // make room in n for the script and user args added below (+2 for script, NULL)
  {
    char **grown = (char **)calloc(n.argc + o.argc + 2, sizeof(char *));
    for(i=0; i < n.argc; i++) grown[i] = n.argv[i];
    free(n.argv);
    n.argv = grown;
  }

  // check that we have an interpreter from #! /////////////////////////////////
#ifdef MAKE_EXE
  // flags.nstart  set by parse_flags()      // E after env2 flags
  oscr_loc         = 2;                         // first possible place for script
  // Set flags for exe call
  nstart           = flags.nstart;       // after env2 flags
  int_loc          = nstart;                    // interpreter
  if(int_loc >= n.argc) {
    throw StdException("No interpreter found");
  }
  interpreter_base = basename(n.argv[int_loc]); // from n
#else
  // nstart is 0 for a direct (library) call
  oscr_loc         = 1;                         // first possible place for script
  // Set flags for lib call
  nstart           = 0;                         // no env2 flags
  int_loc          = nstart;                    // interpreter
  interpreter_base = basename(o.argv[int_loc]); // from o
#endif

  // look for args meant for script, not interpreter ///////////////////////////
  found=0;  // did we find the delim ~~
  if( !flags.delim.empty() ) {
    for(i=nstart; i < n.argc; i++) {
      // options
      if( strcmp(n.argv[i], flags.delim.c_str() )==STRCMP_TRUE) {
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
    n.argv[nscr_loc] = strdup( o.argv[oscr_loc] );
  } else {
    if(oscr_loc == 2) {
      nscr_loc = n.argc;
      n.argv[nscr_loc] = strdup( o.argv[oscr_loc] );
      n.argc++;
    } else {
      nscr_loc = n.argc + (oscr_loc-2);
      // o.argv[oscr_loc] will be added below
    }
  }

  // add remaining args for script (from user) /////////////////////////////////
  for(j = (oscr_loc == 2) ? 3 : 2; j<o.argc; j++) {
    n.argv[n.argc] = strdup( o.argv[j] );
    n.argc++;
  }

  // prep conf args ////////////////////////////////////////////////////////////
  e.argc = n.argc-nstart;
  if( !flags.norc ) {
    add_args = vars2(flags);
    if(Debug) fprintf(stderr, "Debug: interpreter_base: %s\n", interpreter_base.c_str());
    if(add_args.find(interpreter_base) != add_args.end()) {
      char *add_args_s = (char *)add_args[interpreter_base].c();

      c = split_args(flags, add_args_s);
      e.argc += c.argc;
    }
  }

  // copy from cargv & nargv to eargv //////////////////////////////////////////
  i=nstart; // nargv (nstart is first non-env2 flag arg)
  j=0;      // eargv
  k=0;      // cargv
  // each arg may be split in two by '~' (allow mode), so allow twice e.argc
  e.argv = (char **)calloc(2*e.argc + 2, sizeof(char *));

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
        if ( !strlen(c.argv[k]) && !flags.pre ) {
          if(Debug) fprintf(stderr, "Debug: skipping empty cfg interpreter arg at %d\n", k);
          k++;
          // set it
        } else {
          if(Debug) fprintf(stderr, "Debug: setting cfg interpreter arg: %s\n", c.argv[k]);
          split_sc(1);
        }
      // else add_arg
      } else {
        // if empty string
        if ( !strlen(c.argv[k]) && !flags.pre ) {
          if(Debug) fprintf(stderr, "Debug: skipping empty cfg interpreter arg at %d\n", k);
          k++;
          // add it
        } else {
          if(Debug) fprintf(stderr, "Debug: adding cfg interpreter arg: %s\n", c.argv[k]);
          split_sc(1);
        }
      }
    // add nargv args //////////////////////////////////////
    } else {
      // skip intr args
      if(set && i < nscr_loc ) {
        if(Debug) fprintf(stderr, "Debug: skipping nargv interpreter arg: %s\n", n.argv[i]);
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

#ifdef __CYGWIN__
  // convert script path to Windows format (like cygpath -w) ///////////////////
  if( flags.win ) {
    int sl = 0;
    // find the script in the final arg list (escr_loc is not reliable here)
    for(i=1; i<j; i++) {
      if( strcmp(e.argv[i], o.argv[oscr_loc])==STRCMP_TRUE ) { sl = i; break; }
    }
    if(sl) {
      char *wpath = (char *)cygwin_create_path(CCP_POSIX_TO_WIN_A, e.argv[sl]);
      if(wpath) {
        if(Debug) fprintf(stderr, "Debug: win path: %s -> %s\n", e.argv[sl], wpath);
        e.argv[sl] = wpath;
        escr_loc = sl;
      } else {
        fprintf(stderr, "Warning: cannot convert '%s' to Windows path: %s\n", e.argv[sl], strerror(errno));
      }
    }
  }
#endif

  // dump args /////////////////////////////////////////////////////////////////
  if(Debug) fprintf(stderr, "Debug: hashbang='%s'\n", o.argv[1]);
  if( Debug && !flags.dump ) {
    for(i=0; i<j; i++) fprintf(stderr, "Debug: argv[%d]='%s'\n", i, e.argv[i]);
  }
  if( flags.dump ) {
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

// #############################################################################

#ifdef MAKE_EXE

/**************************************************************
 * env2_spec - the table of my switches
 *   Used both to parse them (parse_flags) and to print the help (usage),
 *   so the two cannot drift apart.  Switches with no help text (the old
 *   'D') parse but are not listed.  Help is listed in table order.
 **************************************************************/
static const std::vector<SwitchSpec> &env2_spec() {
  static const std::vector<SwitchSpec> spec = {
    //  letter longname   optarg  help
    {'a', NULL,      false, "Allow ~ to mark non-dashed flag AND allow space sep flag args"},
    {'c', NULL,      false, "Comments mode (stuff after # is discarded)"},
    {'d', NULL,      false, "Debug mode (repeat for more)"},
    {'e', NULL,      false, "Emit mode (call dumpargs)"},
    {'D', NULL,      false, NULL},   // emit, old spelling
#ifdef F_TAKES_ARG
    {'f', NULL,      true,  "Find script opts separated by delim (S=~~ if not specified)"},
#else
    {'f', NULL,      false, "Find script opts separated by delimiter ~~"},
#endif
    {'L', NULL,      false, "Legacy splitter, not shellwords (implied by s, p, x)"},
    {'n', NULL,      false, "No rc file read"},
    {'p', NULL,      false, "Preserve empty args (legacy splitter)"},
    {'s', NULL,      false, "Strip backslashes (legacy splitter)"},
    {'S', NULL,      false, "Shellwords splitting, like Perl (the default)"},
    {'w', NULL,      false, "Windows path: convert script path like cygpath -w (Cygwin)"},
    {'x', NULL,      false, "eXpand backslash-escaped characters (legacy splitter)"},
    {'v', "version", false, "print the Version of this program"},
    {'h', "help",    false, "this Help"},
  };
  return spec;
}

/**************************************************************
 * parse_flags - parse my flags
 **************************************************************/
Flags parse_flags(char *flags_str) {
  Flags flags;
  bool seenS = false;                // -S given explicitly
  const std::vector<SwitchSpec> &spec = env2_spec();

  // strip off args meant for me (from #! line) ////////////////////////////////
  SwitchResult r = parse_switches(flags_str, spec);

  for(size_t i=0; i < r.given.size(); i++) {
    const SwitchGiven &g = r.given[i];
    switch(g.letter) {
      // help
      case 'h':
        usage(0);
        break;
      // version
      case 'v':
        usage(2);
        break;
      // allow split on '~' and allow ~ as non-dashed flag prefix marker
      case 'a':
        flags.allow = "~";
        if(Debug) fprintf(stderr, "Debug: Allow split on '~' activated\n");
        break;
      // comment
      case 'c':
        flags.cmt = true;
        if(Debug) fprintf(stderr, "Debug: Comment mode activated\n");
        break;
      // debug
      case 'd':
        Debug++;
        if(Debug==1) fprintf(stderr, "Debug: Debug mode activated\n");
        break;
      // emit (dump) - this is really a debug thing
      case 'e':
      case 'D':
        flags.dump = true;
        if(Debug) fprintf(stderr, "Debug: Dump mode activated\n");
        break;
      // find (delim)
      case 'f':
        flags.delim = g.hasarg ? g.arg : string("~~");
        if(Debug) fprintf( stderr, "Debug: Delim mode activated with '%s'\n", flags.delim.c_str() );
        break;
      // no rc file
      case 'n':
        flags.norc = true;
        if(Debug) fprintf(stderr, "Debug: No rc file mode activated\n");
        break;
      // preserve empty args (why on earth?) -- feature overload
      case 'p':
        flags.pre = true;
        if(Debug) fprintf(stderr, "Debug: Preserve empty args mode activated\n");
        break;
      // strip backslashes (why not by default?) -- feature overload
      case 's':
        flags.sbs = true;
        if(Debug) fprintf(stderr, "Debug: Strip mode activated\n");
        break;
      // split like Perl's shellwords() (the default; blocks the s/p/x implication below)
      case 'S':
        seenS = true;
        if(Debug) fprintf(stderr, "Debug: Shellwords mode activated\n");
        break;
      // use the legacy splitter
      case 'L':
        flags.legacy = true;
        if(Debug) fprintf(stderr, "Debug: Legacy splitter activated\n");
        break;
      // convert script path to Windows format (Cygwin only)
      case 'w':
        flags.win = true;
        if(Debug) fprintf(stderr, "Debug: Windows path mode activated\n");
        break;
      // expand backslash-escaped chars
      case 'x':
        flags.exp = true;
        if(Debug) fprintf(stderr, "Debug: Expand mode activated\n");
        break;
    }
  }
  // -s, -p and -x only mean something to the legacy splitter, so they select it
  // (unless -S was given explicitly), which keeps older #! lines working as before
  if(!seenS && !flags.legacy && (flags.sbs || flags.pre || flags.exp)) {
    flags.legacy = true;
    if(Debug) fprintf(stderr, "Debug: Legacy splitter implied by s, p or x\n");
  }
  flags.nstart = r.clusters;
  if(Debug) fprintf( stderr, "Debug: nstart: %d\n", flags.nstart );
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
            "Where flags are one or more of:                                         \n",
            Argv0I
           );
    // the flag lines come from the same table that parses them
    fputs(switch_help(env2_spec()).c_str(), out);
    fprintf(out,
            "\n"
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

  Flags flags;

  try {
    // Parse out my flags
    flags = parse_flags(o.argv[1]);

    // Call the main env2() function
    e = env2(flags, o);
  } catch (StdException &exc) {
    fprintf(stderr, "%s error: %s\n", Argv0, exc.what());
    usage(1);
  }

  // Exec the interpreter
  execvp(e.argv[0], e.argv);

  // Oh dear, there was an error
  code = (errno == ENOENT) ? 127 : 126;  // same convention as env(1) and the shell
  fprintf(stderr, "%s error: exec() failed: ", Argv0);
  perror(e.argv[0]);
  return(code);
}

#endif
