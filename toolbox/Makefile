# CWPutils/toolbox - Makefile for a set of standalone Python 3 CLI utilities.
#
# All tools (cut2, pullout, rpullout, ghgrep, tcping) are dependency-free
# Python 3 scripts, so "build" is just making sure they are executable
# and syntactically valid; there is nothing to compile.

PYTHON = python3
PREFIX = /usr/local
BINDIR = $(PREFIX)/bin
MANDIR = $(PREFIX)/share/man/man1
SUDO =

BINS     = cut2 pullout rpullout ghgrep tcping
MANPAGES = cut2.1 pullout.1 rpullout.1 ghgrep.1 tcping.1

# Default target
all: build

# "Build": verify each script is syntactically valid and executable.
build:
	@for bin in $(BINS); do \
		$(PYTHON) -m py_compile $$bin || exit 1; \
		chmod +x $$bin; \
	done
	@echo "Build OK: $(BINS)"

# Run the unittest suite for every tool.
test: build
	@$(PYTHON) -m unittest discover -s tests -v

# Install the scripts and man pages.
install: build
	@echo "Installing $(BINS) to $(BINDIR)..."
	@$(SUDO) mkdir -p $(BINDIR)
	@for bin in $(BINS); do \
		$(SUDO) install -m 755 $$bin $(BINDIR)/ || exit 1; \
	done
	@echo "Installing man pages to $(MANDIR)..."
	@$(SUDO) mkdir -p $(MANDIR)
	@for man in $(MANPAGES); do \
		$(SUDO) install -m 644 $$man $(MANDIR)/ || exit 1; \
	done
	-@$(SUDO) mandb >/dev/null 2>&1
	@echo "Installation complete."

# Uninstall the scripts and man pages.
uninstall:
	@echo "Removing $(BINS) from $(BINDIR)..."
	@for bin in $(BINS); do \
		$(SUDO) rm -f $(BINDIR)/$$bin; \
	done
	@echo "Removing man pages from $(MANDIR)..."
	@for man in $(MANPAGES); do \
		$(SUDO) rm -f $(MANDIR)/$$man; \
	done
	-@$(SUDO) mandb >/dev/null 2>&1
	@echo "Uninstallation complete."

# Clean build artifacts (bytecode caches from py_compile/testing).
clean:
	@rm -rf __pycache__ tests/__pycache__ */__pycache__
	@echo "Cleaned up."

.PHONY: all build test install uninstall clean
