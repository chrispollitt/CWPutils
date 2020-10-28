# Variables ###########################

# Site cusomizable variables (change as needed)
PREFIX   = /usr/local
CXX      = g++
CXXFLAGS = -Wall -g -std=gnu++17

# Internal variables (change at your peril)
PROG1   = env2
PROG2   = dumpargs
SAMPLE  = sample_interpreter
LIBOBJ0 = $(PROG1).o
LIBOBJ1 = $(PROG2).o
LIBOBJ2 = merge_arrays.o
LIBOBJ3 = parse_flags.o
LIBOBJ4 = vars2.o
LIBOBJS = $(LIBOBJ1) $(LIBOBJ2) $(LIBOBJ3) $(LIBOBJ4)

# Logical Targets ##################

all: build sample

build: $(PROG1) $(PROG1).man $(PROG2) $(PROG2).man

sample: $(SAMPLE)

test check: build
	./test_$(PROG1).sh ./$(PROG1)

install: build
	cp $(PROG1) $(PREFIX)/bin
	cp $(PROG1).man $(PREFIX)/share/man/man1/$(PROG1).1
	cp $(PROG2) $(PREFIX)/bin
	cp $(PROG2).man $(PREFIX)/share/man/man1/$(PROG2).1

clean:
	-rm -f $(PROG1) $(PROG2) $(SAMPLE) $(PROG1).pod
	-rm -f *.man *.o *.exe *~
	-rm -f t/out?

uninstall:
	-rm -f $(PREFIX)/bin/$(PROG1)
	-rm -f $(PREFIX)/share/man/man1/$(PROG1).1
	-rm -f $(PREFIX)/bin/$(PROG2)
	-rm -f $(PREFIX)/share/man/man1/$(PROG2).1

# Real Targets ####################

# PROG1
$(PROG1): $(PROG1)_m.o $(LIBOBJS)
	$(CXX) -o $@ $^

$(PROG1).pod: $(PROG1).pod-header $(PROG1).pod-middle $(PROG1).pod-footer
	cat $^ > $(PROG1).pod

$(PROG1).pod-middle: $(PROG1)
	./$< -h > $(PROG1).pod-middle

# PROG2
$(PROG2): $(PROG2)_m.o
	$(CXX) -o $@ $^

# SAMPLE
$(SAMPLE).o: $(SAMPLE).cc
	$(CXX) $(CXXFLAGS) -DMAIN_VARIATION=2 -o $@ -c $<

$(SAMPLE): $(SAMPLE).o $(LIBOBJS) $(LIBOBJ0)
	$(CXX) -o $@ $^

# Generic Rules ##############

%_m.o: %.cc
	$(CXX) $(CXXFLAGS) -DMAKE_EXE -o $@ -c $<

%.o: %.cc
	$(CXX) $(CXXFLAGS) -c $<

%: %.o
	$(CXX) -o $@ $< 

%.man: %.pod
	pod2man $< $@

# Special Rules ##############

.PHONY: all build sample test check install clean uninstall 

.PRECIOUS: %.o %.c

.SUFFIXES:
