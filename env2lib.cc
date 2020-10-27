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
extern int parse_flags(char *flags_str);  // xxx rename and move to .hh

using namespace std; 

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
 * parse hashbang line
 *   input:   input   // Input string
 *   output:  output  // Output string array
 *   return:  count   // Number of strings found
 **************************************************************/
int parse_input(char *input, char output[MAX_STR_CONST][MAX_STR_CONST]) {
  char *input_ptr;    // Input string pointer
  char *output_ptr;   // Output string pointer
  int count=0;        // Number of strings found
  int ccnt=0;         // Character count of current string
  int in_sq=0;        // Inside single quote
  int in_dq=0;        // Inside double quote
  int in_bs=0;        // Inside backslash

  /****************************************
   * inline helper function to reduce duplicated code for quote parsing
   ****************************************/
  auto found_q = [&](int sq) {
    // set in_q1 and in_q2 refs
    int *in_q1 =  sq ? &in_sq : &in_dq;
    int *in_q2 = !sq ? &in_sq : &in_dq;

    // if not in quoted string
    if(!*in_q2 && !in_bs) {
      // if closed on empty string, add to array and move to next argv
      if(*in_q1 && ccnt==0 && flags["pre"].length()) {
        *output_ptr = ENDOFSTR;
        output_ptr = output[++count];
      }
      // flip flag
      *in_q1=1-*in_q1;
    } else {
      // add to string
      *output_ptr++ = *input_ptr;
      ccnt++;
    }
    // clear in_bs
    in_bs=0;
  };
  /***********************************/

  // init in and out pointers
  input_ptr = input;
  output_ptr = (char *)output;
  // loop over input string
  while(*input_ptr) {
    // whitespace //////////////////////////////////////
    if(
      *input_ptr==SPACE   ||
      *input_ptr==TAB     ||
      *input_ptr==NEWLINE ||
      *input_ptr==RETURN 
    ) {
      // not in single, double, or backslash
      if(!in_sq && !in_dq && !in_bs) {
        // and we have a string, term string and move to next argv
        if(ccnt) {
          *output_ptr = ENDOFSTR;
          output_ptr = output[++count];
          ccnt=0;
        }
        // discard unquoted whitespace
      } 
      // add to string
      else {
        *output_ptr++ = *input_ptr;
        ccnt++;
      }
      in_bs=0;
    }
    // not whitespace or quote (regular character) //////////////////////
    else if (
      *input_ptr != SPACE       &&
      *input_ptr != TAB         &&
      *input_ptr != NEWLINE     &&
      *input_ptr != RETURN      &&
      *input_ptr != BACKSLASH   &&
      *input_ptr != DOUBLEQUOTE &&
      *input_ptr != SINGLEQUOTE
    ) {
      // comment
      if(
        (flags["cmt"].length())       && 
        (*input_ptr     == COMMENT)   && 
        (*(input_ptr-1) == SPACE)     &&
        (*(input_ptr-2) != BACKSLASH) &&
        !in_sq                        &&
        !in_dq                        &&
        ccnt == 0
      ) {
        *input_ptr = ENDOFSTR;
        break;
      // regular character
      } else {
        if(
          flags["exp"].length() && 
          in_bs                 &&
          strchr("abefnrtv\\",*input_ptr)
        ) {
          char expa[] = "abefnrtv\\";
          char expc[] = {7,8,27,12,10,13,9,11,92};
          long pos = (strchr(expa,*input_ptr) - expa);

          output_ptr--;
          *output_ptr++ = expc[pos];
        } else {
          *output_ptr++ = *input_ptr;
          ccnt++;
        }
      }
      in_bs=0;
    }
    // single quote //////////////////////////////////
    else if (*input_ptr==SINGLEQUOTE) {
      found_q(1);
    }
    // double quote ///////////////////////////////////
    else if (*input_ptr==DOUBLEQUOTE) {
      found_q(0);
    }
    // back slash (escape char) ///////////////////////
    else if (*input_ptr==BACKSLASH) {
      in_bs=1-in_bs;
      *output_ptr++ = *input_ptr;
      ccnt++;
    }
    // move to next input char 
    input_ptr++;
  } // while
  // catch final string ///////////////////////////
  if(!in_sq && !in_dq && !in_bs) {
    // and we have a string, term string and increase count
    if(ccnt) {
      *output_ptr = ENDOFSTR;
      count++;
    }
  }
  // dangling quote or escape /////////////////////
  else if(ccnt) {
    fprintf(stderr, "%s error: unmatched quote\n", Argv0);
  }
  // return number of strings found
  return(count);
}

/****************************************************************
 * env2
 **************************************************************/
