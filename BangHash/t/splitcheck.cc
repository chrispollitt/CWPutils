// t/splitcheck.cc - a test harness for split_string() (see t/splitcompare.pl)
//
// splitcheck [flags]  -- read lines on stdin, split each with env2's split_string()
// flags: s = strip backslashes, p = preserve empty args, x = expand \n etc.
// output per line:  <U|M>\x1ftoken1\x1ftoken2...   (M = split_string complained: unmatched quote)

#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L   // for fileno() with a strict -std=
#endif
#include "env2lib.hh"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <unistd.h>

char *Argv0 = (char *)"splitcheck";
int   Debug = 0;

int main(int argc, char **argv) {
  Flags flags;
  if(argc > 1) {
    for(const char *p = argv[1]; *p; p++) {
      if(*p == 's') flags.sbs = true;
      if(*p == 'p') flags.pre = true;
      if(*p == 'x') flags.exp = true;
    }
  }
  // capture stderr so we can see whether split_string complained
  FILE *tf = tmpfile();
  fflush(stderr);
  dup2(fileno(tf), 2);

  char *line = NULL; size_t sz = 0; ssize_t n;
  while((n = getline(&line, &sz, stdin)) != -1) {
    if(n > 0 && line[n-1] == '\n') line[--n] = '\0';
    argv_t r = split_string(flags, line);
    fflush(stderr);
    off_t err = lseek(2, 0, SEEK_CUR);
    putchar(err > 0 ? 'M' : 'U');
    if(err > 0) { ftruncate(2, 0); lseek(2, 0, SEEK_SET); }
    for(int i = 0; i < r.argc; i++) { putchar('\x1f'); fputs(r.argv[i], stdout); }
    putchar('\n');
  }
  return 0;
}
