/*****************************************************************
 * switches - a small table-driven parser for #! line switches
 *
 * Used by env2 for its own flags, and available to custom interpreters
 * built on the env2 library.  It is modelled on how Perl handles switches
 * on a #! line:
 *   - single-letter switches can be clustered:      -abc
 *   - several clusters can share one string:        "-ab -c"
 *     (what many kernels hand over as a single argument)
 *   - parsing stops at the first word that is not a switch, which is
 *     left in SwitchResult::rest for the caller
 *   - the same function works on text from the command line or from the
 *     script's own #! line (see read_hashbang()), so it does not matter
 *     how the kernel split things up
 *
 * It has no side effects: no globals, no exit(), no output.  Problems are
 * reported by throwing StdException.
 ****************************************************************/

#include "env2lib.hh"
#include <string.h>

using namespace std;

static const SwitchSpec *find_short(const vector<SwitchSpec> &spec, char c) {
  for(size_t i=0; i < spec.size(); i++) {
    if(spec[i].letter == c) return &spec[i];
  }
  return NULL;
}

static const SwitchSpec *find_long(const vector<SwitchSpec> &spec, const string &name) {
  for(size_t i=0; i < spec.size(); i++) {
    if(spec[i].longname && name == spec[i].longname) return &spec[i];
  }
  return NULL;
}

/****************************************************************
 * parse_switches - parse switches from the front of text
 *   input:   text   // e.g. "-sn perl -w"
 *   input:   spec   // table of known switches
 *   return:  result // switches seen (in order), clusters consumed,
 *                   //   and the remaining text ("perl -w")
 *   throws:  StdException on an unrecognized switch
 **************************************************************/
SwitchResult parse_switches(const char *text, const vector<SwitchSpec> &spec) {
  SwitchResult r;
  const char *p = text;

  while(*p) {
    // blank: start of a new cluster
    if(*p == ' ') {
      p++;
      continue;
    }
    // first word that is not a switch: stop
    if(*p != '-') break;

    // one cluster, up to the next blank
    const char *end = p;
    while(*end && *end != ' ') end++;
    string word(p, end - p);

    if(word.compare(0, 2, "--") == 0 && word.size() > 2) {
      // long name: --help
      const SwitchSpec *s = find_long(spec, word.substr(2));
      if(!s) throw StdException("unrecognized flag ", word.c_str());
      r.given.push_back({s->letter, false, string()});
    } else {
      // clustered short switches: -abc (a lone "-" is an empty cluster)
      for(size_t j=1; j < word.size(); j++) {
        char c = word[j];
        const SwitchSpec *s = find_short(spec, c);
        if(!s) throw StdException("unrecognized flag ", string(1, c).c_str());
        if(s->optarg && j+1 < word.size() && (word[j+1] == '=' || word[j+1] == ':')) {
          // attached arg runs to the end of the word, and ends the cluster
          r.given.push_back({c, true, word.substr(j+2)});
          break;
        }
        r.given.push_back({c, false, string()});
      }
    }
    r.clusters++;
    p = end;
  }

  r.rest = p;
  return r;
}
