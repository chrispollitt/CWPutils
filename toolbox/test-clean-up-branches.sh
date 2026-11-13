#!/bin/bash
# Tests for clean-up-branches.sh (the offer part), on throwaway repos with a bare "origin": nothing real is read or changed.
#   bash toolbox/test-clean-up-branches.sh
here=$(cd "$(dirname "$0")" && pwd)
S=$here/clean-up-branches.sh
T=$(mktemp -d "${TMPDIR:-/tmp}/cub-test.XXXXXX"); trap 'rm -rf "$T"' EXIT
pass=0; failn=0
ok()  { pass=$((pass+1)); }
bad() { failn=$((failn+1)); echo "FAIL: $1"; [ -n "${2:-}" ] && printf '%s\n' "$2" | sed 's/^/    | /'; }
has() { case "$3" in *"$2"*) ok ;; *) bad "$1 (wanted: $2)" "$3" ;; esac; }
no()  { case "$3" in *"$2"*) bad "$1 (did not want: $2)" "$3" ;; *) ok ;; esac; }
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t

mk() {   # build repo R under $T/gh with a bare origin and a spread of branches
  local g=$T/gh/R o=$T/origin/R.git
  rm -rf "$g" "$o"; mkdir -p "$T/gh" "$T/origin"
  git init -q --bare "$o"
  git init -q -b main "$g"; git -C "$g" remote add origin "$o"
  echo 1 > "$g/f"; git -C "$g" add f; git -C "$g" commit -q -m base
  git -C "$g" push -q origin main
  # merged, local and on origin
  git -C "$g" branch merged-both; git -C "$g" push -q origin merged-both
  # merged, only on origin
  git -C "$g" push -q origin main:refs/heads/merged-remote-only
  # rebased copy: patch in main under another hash
  git -C "$g" checkout -q -b rebased; echo r > "$g/r"; git -C "$g" add r; git -C "$g" commit -q -m "add r"
  git -C "$g" checkout -q main; echo r > "$g/r"; git -C "$g" add r   # the same patch on main, under another hash (another date)
  GIT_AUTHOR_DATE="2020-01-01T00:00:00" GIT_COMMITTER_DATE="2020-01-01T00:00:00" git -C "$g" commit -q -m "add r"
  # unmerged, on origin
  git -C "$g" checkout -q -b old-unmerged; echo u > "$g/u"; git -C "$g" add u; git -C "$g" commit -q -m "unmerged work"; git -C "$g" push -q origin old-unmerged
  # unmerged, only here
  git -C "$g" checkout -q main; git -C "$g" checkout -q -b only-here; echo o > "$g/o"; git -C "$g" add o; git -C "$g" commit -q -m "only copy"
  # unmerged, only on origin
  git -C "$g" checkout -q main; git -C "$g" checkout -q -b remote-work; echo w > "$g/w"; git -C "$g" add w; git -C "$g" commit -q -m "remote work"; git -C "$g" push -q origin remote-work; git -C "$g" checkout -q main; git -C "$g" branch -q -D remote-work
  # listed in keep-branches.txt
  git -C "$g" branch keepme; git -C "$g" push -q origin keepme
  # merged branch with a clean .claude/worktrees worktree, and one with a worktree elsewhere
  git -C "$g" branch wt-clean; git -C "$g" worktree add -q "$g/.claude/worktrees/wt-clean" wt-clean
  rm -rf "$T/elsewhere"; git -C "$g" branch wt-elsewhere; git -C "$g" worktree add -q "$T/elsewhere" wt-elsewhere
  git -C "$g" fetch -q origin
}
run() {   # answers on stdin; prints the output
  GH=$T/gh LIST=$T/list KEEP=$T/keep WGIT=git CLEANUP_ASSUME_TTY=1 bash "$S" "$@" 2>&1
}
branches() { git -C "$T/gh/R" for-each-ref --format='%(refname:short)' refs/heads | tr '\n' ' '; }
remotes()  { git -C "$T/gh/R" ls-remote --heads origin | sed 's#.*refs/heads/##' | tr '\n' ' '; }
: > "$T/list"
echo "R keepme" > "$T/keep"

