#pragma once

#include "config.hh"
#include <string>
#include <map>
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
extern void perror(const char *s);
extern int errno;

// env2 functions
extern int dumpargs(int argc, char **argv);
extern argv_t env2(argv_t o);
extern char *getaline(FILE *fh);
extern char* join_array(char *strings[], int count, char sep=' ');
extern argv_t merge_arrays(argv_t argv1, argv_t argv2, int at, int ovr);
extern argv_t read_hashbang(argv_t i);
extern argv_t split_and_merge(argv_t argvi, char *stri=NULL, int at=1);
extern argv_t split_string(char *input);
extern hash_t vars2();

// Global vars
extern char  *Argv0;                           // Name of program
extern int    Debug;                           // Debug flag
extern hash_t flags;                           // Place for flags  xxx

// std::exception with a what()
class StdException: public std::exception {
public:
  // constructors
  StdException (const char *m) noexcept {
    std::string msg = std::string(m);
    message = msg.c_str();
  }
  StdException (const char *m, const char *a) noexcept {
    std::string msg = std::string(m) + std::string(a);
    message = msg.c_str();
  }
  StdException (const std::string m) noexcept {
    message = m.c_str();
  }
  // methods
  virtual const char* what() const throw() {
    return message;
  }

private:
  const char *message;
};
