# BIDeT3D Makefile.  Pure Python, so there is nothing to compile: this checks,
# tests, installs and packages.  Run "make help".
SHELL   = /bin/sh
PREFIX  ?= /usr/local
DESTDIR ?=
PYTHON  ?= python3
INSTALL ?= install

BINDIR  = $(DESTDIR)$(PREFIX)/bin
MANDIR  = $(DESTDIR)$(PREFIX)/share/man/man1
DATADIR = $(DESTDIR)$(PREFIX)/share/BIDeT3D
DOCDIR  = $(DESTDIR)$(PREFIX)/share/doc/bidet3d

# The converters for --format (sixel2kitty and friends) live in ../gfx-conv; they are
# installed under DATADIR/gfx, with the tools linked into BINDIR.
GFX      = ../gfx-conv
GFXLIB   = sixeldec.py
GFXTOOLS = sixel2ans sixel2iterm sixel2kitty sixel2tek

VERSION = $(shell sed -n 's/^VERSION = "\(.*\)"/\1/p' bidet3d.py)
DOCS    = README.md LICENSE 3RDPARTY CHANGELOG.md
DISTFILES = bidet3d.py bidet3d.1 Makefile requirements.txt test.sh profiling.sh get-textures.sh \
            .gitattributes .gitignore $(DOCS)

all: lint

help:
	@echo "BIDeT3D $(VERSION).  Targets:"
	@echo "  lint         - syntax-check the program, scripts and man page"
	@echo "  test, check  - lint, then render every preset (test.sh)"
	@echo "  man          - read the man page without installing it"
	@echo "  textures     - fetch the optional Word textures (get-textures.sh)"
	@echo "  install      - install bidet3d, its man page, docs and the gfx-conv converters under PREFIX"
	@echo "  uninstall    - remove them again"
	@echo "  installreq   - install the required OS packages (Debian/Ubuntu, as root)"
	@echo "  dist         - make bidet3d-$(VERSION).tar.gz"
	@echo "  clean        - remove generated files"
	@echo "  version      - print the version"
	@echo "Variables: PREFIX=$(PREFIX)  DESTDIR=  PYTHON=$(PYTHON)"

version:
	@echo $(VERSION)

lint:
	@$(PYTHON) -c "import ast; ast.parse(open('bidet3d.py', encoding='utf-8').read())"
	@sh -n test.sh && sh -n profiling.sh && sh -n get-textures.sh
	@for f in $(GFXLIB) $(addsuffix .py,$(GFXTOOLS)); do \
	    $(PYTHON) -c "import ast,sys; ast.parse(open(sys.argv[1], encoding='utf-8').read())" $(GFX)/$$f || exit 1; \
	done
	@if command -v groff >/dev/null 2>&1; then \
	    out=$$(groff -man -ww -z bidet3d.1 2>&1); \
	    if [ -n "$$out" ]; then echo "$$out"; exit 1; fi; \
	elif command -v mandoc >/dev/null 2>&1; then \
	    mandoc -Tlint bidet3d.1; \
	else echo "(no groff or mandoc: man page not checked)"; fi
	@echo "lint ok"

test check: lint
	./test.sh
	cd $(GFX) && PYTHON=$(PYTHON) ./test.sh

man:
	man ./bidet3d.1

textures:
	./get-textures.sh

# Run as root (or set PREFIX and DESTDIR)
install: install-bin install-man install-data install-gfx

install-bin:
	$(INSTALL) -d $(BINDIR)
	$(INSTALL) -m 755 bidet3d.py $(BINDIR)/bidet3d

install-man:
	$(INSTALL) -d $(MANDIR)
	$(INSTALL) -m 644 bidet3d.1 $(MANDIR)/bidet3d.1

# docs, and the Word textures if you fetched them (bidet3d looks in ../share/BIDeT3D/textures)
install-data:
	$(INSTALL) -d $(DOCDIR)
	$(INSTALL) -m 644 $(DOCS) $(DOCDIR)
	@if ls textures/*.png >/dev/null 2>&1; then \
	    $(INSTALL) -d $(DATADIR)/textures; \
	    $(INSTALL) -m 644 textures/*.png $(DATADIR)/textures; \
	fi

# the converters: modules and tools in DATADIR/gfx (where bidet3d --format finds them),
# and the tools linked into BINDIR as sixel2ans, sixel2iterm, ...
install-gfx:
	$(INSTALL) -d $(DATADIR)/gfx $(BINDIR)
	$(INSTALL) -m 644 $(addprefix $(GFX)/,$(GFXLIB)) $(DATADIR)/gfx
	$(INSTALL) -m 755 $(addprefix $(GFX)/,$(addsuffix .py,$(GFXTOOLS))) $(DATADIR)/gfx
	$(INSTALL) -d $(DOCDIR)
	$(INSTALL) -m 644 $(GFX)/README.md $(DOCDIR)/gfx-conv.md
	$(INSTALL) -m 644 $(GFX)/GRAPHICS-HISTORY.md $(DOCDIR)
	for t in $(GFXTOOLS); do ln -sf ../share/BIDeT3D/gfx/$$t.py $(BINDIR)/$$t; done

uninstall:
	rm -f $(BINDIR)/bidet3d $(MANDIR)/bidet3d.1
	for t in $(GFXTOOLS); do rm -f $(BINDIR)/$$t; done
	rm -rf $(DOCDIR) $(DATADIR)

# Run once, as root.  Elsewhere: pip install -r requirements.txt  (and see README.md)
installreq:
	@if [ -r /etc/debian_version ]; then \
	    set -x; apt install python3 python3-pil python3-numpy libsixel-bin; \
	else \
	    echo "Not Debian/Ubuntu.  Install Python 3, Pillow, numpy and libsixel"; \
	    echo "(img2sixel) with your package manager (Cygwin setup, brew, ...), or:"; \
	    echo "  $(PYTHON) -m pip install -r requirements.txt"; \
	fi

dist: lint
	rm -rf dist/bidet3d-$(VERSION)
	mkdir -p dist/bidet3d-$(VERSION)
	cp $(DISTFILES) dist/bidet3d-$(VERSION)
	mkdir -p dist/bidet3d-$(VERSION)/gfx
	cp $(addprefix $(GFX)/,$(GFXLIB) $(addsuffix .py,$(GFXTOOLS)) README.md GRAPHICS-HISTORY.md test.sh) \
	   dist/bidet3d-$(VERSION)/gfx
	tar -C dist -czf bidet3d-$(VERSION).tar.gz bidet3d-$(VERSION)
	rm -rf dist
	@echo "made bidet3d-$(VERSION).tar.gz (the css3wordart textures are not included)"

clean:
	rm -rf __pycache__ dist bidet3d-*.tar.gz

.PHONY: all help version lint test check man textures install install-bin install-man \
        install-data install-gfx uninstall installreq dist clean
