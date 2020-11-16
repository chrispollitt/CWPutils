PREFIX = /usr/local

all: man

man:
	pod2man BIDeT.pl > BIDeT.man

clean:
	-rm -f BIDeT.man

install:
	mkdir -p $(PREFIX)/share/BIDeT
	mkdir -p $(PREFIX)/share/man/man1
	mkdir -p $(PREFIX)/bin
	cp BIDeT.man $(PREFIX)/share/man/man1/bidet.1
	cp BIDeT.pl $(PREFIX)/bin/bidet
	perl -lpi -e 's,("\$$Bin),$$1/../share/BIDeT, and print ' $(PREFIX)/bin/bidet
	chmod 555 $(PREFIX)/bin/bidet
	cp netpbm_rgb.txt  PostScript_Simple.pm $(PREFIX)/share/BIDeT
