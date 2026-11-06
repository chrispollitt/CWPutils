// t/splitcheck.cc - a test harness for split_string() / split_shellwords()
// (see t/splitcompare.pl)
//
// splitcheck [flags]  -- read lines on stdin, split each with env2's splitter
// flags: S = split like Perl's shellwords() (otherwise env2's original split_string())
//        s = strip backslashes, p = preserve empty args, x = expand \n etc.  (split_string only)
//        c = comments
// output per line:  <U|M>\x1ftoken1\x1ftoken2...
//   M = the splitter complained (unmatched quote), U = it did not

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
      if(*p == 'S') flags.shellwords = true;
      if(*p == 's') flags.sbs = true;
      if(*p == 'p') flags.pre = true;
      if(*p == 'x') flags.exp = true;
      if(*p == 'c') flags.cmt = true;
    }
  }
  // split_string() reports problems on stderr: capture it to see whether it complained
  FILE *tf = tmpfile();
  fflush(stderr);
  dup2(fileno(tf), 2);

  char *line = NULL; size_t sz = 0; ssize_t n;
  while((n = getline(&line, &sz, stdin)) != -1) {
    if(n > 0 && line[n-1] == '\n') line[--n] = '\0';
    argv_t r = {0, NULL};
    bool complained = false;
    try {
      r = split_args(flags, line);
    } catch (StdException &) {
      complained = true;          // split_shellwords() throws
    }
    fflush(stderr);
    off_t err = lseek(2, 0, SEEK_CUR);
    if(err > 0) {
      complained = true;
      if(ftruncate(2, 0) != 0) perror("ftruncate");
      lseek(2, 0, SEEK_SET);
    }
    putchar(complained ? 'M' : 'U');
    for(int i = 0; i < r.argc; i++) { putchar('\x1f'); fputs(r.argv[i], stdout); }
    putchar('\n');
  }
  return 0;
}
