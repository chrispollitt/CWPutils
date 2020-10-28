#include <bits/stdc++.h>
#include <exception>

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
extern int split_string(char *input, char output[MAX_STR_CONST][MAX_STR_CONST]);

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

