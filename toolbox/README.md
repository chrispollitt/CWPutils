# CWPutils/toolbox - command-line utilities

A small collection of standalone command-line utilities for
slicing/filtering text streams, quick network diagnostics and taming
Cygwin on Windows. Each tool is a single dependency-free script (Python 3,
or bash for `fixperms` and `gitcheck`); no build step or third-party packages are required.

| Tool | Purpose |
| --- | --- |
| [`cut2`](#cut2) | `cut`-alike with regex delimiters and quote-aware field splitting |
| [`pullout`](#pullout) | Pull a substring out of a stream using before/after context regexes |
| [`rpullout`](#rpullout) | Like `pullout`, but finds the *last* match before an after-context regex |
| [`ghgrep`](#ghgrep) | `grep` that also prints the group/section header a match belongs to |
| [`tcping`](#tcping) | Time a TCP connect/disconnect and report any welcome banner |
| [`termprobe`](#termprobe) | Find out what survives the trip between a program and its terminal (colour queries, key and mouse input, ConPTY/ssh damage) |
| [`wincygterm`](#wincygterm) | Run Cygwin programs on a real pty inside Windows Terminal (fixes OSC colour queries and ncurses input) |
| [`fixperms`](#fixperms) | Repair owner, mode and ACL of files created from an elevated (administrator) Cygwin shell |
| [`gitcheck`](#gitcheck) | Report uncommitted changes and unpushed commits in every repo under a directory, and optionally commit, push and clone missing GitHub repos |

Full details for each tool are in its man page (`cut2.1`, `pullout.1`,
`rpullout.1`, `ghgrep.1`, `tcping.1`, `termprobe.1`, `wincygterm.1`,
`fixperms.1`, `gitcheck.1`); this
file is a quick-start summary.

## Requirements

Python 3.8+ and nothing else. All the Python scripts use only the standard
library (`argparse`, `re`, `socket`, `sys`). `fixperms` needs bash 4+ and
the usual coreutils plus `getfacl`/`setfacl` (part of Cygwin's base install).
`gitcheck` needs bash 4.4+ and git; the GitHub CLI `gh` is optional.

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

## termprobe

Asks the controlling terminal what a capability-negotiating TUI asks (colours
with OSC 10/11, DA1/DA2, window and cell size, cursor position, kitty keys,
mouse and win32-input-mode state) and checks that the replies are whole,
single and consistent - then, with `--tvision`, replays tvision's startup and
tests keyboard and mouse input, counting key records cut in two on the way.
Run it in each terminal / shell / ssh combination and compare.

```bash
termprobe --label mintty
ssh -tt host termprobe --label via-ssh
termprobe --tvision --label tvmail-repro
```

```
termprobe [--timeout S] [--label TEXT] [--raw] [--input | --tvision] [--no-vt-input]
```

- Two verdicts: `OSC 11` (`ANSWERED` / `DROPPED` / `SILENT`) and `NEGOTIATION` (`CLEAN` / `MANGLED`, with the reasons); things worth knowing that are not faults (win32-input-mode being on) are printed as `note:` lines. It prints the tty name, and on a Cygwin console (`/dev/cons*`) a dropped OSC 11 comes with a hint to use `wincygterm`, mintty or ssh.
- `--input`: interactive keyboard and mouse fidelity test; `--tvision`: the same after setting the terminal up as tvision does.
- Exit status 0 clean, 1 a problem found, 2 no terminal. Works on POSIX (incl. Cygwin, mintty, WSL) and native Windows Python.

## wincygterm

Windows only. A Cygwin program started directly in a Windows Terminal tab
runs on Cygwin's console layer (`/dev/cons*`), which swallows OSC colour
queries (so programs cannot learn the terminal's colours) and, behind ssh,
lets key input reach ncurses programs in fragments that show up as stray text.
`wincygterm` runs the command on a real Cygwin pty (`/dev/pty*`) instead, as
mintty and ssh do, while staying in your Windows Terminal tab.

Run it with a **native Windows** Python (not Cygwin's). It is two halves in one
file: a Windows front-end that forwards bytes between the console and a pipe,
and a helper, run by Cygwin's Python, that puts the command on the pty.

```bash
python wincygterm --login-dir                  # bash -l on a pty, in the Cygwin home
python wincygterm -- /bin/zsh                  # another command
python wincygterm --profile                    # print a Windows Terminal profile command line
```

```
python wincygterm [--root DIR] [--python EXE] [--term TERM] [--login-dir] [--no-reset] [--debug FILE] [--] [CMD [ARG...]]
```

- Finds Cygwin by `--root`, `$CYGWIN_ROOT`, the registry, then the usual places.
- Handles window resizes, UTF-8, and hangs up the command if the tab is closed.
- For a Windows Terminal profile use the full path of the Windows Python and add `--login-dir`.
- Not winpty: winpty runs a Windows console program inside a Unix pty; this runs a Cygwin program on a pty inside a Windows console.
- Not needed in mintty or any other terminal that already gives Cygwin programs a pty; it is for Windows Terminal and other ConPTY consoles.
- Sets `WINCYGTERM=<version>` for the command; `termprobe` shows it as a `via:` line.
- Check the result with `termprobe` (`tty` should say `/dev/pty*`, OSC 11 `ANSWERED`).
- Tested in Windows Terminal 1.24 with a Cygwin 3.7 development snapshot: `bash`, a live `tvmail` session and a live `bidet` animation all work.

## fixperms

Files created from an elevated ("Run as administrator") Cygwin shell - an
elevated `pip install` into `/usr/local`, a build, anything in `~/.local` -
often end up owned by Administrators with Windows ACLs that a normal shell
cannot read: `Permission denied`, failed imports, a trailing `+` in `ls -l`.
`chmod` alone does not fix them. `fixperms` walks the tree top-down (never
following symlinks), sets owner and group to you, and replaces each ACL with
a minimal, inheritable one via `setfacl -s` (falling back to
`icacls /reset` and `chmod`), so new files created there come out clean too.

```bash
fixperms -n /usr/local/lib/python3.12/site-packages   # dry run: what would change
fixperms -v /usr/local/lib/python3.12/site-packages   # fix it, listing each change
fixperms -w ~/github/myproject                        # group-writable (775/664)
```

```
fixperms [-n] [-v] [-d] [-u USER] [-g GROUP] [-w] [-x] [-f] [-r FILE]... [-R] PATH...
fixperms --list-rules
```

- Where no rule says otherwise, modes become 755 for directories and 644 for files; files keep x for everyone if any x bit was set or they start with `#!`, `MZ` (exe/dll/pyd, which Cygwin needs x on to load) or ELF magic. `-x` ignores old x bits and goes by content alone; `-w` adds group write (in a home: wherever the group can already read).
- `-d` / `--no-recurse` fixes only the named paths; `-n` / `--dry-run` changes nothing; `-v` lists changes (`-vv` also unchanged entries).
- Taking ownership of Administrators-owned files usually needs an elevated shell: `fixperms` reports those, fixes everything else, and prints the command to rerun elevated.
- Refuses `/`, the Cygwin root, drive roots and top-level directories such as `/usr` without `-f`. Exit status 0 all fixed, 1 something not fixed, 2 usage error.

Places that need other modes or owners are handled by a rule table. The first
match wins, `--list-rules` prints the table, and `-v` says which rule each
change came from. Built in:

- `~/.ssh` 700, keys and `config` 600, `*.pub` and `known_hosts` 644; `~/.gnupg`, `~/.getmail` 700/600; credential files (`~/.netrc`, `~/.authinfo*`, `~/.git-credentials`, `~/.msmtprc`, `~/.pgpass`, ...) 600.
- Anywhere else in a home: `=`, i.e. keep the mode but drop write for group and others, so private files such as `mbox` are never loosened. A home's contents go to the account the `/home/NAME` directory belongs to, not to whoever runs the command.
- `/var/mail` and `/var/spool/mail` stay 1777 and keep their owner, and each mailbox becomes 600 and is owned by the account it is named after. `/tmp`, `/var/tmp` and `/var/log` stay 1777 and their contents keep their owners. sshd's host keys are 600 (`.pub` 644) and `/var/empty` is 755, all keeping their owners.

Add your own in `~/.config/fixperms/rules` or with `--rules FILE`, one per
line: `PATTERN DIR-MODE FILE-MODE OWNER`. The mode is `-` (default), `=`
(keep, never loosen) or octal. The owner is `user`, `keep`, `home`, `base`
or an account name. For example `/srv/www/** 775 664 www`. `--no-rules`
turns the table off.

## gitcheck

Run over a folder of clones to see what still needs committing or pushing.
For each git repository directly under the directory it reports whether it
has a GitHub remote (and, with `gh` signed in, whether the repo exists on
GitHub), then whatever the options ask for.

```bash
gitcheck -c ~/github/chrispollitt     # uncommitted changes, unpushed commits
gitcheck -c -i ~/github/chrispollitt  # same, and offer to add/ignore, commit, push
gitcheck -u -i ~/github/chrispollitt  # ...and offer to clone GitHub repos not here yet
gitcheck -f -s                        # fetch; ahead/behind; summary (current dir)
```

```
Processing CWPutils...
  ├─ Linked to GitHub: Yes (exists on GitHub)
  ├─ Uncommitted changes: Yes (branch: main)
  │  ├─ Tracked files changed: 3
  │  └─ Untracked files: 1
  ├─ Unpulled commits: Yes
  │  └─ main: 2 (from origin/main)
  │     ⚠ Diverged (1 local); merging would conflict in: README.md
  │     ⚠ Uncommitted changes to files changed upstream: Makefile
  ├─ Unpushed commits: Yes
  │  └─ main: 1
  │  └─ media: 1 (local only)
```

- `-c` splits changes into tracked files and untracked ones; lists branches whose upstream has commits they don't (unpulled), flagging potential conflicts with ⚠ (a diverged branch whose merge, tried in memory with `git merge-tree`, would conflict; uncommitted changes to files the upstream also changed); and counts commits on each local branch that are on no remote-tracking branch (unpushed). It compares with the remotes as of the last fetch. `-f` fetches first and compares the current branch with its upstream; `-b` lists branches, `-l` files over 1 MB, `-s` a summary.
- `-c -i` asks, per untracked item, to add, `.gitignore` or skip it; then whether to commit all tracked changes or only what is staged; then, for each branch that is behind its upstream, whether to pull, but only when it is safe (a fast-forward, or a merge or rebase of the checked-out branch that `git merge-tree` says won't conflict, and never over uncommitted changes to the same files); then, for each branch with unpushed commits, whether to set an upstream (if it has none) and whether to push. `q` quits.
- `-u` lists your GitHub repositories that have no directory of the same name here (needs `gh`); with `-i` it offers to clone each one.
- Subdirectories that are not repositories are flagged, except names like `tmp`, `BAK`, `old` or `*.bak` (any case) and anything listed in `~/.config/gitcheck/ignore` (name patterns, or full paths starting with `/`). With `-i`, answering `g` to a flagged directory makes it a new repo (`git init`, add or ignore its files, an initial commit, then optionally `gh repo create` as private or public and push); answering `i` adds it to the ignore file.
- Answering `n` to setting an upstream marks the branch local-only (`branch.NAME.gitcheckNoUpstream` in the repo's config), and `n` to cloning adds the repo to `~/.config/gitcheck/noclone`, so neither is asked about again.

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
