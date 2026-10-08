# BIDeT 4D Makefile.  Pure Python, so there is nothing to compile: this checks,
# tests, installs and packages.  Run "make help".
SHELL   = /bin/sh
PREFIX  ?= /usr/local
DESTDIR ?=
PYTHON  ?= python3
INSTALL ?= install

BINDIR  = $(DESTDIR)$(PREFIX)/bin
DATADIR = $(DESTDIR)$(PREFIX)/share/BIDeT4D
DOCDIR  = $(DESTDIR)$(PREFIX)/share/doc/bidet4d

# The tools (linked into BINDIR without the .py) and the modules they import.  All of them are installed
# together in DATADIR: a tool linked into BINDIR runs from there, because Python puts the directory of the
# real script first on its path.
TOOLS   = bif bifin bifout
LIB     = bifrender.py bifsixel.py bifin_text.py ttfglyphs.py
PYFILES = $(addsuffix .py,$(TOOLS)) $(LIB)
DOCS    = README.md BIF-SPEC.md HANDOFF.md
TESTS   = tests/test_bif.py tests/test_bifout.py tests/test_bifin.py tests/test_parity.py \
          tests/make_testdata.py tests/reference/unascii_v3.py

VERSION = $(shell sed -n 's/^VERSION = "\(.*\)"/\1/p' bifin.py)
DISTFILES = $(PYFILES) Makefile requirements.txt test.sh .gitignore $(DOCS)

all: lint

help:
	@echo "BIDeT 4D $(VERSION).  Targets:"
	@echo "  lint         - syntax-check the programs, the tests and the shell scripts"
	@echo "  test-quick   - lint, then the library, renderer and importer tests (about 30 seconds)"
	@echo "  test, check  - lint, then everything including the parity gate against unascii (about 8 minutes)"
	@echo "  testdata     - regenerate testdata/ (only when the spec or tests/make_testdata.py changed)"
	@echo "  install      - install bif, bifin and bifout, and the docs, under PREFIX"
	@echo "  uninstall    - remove them again"
	@echo "  installreq   - install the required OS packages (Debian/Ubuntu, as root)"
	@echo "  dist         - make bidet4d-$(VERSION).tar.gz (sources, tests, samples, test data, docs)"
	@echo "  clean        - remove generated files"
	@echo "  version      - print the version"
	@echo "Variables: PREFIX=$(PREFIX)  DESTDIR=  PYTHON=$(PYTHON)"

version:
	@echo $(VERSION)

lint:
	@for f in $(PYFILES) $(TESTS); do \
	    $(PYTHON) -c "import ast,sys; ast.parse(open(sys.argv[1], encoding='utf-8').read())" $$f || exit 1; \
	done
	@sh -n test.sh
	@echo "lint ok"

test-quick: lint
	$(PYTHON) -W ignore tests/test_bif.py
	$(PYTHON) -W ignore tests/test_bifout.py
	$(PYTHON) -W ignore tests/test_bifin.py

test check: lint
	PYTHON=$(PYTHON) ./test.sh

testdata:
	$(PYTHON) tests/make_testdata.py

# Run as root (or set PREFIX and DESTDIR)
install: install-bin install-doc

install-bin:
	$(INSTALL) -d $(DATADIR) $(BINDIR)
	$(INSTALL) -m 755 $(addsuffix .py,$(TOOLS)) $(DATADIR)
	$(INSTALL) -m 644 $(LIB) $(DATADIR)
	for t in $(TOOLS); do ln -sf ../share/BIDeT4D/$$t.py $(BINDIR)/$$t; done

install-doc:
	$(INSTALL) -d $(DOCDIR)
	$(INSTALL) -m 644 $(DOCS) $(DOCDIR)

uninstall:
	for t in $(TOOLS); do rm -f $(BINDIR)/$$t; done
	rm -rf $(DOCDIR) $(DATADIR)

# Run once, as root.  Elsewhere: pip install -r requirements.txt  (no libsixel needed: SIXEL is written here)
installreq:
	@if [ -r /etc/debian_version ]; then \
	    set -x; apt install python3 python3-pil python3-numpy; \
	else \
	    echo "Not Debian/Ubuntu.  Install Python 3, Pillow and numpy with your package manager"; \
	    echo "(Cygwin setup, brew, ...), or:"; \
	    echo "  $(PYTHON) -m pip install -r requirements.txt"; \
	fi

dist: lint
	rm -rf dist/bidet4d-$(VERSION)
	mkdir -p dist/bidet4d-$(VERSION)/tests/reference dist/bidet4d-$(VERSION)/testdata dist/bidet4d-$(VERSION)/samples
	cp $(DISTFILES) dist/bidet4d-$(VERSION)
	cp tests/*.py dist/bidet4d-$(VERSION)/tests
	cp tests/reference/*.py dist/bidet4d-$(VERSION)/tests/reference
	cp -R testdata/good testdata/bad dist/bidet4d-$(VERSION)/testdata
	cp samples/* dist/bidet4d-$(VERSION)/samples
	tar -C dist -czf bidet4d-$(VERSION).tar.gz bidet4d-$(VERSION)
	rm -rf dist
	@echo "made bidet4d-$(VERSION).tar.gz"

clean:
	rm -rf __pycache__ tests/__pycache__ tests/reference/__pycache__ dist out bidet4d-*.tar.gz

.PHONY: all help version lint test-quick test check testdata install install-bin install-doc \
        uninstall installreq dist clean
