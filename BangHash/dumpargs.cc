#include <stdio.h>
#include <unistd.h>
#include <stdlib.h>
#include <string.h>
#include "env2lib.hh"

int dumpargs(int argc, char **argv, int scr_loc) {
  char *line   = NULL;
  char *script = NULL;
  FILE *fh     = NULL;
  int i        = 0;
  size_t size  = 0;
  int read     = 0;

  printf("------arguments-----\n");
  for(i=0; i<argc; i++) {
    printf("arg%d='%s'",i,argv[i]);
    if(
      (
        (scr_loc)           && 
        (scr_loc = i)
      )       ||
      (
        (strlen(argv[i]))   &&
        (i>0)               &&
        (script == NULL)    &&
        (argv[i][0] != '-') &&
        (access( argv[i], F_OK ) != -1)
      )
    ) {
      script = argv[i];
      printf("\t<-- script\n");
    }
    else if(i == 0) {
      printf("\t<-- interpreter\n");
    }
    else {
      printf("\n");
    }
  }
  if( script != NULL) {
    if((fh = fopen(script,"r")) == NULL) {
      fprintf(stderr, "warning: script file not readable: '%s'\n", script);
      fh = NULL;
      //exit(1);
    }
  }
  else {
#ifdef USE_STDIN_IF_NO_SCRIPT
    fprintf(stderr, "warning: script file not specified, using stdin\n");
    fh = stdin;
#else
    fprintf(stderr, "warning: script file not specified\n");
    fh = NULL;
#endif
  }
  if(fh != NULL) {
    printf("------input-----\n");
    i = 0;
    while((read =  getline(&line, &size, fh)) != -1) {
      line[strlen(line)-1]='\0';
      printf("line%d='%s'\n", i++, line);
    }
    fclose(fh);
  }
#ifndef MAKE_EXE
  printf("------output-----\n");
#endif

  return(0);
}

#ifdef MAKE_EXE

int main(int argc, char **argv) {
  dumpargs(argc, argv);
  return(0);
}

#endif
