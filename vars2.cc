#include <libgen.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>
#include <cstdio>
#include <cstring>
#include <iostream>
#include <iterator>
#include <regex>
#include <string>
#include "env2lib.hh"

using namespace std;

/*************************
 * parse config file and fill add_args[]
 ************************/
hash_t vars2() {
  char *myname = basename(Argv0);
  char *home = getenv("HOME");
  char conf_name[MAX_STR_CONST];
  struct stat conf_stat;
  FILE *conf_fh;
  char *conf_line = NULL;
  size_t size = 0;
  int read;
  size_t i, j;
  hash_t add_args;
  regex cfg_re0( R"(^\s*(\w+)\s*([;:=+!])\s*(.*)$)" );  // find "a=b" or "a!" OR "a:b" or "a;b"
  regex cfg_re1( R"(\s+$)" );                           // trailing whitespace
  regex cfg_re2( R"(\\([^\\]))" );                      // remove extra backslashes
  regex cfg_re3( R"(^[']([^']*)[']$)" );                // remove enclosing ''
  regex cfg_re4( R"(^["]([^"]*)["]$)" );                // remove enclosing ""
  smatch cfg_matches;

  snprintf(conf_name, sizeof(conf_name)-1,"%s/.%s%s",home,myname,"rc");
  if(stat(conf_name, &conf_stat) != 0) {
    if(Debug) fprintf(stderr, "Debug: conf file not found: %s\n", conf_name);
    return add_args;
  }
  conf_fh=fopen(conf_name, "r");
  if(conf_fh == NULL) {
    if(Debug) fprintf(stderr, "Debug: conf file not readable: %s\n", conf_name);
    return add_args;
  }
  while((read =  getline(&conf_line, &size, conf_fh)) != -1) {
    string conf_line_s = conf_line;
    conf_line_s = regex_replace(conf_line_s, cfg_re1, "");  // remove trailing whitespace
    if(regex_search(conf_line_s, cfg_matches, cfg_re0)) {   // look for a=b or a:b
      string var  = cfg_matches[1].str();
      string sep  = cfg_matches[2].str();
      string val  = cfg_matches[3].str();
      char *oval;

      // Set Environment Variable
      if(sep == "=" || sep == "+") {
        if        (regex_search(val, cfg_re3)) {            // remove enclosing ''
          val =   regex_replace(val, cfg_re3, "$1");
        } else if (regex_search(val, cfg_re4)) {            // remove enclosing ""
          val =   regex_replace(val, cfg_re4, "$1");
        }
        if(flags["exp"].length()) {
          char expa[] = "abefnrtv";
          char expc[] = {7,8,27,12,10,13,9,11};
          for(i=0; i<strlen(expa);i++) {
            string esc = string("\\") + string(1,(char)expa[i]);
            while( (j=val.find(esc)) != string::npos ) {
              val.replace(j,esc.length(),string(1,(char)expc[i]));
            }
          }
        }
        if(flags["sbs"].length()) {
          while( regex_search(val, cfg_re2) ) {
            val = regex_replace(val, cfg_re2, "$1");
          }
          string esc = string("\\\\");
          while( (j=val.find(esc)) != string::npos ) {
            val.replace(j,1,"");
          }
        }
        if(sep == "+") {
          oval = getenv(var.c_str());
          if (oval) val += string(oval);
        }
        if(Debug) fprintf(stderr, "Debug: setenv: %s=%s\n", var.c_str(), val.c_str());
        setenv(var.c_str(),val.c_str(),1);
        // Unset Environment Variable
      } else if(sep == "!") {
        if(Debug) fprintf(stderr, "Debug: unsetenv: %s\n", var.c_str());
        unsetenv(var.c_str());
        // Extra interpeter args
      } else if(sep == ":") {
        if(Debug) fprintf(stderr, "Debug: add_args: %s=%s\n", var.c_str(), val.c_str());
        add_args[var] = val;
        // Only interpeter args
      } else if(sep == ";") {
        if(Debug) fprintf(stderr, "Debug: set_args: %s=%s\n", var.c_str(), val.c_str());
        add_args[var] = "~~"+val;
        // Impossible!
      } else {
        if(Debug) fprintf(stderr, "Debug: sep illegal: %s\n", sep.c_str());
      }
    }
  }
  free(conf_line);
  fclose(conf_fh);
  return(add_args);
}
