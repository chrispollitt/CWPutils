/*****************************************************************
 * shellwords - a port of Perl's Text::ParseWords::shellwords()
 *
 * Splits a string into words the way a shell does, as Perl does it:
 *
 *   - whitespace (space, tab, newline, CR, FF, VT) separates words;
 *     leading and trailing whitespace is ignored
 *   - "double quoted" and 'single quoted' text is part of a word; the
 *     quotes are removed, and quoted and unquoted pieces next to each
 *     other join into one word:   ab"c d"'e'  ->  abc de
 *   - outside quotes and inside double quotes a backslash makes the next
 *     character literal and is removed:   a\ b  ->  "a b"
 *   - inside single quotes everything is literal, backslashes included,
 *     except that a backslash still protects a quote from ending the
 *     string:   'a\'b'  ->  a\'b
 *   - an empty quoted string is an empty word:   ""  ->  ""
 *   - an unclosed quote, or a backslash with nothing after it, is an
 *     error (Perl returns an empty list; this throws StdException)
 *
 * Perl implements this with one big regex (parse_line); this is the same
 * thing as a plain state machine.  t/splitcompare.pl checks that the two
 * agree on every short string, and `make test` runs that check.
 *
 * Optional extensions (Perl's shellwords() has neither):
 *   comments=true  stops at a '#' that starts a word (env2's -c)
 *   expand=true    replaces ${NAME} with the environment variable's value (env2's -E),
 *                  outside quotes and inside double quotes, like GNU env -S.  The value is
 *                  not split again.  An unset variable is empty and a whole unquoted word made
 *                  of only unset variables is dropped; a variable that is set but empty gives an
 *                  empty word (as in GNU env -S).  Any other '$' is an error.
 ****************************************************************/

#include "env2lib.hh"
#include <ctype.h>
#include <stdlib.h>
#include <string.h>
#include <string>
#include <vector>

using namespace std;

// Perl's \s on a byte string
static bool is_space(char c) {
  return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\f' || c == '\v';
}

static bool is_quote(char c) {
  return c == '"' || c == '\'';
}

// is this a valid environment variable name?
static bool valid_name(const string &s) {
  if(s.empty() || !(isalpha((unsigned char)s[0]) || s[0] == '_')) return false;
  for(size_t i=1; i < s.size(); i++) {
    if(!(isalnum((unsigned char)s[i]) || s[i] == '_')) return false;
  }
  return true;
}

// backslash + any char  ->  that char  (so \$ is a literal dollar)
// expand=true: ${NAME} -> the value of that environment variable (empty if unset);
//   any other '$' is an error, as in GNU env -S.  The value is spliced in as plain
//   text, so it is never split again or expanded again.
// *defined (if given) is set when the text produced a character or named a variable
//   that is SET (even if its value is empty).  Only a piece made of nothing but unset
//   variables is not "defined", and an unquoted word like that disappears.  This is
//   how GNU env -S behaves: ${SET_BUT_EMPTY} is an empty argument, ${UNSET} is nothing.
static string unescape(const string &s, bool expand, bool *defined = NULL) {
  string out;
  if(defined) *defined = false;
  for(size_t i=0; i < s.size(); i++) {
    if(s[i] == '\\' && i+1 < s.size()) {
      out += s[++i];
      if(defined) *defined = true;
      continue;
    }
    if(expand && s[i] == '$') {
      size_t close = (i+1 < s.size() && s[i+1] == '{') ? s.find('}', i+2) : string::npos;
      string name = (close == string::npos) ? string() : s.substr(i+2, close-i-2);
      if(!valid_name(name)) throw StdException("only ${NAME} expansion is supported");
      const char *value = getenv(name.c_str());
      if(value) {
        out += value;
        if(defined) *defined = true;
      }
      i = close;
      continue;
    }
    out += s[i];
    if(defined) *defined = true;
  }
  return out;
}

/****************************************************************
 * split_shellwords - split a string like Perl's shellwords()
 *   input:   input     // string to split
 *   input:   comments  // true: a '#' that starts a word ends the input
 *   return:  o         // argv_t (NULL terminated, strdup'd words)
 *   throws:  StdException on an unclosed quote or a trailing backslash
 **************************************************************/
argv_t split_shellwords(const char *input, bool comments, bool expand) {
  const string s(input);
  const size_t n = s.size();
  vector<string> words;
  string word;
  bool have_word = false;         // Perl's "$word is defined"
  size_t pos = 0;

  while(pos < n && is_space(s[pos])) pos++;   // leading whitespace

  while(pos < n) {
    char c = s[pos];

    // a '#' at the start of a word starts a comment (extension)
    if(comments && !have_word && c == '#') break;

    if(is_quote(c)) {
      // quoted string: up to the first quote of the same kind that is not
      // protected by a backslash
      size_t i = pos + 1;
      for(;;) {
        if(i >= n) throw StdException("unmatched quote");
        if(s[i] == '\\') {
          if(i+1 >= n) throw StdException("unmatched quote");
          i += 2;
          continue;
        }
        if(s[i] == c) break;
        i++;
      }
      string quoted = s.substr(pos + 1, i - pos - 1);
      // double quotes: backslashes (and ${NAME} if expanding); single quotes: all literal
      word += (c == '"') ? unescape(quoted, expand) : quoted;
      have_word = true;
      pos = i + 1;
      if(pos >= n) {            // end of input right after the closing quote
        words.push_back(word);
        have_word = false;
      }
      continue;
    }

    // unquoted text: up to whitespace, a quote, or the end
    size_t i = pos;
    for(;;) {
      if(i >= n || is_space(s[i])) break;
      if(i > pos && is_quote(s[i])) break;      // a quote ends this piece (not at its start)
      if(s[i] == '\\') {
        if(i+1 >= n) throw StdException("unmatched quote or trailing backslash");
        i += 2;
        continue;
      }
      i++;
    }
    bool defined;
    word += unescape(s.substr(pos, i - pos), expand, &defined);
    // An unquoted piece that is only ${UNSET} adds nothing; if that is the whole
    // word, the word disappears.  A quoted piece always counts.
    if(defined) have_word = true;
    pos = i;

    if(pos >= n) {              // end of input: the word is complete
      if(have_word) words.push_back(word);
      have_word = false;
    } else if(is_space(s[pos])) {   // whitespace: the word is complete
      while(pos < n && is_space(s[pos])) pos++;
      if(have_word) words.push_back(word);
      word.clear();
      have_word = false;
    }
    // else: a quote follows; the word continues
  }
  // stopped at a comment with a word in progress (can't happen: comments only
  // start a word), or fell off the end: nothing left to push

  argv_t o;
  o.argc = (int)words.size();
  o.argv = (char **)calloc(words.size() + 1, sizeof(char *));
  for(size_t k=0; k < words.size(); k++) o.argv[k] = strdup(words[k].c_str());
  return o;
}
