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

extern void usage(int ret);               // xxx rename and move to .hh

using namespace std; 

#define STRCMP_TRUE    0
#define ENDOFSTR      '\0'

/**************************************************************
 * parse_flags
 **************************************************************/
int parse_flags(char *flags_str) {
  int nstart = 0;                            // nargv start element
  int j = 0;

  flags["cmt"]      = "";                     // comments 
  flags["pre"]      = ""; 
  flags["dump"]     = "";                     // Dump args flag
  flags["sbs"]      = "";                     // Strip backslashes
  flags["norc"]     = "";                     // Do not read rc file
  flags["orig"]     = "";                     // Do NOT split argv[1] (undocumented)
  flags["delim"]    = "";                     // Delimiter to sep interpreter args from script args
  flags["exp"]      = "";                     // Expand  backslash-escaped characters
  flags["found"]    = "";                     // found non flag 

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
          if(*(flags_str+j+1) == '=' || *(flags_str+j+1) == ':') {
            char delim[40];
            long l = (long) (strchr((char *)flags_str+j+2,' ') - (flags_str+j+2));
            strncpy(delim, (char *)flags_str+j+2, l);
            delim[l] = '\0';
            flags["delim"] = delim;
            j += l+2;
            b=1;
          } else {
            flags["delim"] = (char *) "~~";
          }
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
        // keep original #! behaviour (why on earth!?)
        else if(*(flags_str+j) == 'O' ) {
          flags["orig"] = "1";
          if(Debug) fprintf(stderr, "Debug: Undocumented Orig mode activated (why!?)\n");
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
    flags_str += j+1;
  } // while
  return nstart;
}