# ---- dry run: lists, changes nothing
mk
before="$(branches)|$(remotes)"
out=$(run -n </dev/null)
has "dry run lists a merged local branch as safe" "[safe  ] R              local   merged-both" "$out"
has "dry run lists a merged GitHub branch" "github  merged-remote-only" "$out"
has "rebased copies count as safe" "rebased  --  its 1 commit(s) are in main already" "$out"
has "an unmerged branch is a review item" "[review] R              local   only-here" "$out"
has "and says it is the only copy" "NOT on origin: the only copy" "$out"
has "an unmerged GitHub-only branch is a review item" "[review] R              github  remote-work" "$out"
has "a clean .claude/worktrees worktree goes with its branch" "its clean worktree goes too" "$out"
has "a worktree elsewhere is kept" "kept:  R wt-elsewhere -- checked out in a worktree outside .claude/worktrees" "$out"
no  "the keep list hides a branch" "keepme" "$(printf '%s' "$out" | grep -v 'kept:')"
no  "main is never offered (local)" "local   main " "$out"
no  "main is never offered (GitHub)" "github  main " "$out"
has "dry run says so" "dry run: nothing asked, nothing deleted" "$out"
[ "$before" = "$(branches)|$(remotes)" ] && ok || bad "dry run changed something"

# ---- no terminal: lists only
out=$(GH=$T/gh LIST=$T/list KEEP=$T/keep WGIT=git bash "$S" </dev/null 2>&1)
has "without a terminal it only lists" "no terminal: listed only" "$out"
[ "$before" = "$(branches)|$(remotes)" ] && ok || bad "no-terminal run changed something"

# ---- --no-offer: nothing but the list pass
out=$(run --no-offer </dev/null)
no "--no-offer skips the search" "Looking for branches" "$out"

# ---- a = all safe ones
out=$(printf 'a\n' | run)
has "a deletes a merged local branch" "done:  deleted local R merged-both" "$out"
has "a deletes a merged GitHub branch" "done:  deleted on GitHub R merged-remote-only" "$out"
has "a deletes the rebased copy" "done:  deleted local R rebased" "$out"
has "a removes the clean worktree with its branch" "done:  deleted local R wt-clean" "$out"
[ ! -d "$T/gh/R/.claude/worktrees/wt-clean" ] && ok || bad "the clean worktree directory is still there"
case " $(branches)" in *" only-here "*) ok ;; *) bad "a deleted a review branch" "$(branches)" ;; esac
case " $(branches)" in *" old-unmerged "*) ok ;; *) bad "a deleted an unmerged branch" ;; esac
case " $(branches)" in *" wt-elsewhere "*) ok ;; *) bad "a deleted a branch that has a worktree elsewhere" ;; esac
case " $(remotes)" in *" old-unmerged "*) ok ;; *) bad "a deleted an unmerged GitHub branch (old-unmerged)" "$(remotes)" ;; esac
case " $(remotes)" in *" remote-work "*) ok ;; *) bad "a deleted an unmerged GitHub branch (remote-work)" "$(remotes)" ;; esac
case " $(remotes)" in *" merged-both "*|*" merged-remote-only "*) bad "merged GitHub branches are still there" "$(remotes)" ;; *) ok ;; esac
case " $(remotes)" in *" keepme "*) ok ;; *) bad "a deleted the kept branch on GitHub" ;; esac

# ---- review items: the name must be typed
mk
n=$(run -n </dev/null | grep -n "local   only-here" | head -1 | sed 's/^[^0-9]*\([0-9]*\) .*/\1/'); n=$(run -n </dev/null | sed -n 's/^ *\([0-9]*\)  \[review\] R .*local   only-here.*/\1/p')
out=$(printf '%s\nwrong\n' "$n" | run)
has "a review item asks for the name" "type the branch name to delete it" "$out"
has "and shows what would be lost" "only copy" "$out"
has "and how to bring it back" "git branch only-here" "$out"
case " $(branches)" in *" only-here "*) ok ;; *) bad "a wrong confirmation deleted the branch" ;; esac
out=$(printf '%s\nonly-here\n' "$n" | run)
has "typing the name deletes it" "done:  deleted local R only-here" "$out"
case " $(branches)" in *" only-here "*) bad "only-here is still there" ;; *) ok ;; esac

# ---- k: never offer again
mk
n=$(run -n </dev/null | sed -n 's/^ *\([0-9]*\)  \[review\] R .*local   only-here.*/\1/p')
out=$(printf 'k %s\n' "$n" | run)
has "k adds the branch to the keep list" "R only-here" "$(cat "$T/keep")"
out=$(run -n </dev/null)
no "a kept branch is not offered again" "only-here" "$(printf '%s' "$out" | grep -v 'kept:')"

# ---- an entry for a branch deleted by the offer leaves the list file
mk; echo "R merged-both" > "$T/list"
run <<< "a" >/dev/null
no "the list file forgets a branch the offer deleted" "merged-both" "$(cat "$T/list")"

echo "clean-up-branches tests: $pass passed, $failn failed"
[ "$failn" -eq 0 ]
