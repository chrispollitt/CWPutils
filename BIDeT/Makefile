SHELL  = /bin/bash
PREFIX = /usr/local

DEBIAN = $(shell cat /etc/os-release 2>/dev/null|grep -i debian)

build all: img2ans man

img2ans: img2ans.c

man:
	pod2man BIDeT.pl > BIDeT.man

test check: build
	./test-sixel.sh
	./BIDeT.pl "Hello, World!"

clean:
	-rm -f BIDeT.man img2ans img2ans.exe

# Run as root
install: build
ifneq ($(DEBIAN),)
	@echo "*** NOTE! You may want to run: sudo make fixnetpbm"
endif
	mkdir -p $(PREFIX)/share/BIDeT
	mkdir -p $(PREFIX)/share/man/man1
	mkdir -p $(PREFIX)/bin
	-rm -rf $(PREFIX)/bin/test-sixel $(PREFIX)/share/man/man1/bidet.1 $(PREFIX)/bin/bidet /usr/local/share/BIDeT/*
	cp test-sixel.sh $(PREFIX)/bin/test-sixel
	chmod 555 $(PREFIX)/bin/test-sixel
	cp BIDeT.man $(PREFIX)/share/man/man1/bidet.1
	cp BIDeT.pl $(PREFIX)/bin/bidet
	perl -lpi -e 's,([" ]\$$Bin),$$1/../share/BIDeT,' $(PREFIX)/bin/bidet
	chmod 555 $(PREFIX)/bin/bidet
	cp img2ans netpbm_rgb.txt  PostScript_Simple.pm fontlist.txt fontsuffixlist.txt $(PREFIX)/share/BIDeT
	[[ $$(uname) != CYGWIN* ]] || cp netpbm.sh /etc/profile.d

# Run Once, as root
ifneq ($(DEBIAN),)

installreq:
	apt install ghostscript ghostscript-x gsfonts gsfonts-other gsfonts-x11
	apt install moreutils
	apt install libsixel-bin
	apt install mlterm

fixnetpbm:
	./fixnetpbm
endif

help:
	@echo "Targets are:"
	@echo "  build       - build objects"
	@echo "  test        - test program"
	@echo "  install     - install program"
	@echo "  installreq  - install required OS packages"
	@echo "  fixnetpbm   - fix netpbm on Ubuntu/Debian"

.PHONY: build all man test check clean install installreq fixnetpbm

