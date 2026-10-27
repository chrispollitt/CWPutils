#!/bin/bash
# Standing clean-up of finished branches. Each entry is "repo branch".
# A branch is only removed if ALL of these hold; otherwise it is skipped with a reason:
#   - the repo's main branch (main/master) exists
#   - every commit on the branch is reachable from main (nothing unmerged)
#   - its .claude/worktrees/<name> worktree, if any, has no uncommitted or untracked files
#   - the branch is not checked out in some other worktree
# Local only; remotes are untouched. Never forces (no -D, no worktree remove --force).
# Branches to clean live in tmp-branches.txt next to this script (one "repo branch" per line;
# blank lines and # comments ignored). An entry is removed from that file once its branch
# is confirmed deleted (or already gone). Skipped entries stay for the next run.
# Usage: clean-up-branches.sh [-n]    (-n = dry run)

GH=${GH:-/home/chris/gh_cp}
dry=; [ "$1" = -n ] && dry=echo

# Worktrees made by Windows git carry D:/ paths that Cygwin git rejects on remove
# ("does not point back to"), so worktree status/remove/prune go through Windows git when present.
WGIT=git
for p in "/cygdrive/c/Program Files/Git/cmd/git.exe" "/c/Program Files/Git/cmd/git.exe"; do
  [ -x "$p" ] && { WGIT=$p; break; }
done
wgit() { local r=$1; shift; [ "$WGIT" = git ] || r=$(cygpath -m "$r"); "$WGIT" -C "$r" "$@"; }

LIST=${LIST:-$(dirname "$0")/tmp-branches.txt}
[ -f "$LIST" ] || { echo "no $LIST"; exit 0; }
mapfile -t BRANCHES < <(grep -vE '^[[:space:]]*(#|$)' "$LIST" | sed 's/[[:cntrl:]]*$//')

# drop a finished entry from the list file (not on dry run)
forget() {
  [ -n "$dry" ] && return
  grep -vxF "$repo $b" "$LIST" > "$LIST.new" ; mv "$LIST.new" "$LIST"
}

skip() { echo "SKIP:  $repo $b -- $*"; }

for entry in "${BRANCHES[@]}"; do
  read -r repo b <<< "$entry"
  g="$GH/$repo"
  git -C "$g" rev-parse --verify -q "refs/heads/$b" >/dev/null || { echo "gone:  $repo $b"; forget; continue; }

  main=
  for m in main master; do
    git -C "$g" rev-parse --verify -q "refs/heads/$m" >/dev/null && { main=$m; break; }
  done
  [ -n "$main" ] || { skip "no main/master branch"; continue; }
  [ "$b" = "$main" ] && { skip "is the main branch"; continue; }

  if ! git -C "$g" merge-base --is-ancestor "$b" "$main"; then
    n=$(git -C "$g" rev-list --count "$main..$b")
    skip "$n commit(s) not merged into $main"; continue
  fi

  # use the path git registered (may be a D:/ path made by Windows git, not our /home/... path)
  wt=$(git -C "$g" worktree list --porcelain | sed -n "s/^worktree //p" | grep -F "/.claude/worktrees/${b#claude/}" | head -n1)
  if [ -n "$wt" ] && [ -d "$wt" ]; then
    if [ -n "$(wgit "$wt" status --porcelain 2>&1)" ]; then
      skip "worktree has uncommitted or untracked files: $wt"; continue
    fi
    $dry wgit "$g" worktree remove "$wt" || { skip "could not remove worktree $wt"; continue; }
  fi

  # checked out in some other worktree (e.g. not under .claude/worktrees)?
  if git -C "$g" worktree list --porcelain | grep -qx "branch refs/heads/$b"; then
    [ -n "$dry" ] && [ -n "$wt" ] || { skip "still checked out in a worktree"; continue; }
  fi

  $dry git -C "$g" branch -d "$b" && { echo "done:  $repo $b"; forget; }
done
$dry wgit "$GH/TUIs" worktree prune
