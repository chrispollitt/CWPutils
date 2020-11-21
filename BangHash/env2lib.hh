#pragma once

#include "config.hh"
#include <string>
#include <map>
#include <exception>

#define MAX_STR_CONST 255
#define MAX_LINE_LEN 1024

class flag_t {
  public:
    // c'tors
    flag_t()              { val=std::to_string(0); };
    flag_t(int v)         { val=std::to_string(v); };
    flag_t(char *v)       { val=std::string(v);    };
    flag_t(std::string v) { val=v;                 };
    // get
    int         l() { return val.length();  }
    int         i() { return std::stoi(val);};
    const char *c() { return val.c_str();   };
    std::string s() { return val;           };
  private:
    // attrs
    std::string val;
};
typedef std::map<std::string, flag_t> hash_t;
typedef struct {
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
extern void init_flags(int found=0, int nstart=0);
extern char* join_array(char *strings[], int count, char sep=' ');
extern argv_t merge_arrays(argv_t argv1, argv_t argv2, int at, int ovr);
extern argv_t read_hashbang(argv_t i);
extern argv_t split_and_merge(argv_t argvi, char *stri=NULL, int at=1);
extern argv_t split_string(char *input);
extern hash_t vars2();

// Global vars
extern char  *Argv0;                           // Name of program
extern int    Debug;                           // Debug flag
extern hash_t flags;                           // Place for flags

// std::exception with a what()
class StdException: public std::exception {
public:
  // constructors
  StdException (const char *m) noexcept {
    message = std::string(m);
  }
  StdException (const char *m, const char *a) noexcept {
    message = std::string(m) + std::string(a);
  }
  StdException (const std::string m) noexcept {
    message = m;
  }
  // methods
  virtual const char* what() const throw() {
    return message.c_str();
  }

private:
  std::string message;
};

