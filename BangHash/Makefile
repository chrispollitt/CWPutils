# Variables ###########################

# config.mk is made by ./configure.  Don't require it when the only goals are
# clean/distclean, so that distclean can remove it.  (No goals = default target.)
NEED_CONFIG := $(if $(MAKECMDGOALS),$(filter-out clean distclean,$(MAKECMDGOALS)),all)
ifneq ($(NEED_CONFIG),)
include config.mk
endif

# Generate header dependencies (*.d) as a side effect of compiling
CXXFLAGS += -MMD -MP

# Internal variables (change at your peril)
PROG1   = env2
PROG2   = dumpargs
SAMPLE  = sample_interpreter
LIBOBJ0 = $(PROG1).o
LIBOBJ1 = $(PROG2).o
LIBOBJ2 = array_utils.o
LIBOBJ3 = vars2.o
LIBOBJ4 = switches.o
LIBOBJ5 = shellwords.o
LIBOBJS = $(LIBOBJ1) $(LIBOBJ2) $(LIBOBJ3) $(LIBOBJ4) $(LIBOBJ5)

# Logical Targets ##################

build all: progs samples

rebuild: clean all

progs: $(PROG1) $(PROG1).man $(PROG2) $(PROG2).man

samples: $(SAMPLE)1 $(SAMPLE)2 $(SAMPLE)3

test check: all splitcheck
	./test_$(PROG1).sh ./$(PROG1)
	./test_configure.sh

install: build
	mkdir -p $(PREFIX)/bin
	mkdir -p $(PREFIX)/share/man/man1
	cp $(PROG1) $(PREFIX)/bin
	cp $(PROG1).man $(PREFIX)/share/man/man1/$(PROG1).1
	cp $(PROG2) $(PREFIX)/bin
	cp $(PROG2).man $(PREFIX)/share/man/man1/$(PROG2).1

clean:
	-rm -f $(PROG1) $(PROG2) $(SAMPLE) $(SAMPLE)1 $(SAMPLE)2 $(SAMPLE)3 splitcheck $(PROG1).pod *.pod-middle sample_script.si da
	-rm -f *.man *.o *.d *.exe *~ *.stackdump core
	-rm -f t/out*

distclean: clean
	-rm -f t/exp* config.hh config.mk

uninstall:
	-rm -f $(PREFIX)/bin/$(PROG1)
	-rm -f $(PREFIX)/share/man/man1/$(PROG1).1
	-rm -f $(PREFIX)/bin/$(PROG2)
	-rm -f $(PREFIX)/share/man/man1/$(PROG2).1

fixpaths:
	@for f in t/exp*; do \
	perl -lpi~ -e 's,/(.+/CWPutils/BangHash/)(sample_interpreter),'"$(PWD)"'/$$2,;' $$f; \
	done
	@rm t/exp*~

# Real Targets ####################

# PROG1
$(PROG1): $(PROG1)_m.o $(LIBOBJS)
	$(LDXX) $(LDXXFLAGS) -o $@ $^ $(LDXXLIBS)

$(PROG1).pod: $(PROG1).pod-header $(PROG1).pod-middle $(PROG1).pod-footer
	cat $^ > $(PROG1).pod

$(PROG1).pod-middle: $(PROG1)
	./$< -h > $(PROG1).pod-middle

# PROG2
$(PROG2): $(PROG2)_m.o
	$(LDXX) $(LDXXFLAGS) -o $@ $^ $(LDXXLIBS)

# splitcheck: test harness for split_string()/split_shellwords() (see t/splitcompare.pl)
splitcheck: t/splitcheck.cc $(LIBOBJS)
	$(CXX) $(CXXFLAGS) -I. -o $@ t/splitcheck.cc $(LIBOBJS) $(LDXXLIBS)

# SAMPLES
$(SAMPLE)1.o: $(SAMPLE).cc
	$(CXX) $(CXXFLAGS) -DMAIN_VARIATION=1 -o $@ -c $<
$(SAMPLE)1: $(SAMPLE)1.o $(LIBOBJS) $(LIBOBJ0)
	$(LDXX) $(LDXXFLAGS) -o $@ $^ $(LDXXLIBS)
$(SAMPLE)2.o: $(SAMPLE).cc
	$(CXX) $(CXXFLAGS) -DMAIN_VARIATION=2 -o $@ -c $<
$(SAMPLE)2: $(SAMPLE)2.o $(LIBOBJS) $(LIBOBJ0)
	$(LDXX) $(LDXXFLAGS) -o $@ $^ $(LDXXLIBS)
$(SAMPLE)3.o: $(SAMPLE).cc
	$(CXX) $(CXXFLAGS) -DMAIN_VARIATION=3 -o $@ -c $<
$(SAMPLE)3: $(SAMPLE)3.o $(LIBOBJS) $(LIBOBJ0)
	$(LDXX) $(LDXXFLAGS) -o $@ $^ $(LDXXLIBS)

# Generic Rules ##############

%_m.o: %.cc
	$(CXX) $(CXXFLAGS) -DMAKE_EXE -o $@ -c $<

%.o: %.cc
	$(CXX) $(CXXFLAGS) -c $<

%: %.o
	$(LDXX) $(LDXXFLAGS) -o $@ $< $(LDXXLIBS)

%.man: %.pod
	pod2man $< $@
	perl -lpi -e 's,PREFIX,'"$(PREFIX)"',g' $@

# Special Rules ##############

-include $(wildcard *.d)

.PHONY: all build rebuild progs samples test check install clean uninstall fixpaths

.PRECIOUS: %.o %.cc

.SUFFIXES:
