# Variables
CC = gcc
CFLAGS = -Wall -Wextra -O2
LDFLAGS = -lpcre
BIN = cut2
MANPAGE = cut2.1
PREFIX = /usr/local
BINDIR = $(PREFIX)/bin
MANDIR = $(PREFIX)/share/man/man1
SUDO =

# Default target
all: build

# Compile cut2
build: $(BIN).c
	$(CC) $(CFLAGS) -c $(BIN).c
	$(CC) -o $(BIN) $(BIN).o $(LDFLAGS)

# Run test cases
test: build
	@echo "Running tests..."
	@echo 'John "Doe Smith" 30' | ./cut2 -f2 | grep -q "Doe Smith" && echo "[PASS] Quoted field" || echo "[FAIL] Quoted field"
	@echo 'Alice,Bob,25' | ./cut2 -f1,3 -d',' | grep -q "Alice" && echo "[PASS] Delimited fields (comma)" || echo "[FAIL] Delimited fields (comma)"
	@echo "abcdef" | ./cut2 -c1-3 | grep -q "abc" && echo "[PASS] Character selection" || echo "[FAIL] Character selection"
	@echo 'foo  bar    baz' | ./cut2 -f1,3 | grep -q "foo" && echo "[PASS] Default delimiter (multiple spaces)" || echo "[FAIL] Default delimiter (multiple spaces)"
	@echo 'a,b;c,d' | ./cut2 -f2,4 -d'[,;]' | grep -q "b" && echo "[PASS] PCRE delimiter" || echo "[FAIL] PCRE delimiter"
	@echo -e 'a\t\tb\tc' | ./cut2 -f1,3 | grep -q "a" && echo "[PASS] Tab delimiter" || echo "[FAIL] Tab delimiter"

# Install the binary and man page
install: build
	@echo "Installing $(BIN) to $(BINDIR)..."
	@$(SUDO) install -m 755 $(BIN) $(BINDIR)/
	@echo "Installing man page to $(MANDIR)..."
	@$(SUDO) install -m 644 $(MANPAGE) $(MANDIR)/
	@$(SUDO) mandb
	@echo "Installation complete."

# Uninstall the binary and man page
uninstall:
	@echo "Removing $(BIN) from $(BINDIR)..."
	@$(SUDO) rm -f $(BINDIR)/$(BIN)
	@echo "Removing man page from $(MANDIR)..."
	@$(SUDO) rm -f $(MANDIR)/$(MANPAGE)
	@$(SUDO) mandb
	@echo "Uninstallation complete."

# Clean build artifacts
clean:
	@rm -f $(BIN) $(BIN).o
	@echo "Cleaned up."

.PHONY: all build test install uninstall clean