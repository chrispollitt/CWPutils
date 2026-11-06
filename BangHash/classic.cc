/*****************************************************************
 * classic - env2's original argument splitter  (env2 -C, and implied by -s, -p, -x)
 *
 * This is the splitter env2 has had since 2020.  Since version 2.0 the default
 * is the shellwords splitter (shellwords.cc); this one is kept so that older
 * #! lines behave exactly as they always did, and it is still available with
 * -C (or its old name -L).
 *
 * WHAT IT DOES
 *   Splits one string - the interpreter arguments from a #! line, or an
 *   interpreter-argument line from the rc file - into separate arguments:
 *
 *     - space, tab, newline and carriage return separate arguments
 *     - 'single' and "double" quotes group text (spaces included) into one
 *       argument and are removed; a quote of one kind can hold the other kind
 *     - a backslash is KEPT in the argument (this is the biggest difference
 *       from shellwords), unless the -s flag strips it
 *     - empty arguments ("" or '') are DROPPED, unless the -p flag keeps them
 *
 *   The flags that change its behaviour (all in struct Flags):
 *     flags.sbs  (-s)  strip a backslash that comes before an ordinary character
 *     flags.exp  (-x)  turn \a \b \e \f \n \r \t \v into the characters they name
 *     flags.pre  (-p)  preserve empty arguments
 *     flags.cmt  (-c)  a '#' that starts an argument begins a comment: the rest
 *                      of the string is ignored
 *
 * HOW IT WORKS
 *   One pass over the input, character by character, with a few state flags:
 *     in_sq / in_dq   inside 'single' / "double" quotes
 *     in_bs           the previous character was a backslash
 *     ccnt            characters in the argument being built (0 = none yet)
 *   Each argument is built in its own malloc'ed buffer (output_tmp); when it is
 *   finished the pointer is stored in the output array and a new buffer starts.
 *   Both the buffers and the array are sized from the length of the input, so
 *   there is no fixed limit on how long or how many the arguments can be.
 *
 * KNOWN DIFFERENCES FROM PERL'S shellwords()  (documented in the man page, and
 * the reason shellwords became the default; t/splitcompare.pl finds them)
 *   1. with -s, a backslash before whitespace or a quote is still kept
 *   2. with -s, backslashes inside single quotes are stripped too
 *   3. empty quotes are dropped (or, with -p, make an extra empty argument
 *      when they touch other text)
 *   4. an unclosed quote is only reported if some text came after it
 *
 * ERRORS
 *   An unclosed quote or a trailing backslash (when text came after it) prints
 *   "error: unmatched quote" on stderr and returns what it has so far.  It does
 *   not throw, unlike the other two splitters.
 *
 * This function used to be called split_string() and lived in array_utils.cc.
 ****************************************************************/

#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include "env2lib.hh"

using namespace std;

// Characters this parser cares about
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
 * split_classic - split a string into an array of arguments
 *   input:   flags   // sbs, exp, pre and cmt change the rules (see above)
 *   input:   input   // string to split (not modified)
 *   return:  o       // argc, and a NULL-terminated argv of malloc'ed strings
 **************************************************************/
