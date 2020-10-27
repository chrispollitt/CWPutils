#define MAX_STR_CONST 255

// Declare Globals ////////////////

// System vars and functions
void perror(const char *s);
int errno;


// Local functions
extern void usage(int ret);
extern int parse_flags(char *flags_str) ;

