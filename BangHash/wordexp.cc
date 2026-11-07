/*****************************************************************
 * wordexp - split a string the way a POSIX shell would (env2 -W)
 *
 * A wrapper around the POSIX wordexp() function.  It does what a shell does
 * to a command line: quoting, backslashes, $VAR and ${VAR}, ~, wildcards
 * (globbing) and $((arithmetic)).
 *
 * What it does NOT do: run commands.  $(...) and `...` are refused (the check
 * is done here, quote-aware, and WRDE_NOCMD is set as well), because a #! line
 * must never run anything while it is parsed.
 *
 * Two things are handled here because wordexp() implementations differ:
 *   - Words at the very start that begin with '-' (env2's own flags, like
 *     -Wn) are taken literally.  Some libraries (Cygwin's) build a shell
 *     "echo" command and choke on a first word like -n.
 *   - Command substitution is refused by us, not left to the library, since
 *     with WRDE_NOCMD glibc reports an error but Cygwin passes it through as
 *     literal text.
 *
 * Errors are reported by throwing StdException:
 *   - an unquoted  ( ) ; & | < >  or newline  (a shell would treat these as
 *     operators; wordexp refuses them)
 *   - an unclosed quote or other syntax error
 *   - command substitution
 *
 * Perl's shellwords() (env2's default) follows different rules from a POSIX
 * shell in two places: inside double quotes a shell only treats a backslash
 * specially before  $ ` " \  and newline, and inside single quotes a shell has
 * no escape at all (so  'a\'b'  ends at the second quote).  See the man page.
 ****************************************************************/

#include "env2lib.hh"
#include <stdlib.h>
#include <string.h>
#include <string>
#include <vector>

#if defined(__has_include)
#  if __has_include(<wordexp.h>)
#    define HAVE_WORDEXP 1
#  endif
#elif defined(__sun) || defined(__linux__) || defined(__CYGWIN__) || defined(__APPLE__)
   // compilers without __has_include (Solaris Studio) on systems known to have wordexp()
#  define HAVE_WORDEXP 1
#endif

#ifdef HAVE_WORDEXP
#include <wordexp.h>
#endif

using namespace std;

#ifdef HAVE_WORDEXP

#define SQ '\''
#define DQ '"'
#define BS '\\'

// Does the text contain command substitution, $(...) or `...`, outside single quotes?
// ($((...)) is arithmetic, which is allowed.)
static bool has_command_substitution(const string &s) {
  bool in_sq = false, in_dq = false;
  for(size_t i=0; i < s.size(); i++) {
    char c = s[i];
    if(in_sq) {                       // nothing is special inside single quotes
      if(c == SQ) in_sq = false;
      continue;
    }
    if(c == BS) { i++; continue; }    // escaped character
    if(c == SQ && !in_dq) { in_sq = true; continue; }
    if(c == DQ) { in_dq = !in_dq; continue; }
    if(c == '`') return true;
    if(c == '$' && i+1 < s.size() && s[i+1] == '(' && !(i+2 < s.size() && s[i+2] == '(')) return true;
  }
  return false;
}

#endif

argv_t split_wordexp(const char *input) {
#ifdef HAVE_WORDEXP
  const string s(input);
  vector<string> words;

  // leading words that start with '-' (env2's own flags) are taken literally
  size_t pos = 0;
  for(;;) {
    while(pos < s.size() && (s[pos] == ' ' || s[pos] == '\t')) pos++;
    if(pos >= s.size() || s[pos] != '-') break;
    size_t end = pos;
    while(end < s.size() && s[end] != ' ' && s[end] != '\t') end++;
    words.push_back(s.substr(pos, end - pos));
    pos = end;
  }
  const string rest = s.substr(pos);

  if(has_command_substitution(rest)) {
    throw StdException("wordexp: command substitution is not allowed");
  }

  if(rest.find_first_not_of(" \t") != string::npos) {
    wordexp_t p;
    int r = wordexp(rest.c_str(), &p, WRDE_NOCMD);

    switch(r) {
      case 0:
        break;
      case WRDE_BADCHAR:
        throw StdException("wordexp: unquoted ( ) ; & | < > or newline");
      case WRDE_SYNTAX:
        throw StdException("wordexp: unmatched quote or other syntax error");
      case WRDE_CMDSUB:
        throw StdException("wordexp: command substitution is not allowed");
      case WRDE_NOSPACE:
        wordfree(&p);                  // may have been partly filled in
        throw StdException("wordexp: out of memory");
      default:
        throw StdException("wordexp failed");
    }
    for(size_t i=0; i < p.we_wordc; i++) words.push_back(p.we_wordv[i]);
    wordfree(&p);
  }

  argv_t o;
  o.argc = (int)words.size();
  o.argv = (char **)calloc(words.size() + 1, sizeof(char *));
  for(size_t i=0; i < words.size(); i++) o.argv[i] = strdup(words[i].c_str());
  return o;
#else
  (void)input;
  throw StdException("-W (wordexp) is not available in this build");
#endif
}
