PROG    = env2
LIBOBJ0 = vars5.o
LIBOBJ1 = libenv2.o
LIBOBJ2 = libdumpargs.o
LIBOBJ3 = parse_flags.o
PREFIX  = /usr/local
SAMPLE  = sample_interpreter

CXX      = g++
CXXFLAGS = -Wall -g -std=gnu++17

all: build

build: $(PROG) $(PROG).man

$(PROG): $(PROG).o $(LIBOBJ0) $(LIBOBJ1) $(LIBOBJ2) $(LIBOBJ3)
	$(CXX) -o $@ $^

$(LIBOBJ1): $(PROG)lib.cc
	$(CXX) $(CXXFLAGS) -o $@ -c $^

$(LIBOBJ2): dumpargs.cc
	$(CXX) $(CXXFLAGS) -o $@ -DDUMPARGS_LIB=1 -c $^

$(PROG).man: $(PROG).pod
	pod2man $(PROG).pod $@

$(PROG).pod: $(PROG).pod-header $(PROG).pod-middle $(PROG).pod-footer
	cat $^ > $(PROG).pod

$(PROG).pod-middle: $(PROG)
	./$< -h > $(PROG).pod-middle || true

sample: $(SAMPLE)

$(SAMPLE).o: $(SAMPLE).cc
	$(CXX) $(CXXFLAGS) -DMAIN_VARIATION=3 -o $@ -c $<

$(SAMPLE): $(SAMPLE).o $(LIBOBJ0) $(LIBOBJ1) $(LIBOBJ2) $(LIBOBJ3)
	$(CXX) -o $@ $^

clean:
	-rm -f *.o $(PROG) $(PROG).pod $(PROG).man $(SAMPLE) *.exe *~
	-rm -f t/out?

install: build
	cp $(PROG) $(PREFIX)/bin
	cp $(PROG).man $(PREFIX)/share/man/man1/$(PROG).1

uninstall:
	rm -f $(PREFIX)/bin/$(PROG)
	rm -f $(PREFIX)/share/man/man1/$(PROG).1

test check: build
	./test_env2.sh ./$(PROG)

# Generic Rules ##############
%.o: %.cc
	$(CXX) $(CXXFLAGS) -c $<

%: %.o
	$(CXX) -o $@ $< 

# Special Rules ##############
.PHONY: all build clean install uninstall test check

.PRECIOUS: %.o %.c

.SUFFIXES:
