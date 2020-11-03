
// Declare Globals ////////////////

// System vars and functions
void perror(const char *s);
int errno;

// Local functions
extern void usage(int ret);
extern int my_parse_flags(char *flags_str);

#if MAIN_VARIATION == 3

#include <bits/stdc++.h>
typedef std::map<std::string, std::string> hash_t;

// Global vars
extern char *Argv0;                           // Name of program
extern int   Debug;                           // Debug flag

#endif
