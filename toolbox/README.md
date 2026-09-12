# CWPutils/toolbox - command-line utilities

A small collection of standalone Python 3 command-line utilities for
slicing/filtering text streams and doing quick network diagnostics.
Each tool is a single dependency-free script; no build step or
third-party packages are required.

| Tool | Purpose |
| --- | --- |
| [`cut2`](#cut2) | `cut`-alike with regex delimiters and quote-aware field splitting |
| [`pullout`](#pullout) | Pull a substring out of a stream using before/after context regexes |
| [`rpullout`](#rpullout) | Like `pullout`, but finds the *last* match before an after-context regex |
| [`ghgrep`](#ghgrep) | `grep` that also prints the group/section header a match belongs to |
| [`tcping`](#tcping) | Time a TCP connect/disconnect and report any welcome banner |

Full details for each tool are in its man page (`cut2.1`, `pullout.1`,
`rpullout.1`, `ghgrep.1`, `tcping.1`); this file is a quick-start
summary.

## Requirements

Python 3.8+ and nothing else. All scripts use only the standard
library (`argparse`, `re`, `socket`, `sys`).

## Installation

```bash
make install            # installs to /usr/local/bin and /usr/local/share/man/man1
make PREFIX=$HOME/.local install   # or install to your home directory
```

`make uninstall` removes what `make install` put in place. See the
[Makefile](Makefile) for all targets.

## cut2

An improved `cut` with proper quoting and regex field delimiters.

```bash
echo 'John    Doe    30' | cut2 -f2
# Doe

echo 'John "Doe Smith" 30' | cut2 -f2
# "Doe Smith"        (quotes are preserved, not stripped)

echo 'Alice,Bob,25' | cut2 -f1,3 -d','
# Alice   25

echo 'a,b;c,d' | cut2 -f2,4 -d'[,;]'
# b       d

echo 'abcdef' | cut2 -c1-3
# abc
```

- `-f LIST` / `-c LIST`: select fields or characters (`N`, `N-M`, `N-`, comma-separated, repeatable/reorderable).
- `-d DELIM`: field delimiter, a full regular expression (default `[\t ]+`).
- Quoted spans (`'...'` or `"..."`) are treated as one field even if they contain the delimiter; the quote characters stay in the output.

## pullout

Pulls the bit you want out of a stream, given regexes for what comes
before and after it.

```bash
echo 'name: Alice, age: 30' | pullout 'name: ' '\w+'
# Alice

nslookup 'example.com' | pullout -m 'answer' '\b\d\S+'
```

```
pullout [-A | -a] [-d] [-m] '<bmatch>' '<want>' ['<amatch>']
```

- `-a` / `-A`: also print the matched context (3 or 5 tab-separated parts).
- `-d`: require `<bmatch>`/`<want>`/`<amatch>` to be adjacent (no default `.*?` gap).
- `-m`: multiline mode - read all of stdin at once, `.` matches newlines, every match is reported (not just one per line).

## rpullout

Like `pullout`, but for when you know what comes *after* the value you
want and nothing reliable comes before it. Unlike a plain lazy regex,
it returns the **last** match of `<want>` before `<amatch>`, not the
first.

```bash
echo 'one two three STOP' | rpullout '\w+' 'STOP'
# three
```

```
rpullout [-d] [-m] '<want>' '<amatch>'
```

## ghgrep

A `grep` that understands "groups": search for a pattern and get back
each match's group header too (a `[Section]` heading, the line after a
`----` separator, or a heuristically-detected header), not just the
bare matching line.

```bash
ghgrep "System32" handles.txt
ghgrep -i "listening" netstat.txt
ghgrep --brackets "ESTABLISHED" ports.txt
ghgrep --separator="----" "SysWOW64" handles.txt
```

## tcping

Times how long a TCP connect takes (wall-clock ms), then disconnects
immediately. Along the way it takes one brief, passive look at
whether the server sent an unsolicited "welcome" banner (SSH, FTP,
SMTP and POP3 servers greet before you say anything) - no data is
ever sent to the server.

```bash
tcping github.com 22
# github.com:22 connected in 110.37 ms
# banner: SSH-2.0-49aff2e

tcping example.com 443
# example.com:443 connected in 40.09 ms
# banner: (none within 1.0s)
```

```
tcping [-w TIMEOUT] [-b BANNER_WAIT] [--no-banner] HOST PORT
```

- `-w, --timeout SECONDS`: connect timeout (default 5).
- `-b, --banner-wait SECONDS`: how long to wait for an unsolicited banner (default 1).
- `--no-banner`: skip the banner check; close the socket immediately on connect.

## Testing

Each tool has a standalone `unittest` suite under `tests/` that drives
the real script via `subprocess`, so it exercises the actual CLI
behavior (no internal mocking).

```bash
make test
# or directly:
python3 -m unittest discover -s tests -v
```

## License

MIT - see [LICENSE.txt](LICENSE.txt).
