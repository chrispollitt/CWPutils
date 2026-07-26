# Makefile for mailx.py and sendmail.py

# Variables
PYTHON := python3
INSTALL_DIR ?= /usr/local/bin
PY_FILES := mailx.py sendmail.py
SCRIPTS := test.sh
INSTALL_DIR_SCRIPTS ?= $(INSTALL_DIR)

.PHONY: all compile test install clean help

all: compile

help:
	@echo "Makefile for mailx.py and sendmail.py project"
	@echo ""
	@echo "Usage:"
	@echo "  make all        - Compile Python files (default)."
	@echo "  make compile    - Compile Python files to .pyc (bytecode)."
	@echo "  make test       - Run the test script (test.sh)."
	@echo "  make install    - Install Python scripts to $(INSTALL_DIR)."
	@echo "                    Use 'make install DESTDIR=/tmp/staging' for staging."
	@echo "  make clean      - Remove compiled files and __pycache__."
	@echo ""

compile:
	@echo "Compiling Python files..."
	$(PYTHON) -m py_compile $(PY_FILES)

test: compile
	@echo "Running tests..."
	@if [ ! -x ./test.sh ]; then \
		echo "Making test.sh executable..."; \
		chmod +x ./test.sh; \
	fi
	./test.sh

install: compile
	@echo "Installing Python scripts to $(DESTDIR)$(INSTALL_DIR)..."
	mkdir -p $(DESTDIR)$(INSTALL_DIR)
	cp $(PY_FILES) $(DESTDIR)$(INSTALL_DIR)/
	chmod +x $(DESTDIR)$(INSTALL_DIR)/mailx.py
	chmod +x $(DESTDIR)$(INSTALL_DIR)/sendmail.py
	@echo "Installation complete."

clean:
	@echo "Cleaning up..."
	rm -f *.pyc
	rm -rf __pycache__
	@echo "Cleanup complete."
