#include <bits/stdc++.h>

#define MAX_STR_CONST 255

typedef std::map<std::string, std::string> hash_t;

// Declare Globals ////////////////

// System vars and functions
void perror(const char *s);
int errno;

// env2 functions
extern void env2 (int *argcp, char ***argvp); // The main funtion
extern void vars2();                          // set env vars
extern int dumpargs(int argc, char **argv);   // Dump (display) arguments
extern int parse_input(char *input, char output[MAX_STR_CONST][MAX_STR_CONST]);

// Global vars
extern char *Argv0;                           // Name of program
extern int   Debug;                           // Debug flag
extern hash_t add_args;                       // Set in vars2()
extern hash_t flags;                          // Place for flags
