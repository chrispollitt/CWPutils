#include <bits/stdc++.h>
#include <exception>

#define MAX_STR_CONST 255
#define MAX_LINE_LEN 1024

typedef std::map<std::string, std::string> hash_t;
typedef struct argv {
  int argc;
  char **argv;
} argv_t;

// Declare Globals ////////////////

// System vars and functions
void perror(const char *s);
int errno;

// env2 functions
extern argv_t merge_arrays(argv_t argv1, argv_t argv2, int at, int ovr);
extern argv_t split_and_merge(argv_t argvi, char *stri, int at);
extern argv_t split_string(char *input);
extern int dumpargs(int argc, char **argv);
extern int parse_flags(char *flags_str);
extern void env2 (int *argcp, char ***argvp, int nstart);
extern void vars2();

// Global vars
extern char *Argv0;                           // Name of program
extern int   Debug;                           // Debug flag
extern hash_t add_args;                       // Set in vars2()
extern hash_t flags;                          // Place for flags

// std::exception with a what()
class StdException: public std::exception {
public:
  StdException (const char *m) noexcept {
    message = m;
  }
  virtual const char* what() const throw() {
    return message;
  }

private:
  const char *message;
};
