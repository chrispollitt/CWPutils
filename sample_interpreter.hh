
// Declare Globals ////////////////

// System vars and functions
void perror(const char *s);
int errno;

// Local functions
extern void usage(int ret);
extern argv_t load_script(char *scriptname);
extern void run_bash(argv_t ia, argv_t sa);

#if MAIN_VARIATION == 3

extern hash_t my_parse_flags(char *flags_str);

#endif
