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
LIBOBJ3 = vars2.o
LIBOBJS = $(LIBOBJ1) $(LIBOBJ2) $(LIBOBJ3)

# Logical Targets ##################

build all: progs samples

rebuild: clean all

progs: $(PROG1) $(PROG1).man $(PROG2) $(PROG2).man

samples: $(SAMPLE)1 $(SAMPLE)2 $(SAMPLE)3

test check: all
	./test_$(PROG1).sh ./$(PROG1)

install: build
	cp $(PROG1) $(PREFIX)/bin
	cp $(PROG1).man $(PREFIX)/share/man/man1/$(PROG1).1
	cp $(PROG2) $(PREFIX)/bin
	cp $(PROG2).man $(PREFIX)/share/man/man1/$(PROG2).1

clean:
	-rm -f $(PROG1) $(PROG2) $(SAMPLE)1 $(SAMPLE)2 $(SAMPLE)3 $(PROG1).pod
	-rm -f *.man *.o *.exe *~ *.stackdump core
	-rm -f t/out?

uninstall:
	-rm -f $(PREFIX)/bin/$(PROG1)
	-rm -f $(PREFIX)/share/man/man1/$(PROG1).1
	-rm -f $(PREFIX)/bin/$(PROG2)
	-rm -f $(PREFIX)/share/man/man1/$(PROG2).1

fixpaths:
	@for f in sample_script.si t/exp*; do \
	perl -lpi~ -e 's,/(.+/CWPutils/)(sample_interpreter),'"$(PWD)"'/$$2,;' $$f; \
	done

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

# SAMPLES
$(SAMPLE)1.o: $(SAMPLE).cc
	$(CXX) $(CXXFLAGS) -DMAIN_VARIATION=1 -o $@ -c $<
$(SAMPLE)1: $(SAMPLE)1.o $(LIBOBJS) $(LIBOBJ0)
	$(CXX) -o $@ $^
$(SAMPLE)2.o: $(SAMPLE).cc
	$(CXX) $(CXXFLAGS) -DMAIN_VARIATION=2 -o $@ -c $<
$(SAMPLE)2: $(SAMPLE)2.o $(LIBOBJS) $(LIBOBJ0)
	$(CXX) -o $@ $^
$(SAMPLE)3.o: $(SAMPLE).cc
	$(CXX) $(CXXFLAGS) -DMAIN_VARIATION=3 -o $@ -c $<
$(SAMPLE)3: $(SAMPLE)3.o $(LIBOBJS) $(LIBOBJ0)
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

.PHONY: all build rebuild progs samples test check install clean uninstall fixpaths

.PRECIOUS: %.o %.c

.SUFFIXES:
