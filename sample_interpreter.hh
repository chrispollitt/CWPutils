
// Declare Globals ////////////////

// System vars and functions
void perror(const char *s);
int errno;

// Local functions
extern void usage(int ret);

#if MAIN_VARIATION == 3

#include <bits/stdc++.h>
typedef std::map<std::string, std::string> hash_t;
extern hash_t my_parse_flags(char *flags_str);

// Global vars
extern char *Argv0;                           // Name of program
extern int   Debug;                           // Debug flag

#endif
