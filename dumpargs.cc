#include <stdio.h>
#include <unistd.h>
#include <stdlib.h>
#include <malloc.h>
#include "env2lib.hh"

char *getaline(FILE *fh) {
    char *line = (char *)malloc(MAX_LINE_LEN), *linep = line;
    size_t lenmax = MAX_LINE_LEN, len = lenmax;
    int c;

    if(line == NULL)
        return NULL;

    for(;;) {
        c = fgetc(fh);
        if(c == EOF) {
            *line++ = '\4';
            break;
        }

        if(--len == 0) {
            len = lenmax;
            char *linen = (char *)realloc(linep, lenmax *= 2);

            if(linen == NULL) {
                free(linep);
                return NULL;
            }
            line = linen + (line - linep);
            linep = linen;
        }

        if( c == '\n') {
            *line++ = '\0';
            break;
        }
        else {
            *line++ = c; 
        }
    }
    *line = '\0';
    return linep;
}

int dumpargs(int argc, char **argv) {
  char *line;
  char *script = NULL;
  FILE *fh     = NULL;
  int i=0;
  int j=0;

  printf("------arguments-----\n");
  for(i=0;i<argc;i++) {
    printf("arg%d='%s'",i,argv[i]);
    if(i>0 && script == NULL && argv[i][0] != '-') {
      script = argv[i];
      printf(" <-- script\n");
    }
    else if(i == 0) {
      printf(" <-- interpreter\n");
    }
    else {
      printf("\n");
    }
  }
  i--;
  if( script != NULL) {
    if(access( script, F_OK ) != -1) {
      fh = fopen(script,"r");
    }
    else {
      fprintf(stderr, "warning: script file not found: '%s'\n", script);
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
    line = getaline(fh);
    while(line[0] != '\4') {
      printf("line%d='%s'\n",j,line);
      free(line);
      j++;
      line = getaline(fh);
    }
    fclose(fh);
  }
  printf("------output-----\n");
  
  return(0);
}

#ifdef MAKE_EXE

int main(int argc, char **argv) {
  dumpargs(argc, argv);
  return(0);
}

#endif
