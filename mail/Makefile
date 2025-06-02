all: compile

compile:
	python -m py_compile *.py

test:
	./test.sh

install: compile test
	cp *.py /usr/local/bin

