/*****************************************************************
 * array helpers: split_args (picks the splitter), join_array, merge_arrays,
 * split_and_merge.  The splitters themselves are in classic.cc, shellwords.cc
 * and wordexp.cc.
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

/****************************************************************
 * split_args - split a string into args using the splitter the flags ask for
 *   shellwords (default): split_shellwords() (Perl-compatible; honours -c and -E)
 *   classic (-C, or s, p, x): split_classic() (env2's original splitter, classic.cc)
 *   wordexp (-W): split_wordexp() (a POSIX shell's rules; no command substitution)
 **************************************************************/
argv_t split_args(const Flags &flags, char *input) {
  switch(flags.splitter) {
    case SPLIT_CLASSIC:  return split_classic(flags, input);
    case SPLIT_WORDEXP:  return split_wordexp(input);
    default:             return split_shellwords(input, flags.cmt, flags.expand);
  }
}

/******************************************************
 * join array into one string
 *   input:   strings  // array
 *   input:   count    // size of array
 *   input:   sep      // separator char
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
argv_t split_and_merge(const Flags &flags, argv_t argvi, char *stri, int at) {
  argv_t argvs = {0, (char **)NULL};
  argv_t argvo = {0, (char **)NULL};
  int ovr = 0;

  if(stri == NULL) {
    stri = argvi.argv[at];
    ovr  = 1;
  }

  //  split_args()
  argvs = split_args(flags, stri);

  //  merge_arrays()
  argvo = merge_arrays(argvi, argvs, at, ovr);

  return(argvo);
}
