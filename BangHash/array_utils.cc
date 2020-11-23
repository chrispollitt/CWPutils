/*****************************************************************
 * split strings and merge arrays
 ****************************************************************/

// Includes
#include <unistd.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
//#include <malloc.h>
#include <errno.h>
#include <libgen.h>
#include "env2lib.hh"

using namespace std;

// Constants
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
 * split out string into array
 *   input:   input   // Input string
 *   return:  o       // Output argv_t
 **************************************************************/
argv_t split_string(char *input) {
  argv_t o;
  char **output;
  char *output_tmp;   // tmp placeholder for output string
  char *input_ptr;    // Input string pointer
  char *output_ptr;   // Output string pointer
  int count=0;        // Number of strings found
  int ccnt=0;         // Character count of current string
  int in_sq=0;        // Inside single quote
  int in_dq=0;        // Inside double quote
  int in_bs=0;        // Inside backslash

  if(Debug>=2) printf("Debug: Func=split_string\n");

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
      if(*in_q1 && ccnt==0 && flags["pre"].i() ) {
        *output_ptr = ENDOFSTR;
        output[count++] = output_tmp;
        output_tmp = (char *)malloc(MAX_STR_CONST);
        output_ptr = output_tmp;
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

  /****************************************
   * body of split_string()
   ****************************************/
  output = (char **)calloc(MAX_STR_CONST, sizeof(char *));

  // init in and out pointers
  input_ptr = input;
  output_tmp = (char *)malloc(MAX_STR_CONST);
  output_ptr = output_tmp;
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
          output[count++] = output_tmp;
          output_tmp = (char *)malloc(MAX_STR_CONST);
          output_ptr = output_tmp;
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
        (flags["cmt"].i() )       &&
        (*input_ptr     == COMMENT)   &&
        (*(input_ptr-1) == SPACE)     &&
        (*(input_ptr-2) != BACKSLASH) &&
        !in_sq                        &&
        !in_dq                        &&
        ccnt == 0
      ) {
        break;
        // regular character
      } else {
        char expa[] = "abefnrtv";
        char expc[] = {7,8,27,12,10,13,9,11};
        char *pos;

        if(
          flags["exp"].i() &&
          in_bs                 &&
          (pos = strchr(expa, *input_ptr))
        ) {
          long posd = pos - expa;
          output_ptr--;
          *output_ptr++ = expc[posd];
        } else {
          if(
            flags["sbs"].i() &&
            in_bs
          ) {
            output_ptr--;
          }
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
      if(
        flags["sbs"].i() &&
        in_bs
      ) {
        output_ptr--;
      }
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
      output[count++] = output_tmp;
    }
  }
  // dangling quote or escape /////////////////////
  else if(ccnt) {
    fprintf(stderr, "%s error: unmatched quote\n", Argv0);
//  throw StdException("split_string(): unmatched quote");
  }
  output[count] = NULL;
  // return number of strings found
  o.argc = count;
  o.argv = output;
  return(o);
}

/******************************************************
 * join array into one string
 *   input:   strings  // array
 *   input:   count    // size of array
 *   input:   sep      // seperator char
 *   return:  str      // joined strings
 *******************************************************************/
char* join_array(char *strings[], int count, char sep) {
  char* str = NULL;             /* Pointer to the joined strings  */
  size_t total_length = 0;      /* Total length of joined strings */
  size_t length = 0;            /* Length of a string             */
  int i = 0;                    /* Loop counter                   */
  
  if(Debug>=2) printf("Debug: Func=join_array\n");
  
  /* Find total length of joined strings */
  for(i = 0 ; i<count ; i++)
  {
    total_length += strlen(strings[i]);
    if(strings[i][strlen(strings[i])-1] != sep)
      ++total_length; /* For sep to be added */
  }
  ++total_length;     /* For joined string terminator */

  str = (char*)malloc(total_length);  /* Allocate memory for joined strings */
  str[0] = '\0';                      /* Empty string we can append to      */

  /* Append all the strings */
  for(i = 0 ; i<count ; i++)
  {
    strcat(str, strings[i]);
    length = strlen(str);

    /* Check if we need to insert sep */
    if(str[length-1] != sep)
    {
      str[length] = sep;             /* Append a sep       */
      str[length+1] = '\0';           /* followed by terminator */
    }
  }
  length = strlen(str);
  str[length-1] = '\0';           /* remove final sep */
  return str;
}


/****************************************************************
 * merge two arrays
 *   input:   argv1  // first array
 *   input:   argv2  // second array
 *   input:   at     // where in first to insert second
 *   input:   ovr    // overwrite that insertion element
 *   return:  argv3  // output array
 **************************************************************/
argv_t merge_arrays(argv_t argv1, argv_t argv2, int at, int ovr) {
  argv_t argv3;
  int i, j, k;

  if(Debug>=2) printf("Debug: Func=merge_arrays\n");

  i = 0; // argv3 out: combined array
  j = 0; // argv2 in:  array to be inserted at 'at' point
  k = 0; // argv1 in:  array to receive insertion
  argv3.argc = argv1.argc + argv2.argc;
  if(ovr) argv3.argc -= ovr;
  argv3.argv = (char **)calloc(argv3.argc+1, sizeof(char *));

  while(i < argv3.argc) {
    if((k == at) && (j < argv2.argc)) {
      argv3.argv[i++] = argv2.argv[j++];
    } else {
      if((ovr) && (k==at)) k += ovr;
      if(k >= argv1.argc) break;
      argv3.argv[i++] = argv1.argv[k++];
    }
  }
  argv3.argv[i] = NULL;

  return(argv3);
}

/****************************************************************
 * split and merge
 *   input:   argvi   // Input argv_t
 *   input:   stri    // Input string
 *   input:   at      // Where to insert
 *   return:  argvo   // Output argv_t
 **************************************************************/
argv_t split_and_merge(argv_t argvi, char *stri, int at) {
  argv_t argvs = {0, (char **)NULL};
  argv_t argvo = {0, (char **)NULL};
  int ovr = 0;

  if(stri == NULL) {
    stri = argvi.argv[at];
    ovr  = 1;
  }

  //  split_string()
  argvs = split_string(stri);

  //  merge_arrays()
  argvo = merge_arrays(argvi, argvs, at, ovr);

  return(argvo);
}