void env2 (int *argcp, char ***argvp) {
  char **argv;                               // Orig argv
  int    argc;                               // size of argv
  char  nargv[MAX_STR_CONST][MAX_STR_CONST]; // New  argv (as array of arrays)
  int   nargc = 0;                           // size of nargv
  char  cargv[MAX_STR_CONST][MAX_STR_CONST]; // config  argv (as array of arrays)
  int   cargc = 0;                           // size of cargv
  char *eargv[MAX_STR_CONST];                // New  argv (as array of pointers)
  int   eargc = 0;                           // size of eargv
  int i, j, k;                               // Loop counters
  int set;                                   // cnf args set or add
  int nstart = 0;                            // nargv start element
  int int_loc = 0;                           // interpreter nargv location
  int scr_loc = 0;                           // script      nargv location
  string interpreter_base;                   // basename of interpreter
  char hashbang[1024] = "";
  
  argv = *argvp;                       // Orig argv
  argc = *argcp;                       // size of argv

  // make sure we have the right number of args
  if(argc == 1) {
    fprintf(stderr, "%s error: No interpreter found\n", Argv0);
    usage(1);
  }

  // parse my flags 
  strncpy(hashbang, argv[1], sizeof(hashbang)-1);
  nstart = parse_flags(argv[1]);

  // split up argv[1] (from #! line) ///////////////////////////////////////////
  nargc = parse_input(argv[1], nargv);
  
  // restore argv[1] if undocumented -O flag given /////////////////////////////
  if(flags["orig"].length()) {
    nargc = nstart+2;
    char *argv1 = strstr(argv[1], nargv[nstart]);
    strncpy(nargv[nstart+1], argv1+strlen(nargv[nstart])+1, MAX_STR_CONST-1);
  }
  
  // if sbs mode, strip off excess backslashes from nargs  /////////////////////
  if(flags["sbs"].length()) {
    for(i=0; i< nargc; i++) {
      char nargvx[MAX_STR_CONST];
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
      strncpy(nargv[i], nargvx, MAX_STR_CONST-1);
    }
  }
  
  // check that we have an interpreter from #! /////////////////////////////////
  if(!flags["found"].length()) {
    fprintf(stderr, "%s error: no interpreter found\n", argv[0]);
    usage(1);
  }
  int_loc = nstart;
  
  // look for args meant for script, not interpreter ///////////////////////////
  flags["found"] = "";
  if(flags["delim"].length()) {
    for(i=nstart;i < nargc;i++) {
      // options
      if(strncmp(nargv[i], flags["delim"].c_str(), MAX_STR_CONST-1 )==STRCMP_TRUE) {
        flags["found"] = to_string(i+1);
        break;
      }
    }   
  }
  
  // check that we have a script next //////////////////////////////////////////
  if(argc<3 || argv[2][0] == '-') {
    fprintf(stderr, "%s error: no script found\n", argv[0]);
    usage(1);
  }
  
  // add script  ///////////////////////////////////////////////////////////////
  if(flags["found"].length()) {
    scr_loc = stoi(flags["found"])-1;
    strncpy(nargv[scr_loc], argv[2], MAX_STR_CONST-1);
  } else {
    scr_loc = nargc;
    strncpy(nargv[nargc++], argv[2], MAX_STR_CONST-1);
  }
  
  // add remaining args for script (from user) /////////////////////////////////
  for(j=3;j<argc;j++) {
    strncpy(nargv[nargc++], argv[j], MAX_STR_CONST-1);
  }
  
  // prep conf args ////////////////////////////////////////////////////////////
  eargc = nargc-nstart;
  if(!flags["norc"].length()) {
    vars5();
    interpreter_base = basename(nargv[int_loc]);
    if(Debug) fprintf(stderr, "Debug: interpreter_base: %s\n", interpreter_base.c_str());
    if(add_args.find(interpreter_base) != add_args.end()) {
      char *add_args_s = (char *)add_args[interpreter_base].c_str();
    
      cargc = parse_input(add_args_s, cargv);
      eargc += cargc;
    }
  }
  
  // copy from cargv & nargv to eargv //////////////////////////////////////////
  i=nstart; // nargv (nstart is first non-env2 flag arg)
  j=0;      // eargv
  k=0;      // cargv
  
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
  if(Debug) fprintf(stderr, "Debug: hashbang=%s\n", hashbang);
  if(Debug && !flags["dump"].length()) {
    for(i=0;i<j;i++) fprintf(stderr, "Debug: argv[%d]='%s'\n", i, eargv[i]);
  }
  if(flags["dump"].length()) {
    printf("------env-----\n");
    printf("arg%d='%s'\n",0,argv[0]);
    for(i=0;i<nstart;i++) {
      printf("arg%d='%s'\n",i+1,nargv[i]);
    }
    dumpargs(j, eargv);
  }
  
  /// move pointers to new vars ////////////////////////////////////////////////
  *argvp = eargv;   
  *argcp = eargc;
}