argv_t split_classic(const Flags &flags, char *input) {
  argv_t o;
  char **output;      // the array of arguments being built
  char *output_tmp;   // the argument being built (start of its buffer)
  char *input_ptr;    // where we are in the input string
  char *output_ptr;   // where the next character goes in output_tmp
  int count=0;        // number of arguments finished so far
  int ccnt=0;         // characters in the argument being built; 0 = none yet
  int in_sq=0;        // inside 'single quotes'
  int in_dq=0;        // inside "double quotes"
  int in_bs=0;        // the previous character was a backslash
  // No argument can be longer than the input, and there can't be more arguments
  //   than input characters + 1, so size the buffers from the input.
  size_t cap = strlen(input) + 2;

  if(Debug>=2) printf("Debug: Func=split_classic\n");

  /****************************************
   * inline helper function to reduce duplicated code for quote parsing.
   *   sq=1: the character is a single quote;  sq=0: it is a double quote.
   *   in_q1 is the state of the kind of quote we just saw, in_q2 the other kind.
   ****************************************/
  auto found_q = [&](int sq) {
    // set in_q1 and in_q2 refs
    int *in_q1 =  sq ? &in_sq : &in_dq;
    int *in_q2 = !sq ? &in_sq : &in_dq;

    // A quote of this kind opens or closes a quoted string, unless we are inside
    // the other kind of quotes or it is escaped by a backslash.
    if(!*in_q2 && !in_bs) {
      // The quote is closing a string with nothing in it ("" or ''): with -p,
      //   that is an empty argument, so finish it now.  (Without -p it is dropped.)
      if(*in_q1 && ccnt==0 && flags.pre ) {
        *output_ptr = ENDOFSTR;
        output[count++] = output_tmp;
        output_tmp = (char *)malloc(cap);
        output_ptr = output_tmp;
      }
      // flip flag
      *in_q1=1-*in_q1;
    } else {
      // The quote is just a character (inside the other kind of quotes, or
      //   backslash-escaped): add it to the argument.
      *output_ptr++ = *input_ptr;
      ccnt++;
    }
    // clear in_bs
    in_bs=0;
  };

  /****************************************
   * body of split_classic()
   ****************************************/
  output = (char **)calloc(cap + 1, sizeof(char *));

  // init in and out pointers
  input_ptr = input;
  output_tmp = (char *)malloc(cap);
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
      // not in single, double, or backslash: it separates arguments
      if(!in_sq && !in_dq && !in_bs) {
        // and we have a string, term string and move to next argv
        if(ccnt) {
          *output_ptr = ENDOFSTR;
          output[count++] = output_tmp;
          output_tmp = (char *)malloc(cap);
          output_ptr = output_tmp;
          ccnt=0;
        }
        // discard unquoted whitespace
      }
      // inside quotes, or escaped by a backslash: it is part of the argument
      else {
        *output_ptr++ = *input_ptr;
        ccnt++;
      }
      in_bs=0;
    }
    // not whitespace, backslash or quote (a regular character) ///////////
    else if (
      *input_ptr != SPACE       &&
      *input_ptr != TAB         &&
      *input_ptr != NEWLINE     &&
      *input_ptr != RETURN      &&
      *input_ptr != BACKSLASH   &&
      *input_ptr != DOUBLEQUOTE &&
      *input_ptr != SINGLEQUOTE
    ) {
      // comment (-c): a '#' that starts an argument, is not escaped, and is
      //   outside quotes ends the input.  "Starts an argument" means: preceded
      //   by a space and nothing in the argument yet.  (The two characters
      //   before the '#' are only looked at if they are inside the string.)
      if(
        (flags.cmt )       &&
        (*input_ptr     == COMMENT)   &&
        (input_ptr > input)                           &&
        (*(input_ptr-1) == SPACE)                     &&
        (input_ptr-1 == input || *(input_ptr-2) != BACKSLASH) &&
        !in_sq                        &&
        !in_dq                        &&
        ccnt == 0
      ) {
        break;
        // regular character
      } else {
        char expa[] = "abefnrtv";                 // the letters after a backslash (-x)...
        char expc[] = {7,8,27,12,10,13,9,11};     // ...and the characters they stand for
        char *pos;

        // -x: a backslash followed by one of those letters becomes the character.
        //   The backslash is already in the output, so overwrite it.
        if(
          flags.exp &&
          in_bs                 &&
          (pos = strchr(expa, *input_ptr))
        ) {
          long posd = pos - expa;
          output_ptr--;
          *output_ptr++ = expc[posd];
        } else {
          // -s: drop the backslash that is already in the output
          if(
            flags.sbs &&
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
    // A backslash is copied to the output like any character (so it is kept),
    //   and the NEXT character is treated as escaped.  Two backslashes in a row
    //   are an escaped backslash.  With -s the earlier one is dropped.
    else if (*input_ptr==BACKSLASH) {
      if(
        flags.sbs &&
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
  // The input has ended.  If we are not inside quotes or after a backslash, the
  //   argument being built (if any) is complete.
  if(!in_sq && !in_dq && !in_bs) {
    // and we have a string, term string and increase count
    if(ccnt) {
      *output_ptr = ENDOFSTR;
      output[count++] = output_tmp;
    }
  }
  // dangling quote or escape /////////////////////
  // Only reported if some text followed it (ccnt); a lone quote is ignored.
  else if(ccnt) {
    fprintf(stderr, "%s error: unmatched quote\n", Argv0);
//  throw StdException("split_classic(): unmatched quote");
  }
  output[count] = NULL;
  // return number of strings found
  o.argc = count;
  o.argv = output;
  return(o);
}
