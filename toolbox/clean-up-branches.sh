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
#
# OFFER (after that list): it also looks through every repo under $GH for branches nobody asked it to remove but that look no longer
# needed, local ones and the ones on GitHub (origin), prints them numbered, and OFFERS to delete the ones you pick:
#   [safe]    everything on the branch is in main, or only as rebased copies of patches main already has
#   [review]  commits that are NOT in main (shown, with their age).  Needs the branch name typed back to confirm; a local branch
#             that is not on origin is the only copy and says so.  `a` (all) never includes these.
# Never touched: main/master, the branch checked out in the repo itself, a branch checked out in a worktree outside
# .claude/worktrees (a clean .claude/worktrees one is removed together with its branch), a branch with an open pull request,
# and anything in keep-branches.txt next to this script ("repo branch" lines, or "repo *"; answer "k 3,4" to add items to it).
# Local branches go with git branch -d (-D only for the cases above where main has the work); GitHub ones with git push --delete.
# Without a terminal it only lists.
# Usage: clean-up-branches.sh [-n] [--no-offer]    (-n = dry run: lists and changes nothing; --no-offer = only the list pass)

GH=${GH:-/home/chris/gh_cp}
dry=; offer=auto
for a in "$@"; do
  case $a in
    -n) dry=echo ;;
    --no-offer) offer=no ;;
    -h|--help) sed -n '2,/^# Usage/p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "usage: clean-up-branches.sh [-n] [--no-offer]" >&2; exit 2 ;;
  esac
done

# Worktrees made by Windows git carry D:/ paths that Cygwin git rejects on remove
# ("does not point back to"), so worktree status/remove/prune go through Windows git when present.
if [ -z "${WGIT:-}" ]; then
  WGIT=git
  for p in "/cygdrive/c/Program Files/Git/cmd/git.exe" "/c/Program Files/Git/cmd/git.exe"; do
    [ -x "$p" ] && { WGIT=$p; break; }
  done
fi
wgit() { local r=$1; shift; [ "$WGIT" = git ] || r=$(cygpath -m "$r"); "$WGIT" -C "$r" "$@"; }

LIST=${LIST:-$(dirname "$0")/tmp-branches.txt}
BRANCHES=()
if [ -f "$LIST" ]; then
  mapfile -t BRANCHES < <(grep -vE '^[[:space:]]*(#|$)' "$LIST" | sed 's/[[:cntrl:]]*$//')
else
  echo "(no list file $LIST: only the search below)"
fi

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
[ -d "$GH/TUIs" ] && $dry wgit "$GH/TUIs" worktree prune

# ------------------------------------------------------------------------------------------------------------------------------
# Offer: look for branches that are no longer needed, local and on GitHub
[ "$offer" = no ] && exit 0
KEEP=${KEEP:-$(dirname "$0")/keep-branches.txt}
have_tty=; { [ -t 0 ] || [ -n "${CLEANUP_ASSUME_TTY:-}" ]; } && have_tty=1

C_n=0
declare -a C_repo C_kind C_name C_cls C_why C_wt
keep_listed() { [ -f "$KEEP" ] && { grep -qxF "$1 $2" "$KEEP" || grep -qxF "$1 *" "$KEEP"; }; }
add() { C_repo[C_n]=$1; C_kind[C_n]=$2; C_name[C_n]=$3; C_cls[C_n]=$4; C_why[C_n]=$5; C_wt[C_n]=${6:-}; C_n=$((C_n + 1)); }

# classify AHEAD UNIQUE REF REPO-DIR MAIN -> cls, why
classify() {
  if [ "$1" -eq 0 ]; then cls=safe; why="merged into $5"
  elif [ "$2" -eq 0 ]; then cls=safe; why="its $1 commit(s) are in $5 already, as rebased copies"
  else cls=review; why="$1 commit(s) NOT in $5, last $(git -C "$4" log -1 --format=%ar "$3")"
  fi
}

scan_repo() {
  local repo=$1 g="$GH/$1" main= cur m b ahead uniq wt onorigin wtmap rb name pr
  for m in main master; do git -C "$g" rev-parse --verify -q "refs/heads/$m" >/dev/null && { main=$m; break; }; done
  [ -n "$main" ] || return
  git -C "$g" remote get-url origin >/dev/null 2>&1 && timeout 40 git -C "$g" fetch -q --prune origin 2>/dev/null
  cur=$(git -C "$g" branch --show-current)
  wtmap=$(git -C "$g" worktree list --porcelain | awk '/^worktree /{p=$2} /^branch refs\/heads\//{b=$2; sub("refs/heads/","",b); print b "\t" p}')
  while read -r b; do
    [ -n "$b" ] || continue
    [ "$b" = "$main" ] || [ "$b" = "$cur" ] && continue
    keep_listed "$repo" "$b" && continue
    wt=$(printf '%s\n' "$wtmap" | awk -F'\t' -v b="$b" '$1==b{print $2; exit}')
    if [ -n "$wt" ]; then
      case $wt in
        */.claude/worktrees/*)
          [ -z "$(wgit "$wt" status --porcelain 2>&1)" ] || { echo "kept:  $repo $b -- its worktree has changes: $wt"; continue; } ;;
        *) echo "kept:  $repo $b -- checked out in a worktree outside .claude/worktrees: $wt"; continue ;;
      esac
    fi
    ahead=$(git -C "$g" rev-list --count "$main..$b")
    uniq=$(git -C "$g" cherry "$main" "$b" | grep -c '^+')
    classify "$ahead" "$uniq" "$b" "$g" "$main"
    onorigin=no; git -C "$g" rev-parse --verify -q "refs/remotes/origin/$b" >/dev/null && onorigin=yes
    [ "$cls" = review ] && { [ $onorigin = yes ] && why="$why; the same work stays on origin" || why="$why; NOT on origin: the only copy"; }
    [ -n "$wt" ] && why="$why; its clean worktree goes too"
    add "$repo" local "$b" "$cls" "$why" "$wt"
  done < <(git -C "$g" for-each-ref --format='%(refname:short)' refs/heads)
  while read -r rb; do
    name=${rb#origin/}
    case $name in HEAD|origin|"$main"|"") continue ;; esac
    keep_listed "$repo" "$name" && continue
    if command -v gh >/dev/null 2>&1; then
      pr=$(gh pr list -R "$(git -C "$g" remote get-url origin)" --head "$name" --state open --json number --jq '.[0].number' 2>/dev/null)
      [ -n "$pr" ] && { echo "kept:  $repo origin/$name -- open pull request #$pr"; continue; }
    fi
    ahead=$(git -C "$g" rev-list --count "$main..$rb")
    uniq=$(git -C "$g" cherry "$main" "$rb" | grep -c '^+')
    classify "$ahead" "$uniq" "$rb" "$g" "$main"
    add "$repo" github "$name" "$cls" "$why"
  done < <(git -C "$g" for-each-ref --format='%(refname:short)' refs/remotes/origin)
}

echo
echo "Looking for branches that are no longer needed ..."
for d in "$GH"/*/; do
  [ -e "${d}.git" ] && scan_repo "$(basename "$d")"
done
[ "$C_n" -gt 0 ] || { echo "nothing to offer: no stale branches found"; exit 0; }

echo
printf ' %3s  %-8s %-14s %-7s %s\n' "#" "" "repo" "where" "branch  --  why"
for ((i = 0; i < C_n; i++)); do
  printf ' %3d  [%-6s] %-14s %-7s %s  --  %s\n' $((i + 1)) "${C_cls[i]}" "${C_repo[i]}" "${C_kind[i]}" "${C_name[i]}" "${C_why[i]}"
done
echo
[ -n "$dry" ] && { echo "(dry run: nothing asked, nothing deleted)"; exit 0; }
[ -n "$have_tty" ] || { echo "(no terminal: listed only; run this in a terminal to clean up)"; exit 0; }

# numbers like "1,3,5-7" -> indexes
expand() { local t lo hi i; for t in ${1//,/ }; do case $t in *-*) lo=${t%-*}; hi=${t#*-} ;; *) lo=$t; hi=$t ;; esac
  [[ $lo =~ ^[0-9]+$ && $hi =~ ^[0-9]+$ ]] || continue; for ((i = lo; i <= hi; i++)); do [ "$i" -ge 1 ] && [ "$i" -le "$C_n" ] && echo $((i - 1)); done; done; }

printf '%s' "Delete which?  a = all [safe] ones, numbers (1,3,5-7), k NUMBERS = never offer again, Enter = none: "; read -r ans
[ -n "$ans" ] || { echo "nothing deleted"; exit 0; }
sel=()
case $ans in
  a|A) for ((i = 0; i < C_n; i++)); do [ "${C_cls[i]}" = safe ] && sel+=($i); done ;;
  k*|K*) for i in $(expand "${ans#?}"); do echo "${C_repo[i]} ${C_name[i]}" >> "$KEEP"; echo "keeping: ${C_repo[i]} ${C_name[i]} (in $KEEP)"; done; exit 0 ;;
  *) mapfile -t sel < <(expand "$ans") ;;
esac
[ "${#sel[@]}" -gt 0 ] || { echo "nothing selected"; exit 0; }

for i in "${sel[@]}"; do
  repo=${C_repo[i]}; g="$GH/$repo"; b=${C_name[i]}; kind=${C_kind[i]}; wt=${C_wt[i]}
  main=; for m in main master; do git -C "$g" rev-parse --verify -q "refs/heads/$m" >/dev/null && { main=$m; break; }; done
  if [ "${C_cls[i]}" = review ]; then
    ref=$b; [ "$kind" = github ] && ref=origin/$b
    echo; echo "$repo $kind $b is NOT merged: ${C_why[i]}"
    git -C "$g" log --format='   %h %ad %s' --date=short -5 "$main..$ref"
    echo "   tip: $(git -C "$g" rev-parse --short "$ref")  (to bring it back: git branch $b $(git -C "$g" rev-parse --short "$ref"))"
    printf '%s' "   type the branch name to delete it, anything else keeps it: "; read -r c
    [ "$c" = "$b" ] || { echo "   kept"; continue; }
  fi
  if [ "$kind" = local ]; then
    if [ -n "$wt" ]; then wgit "$g" worktree remove "$wt" || { echo "FAILED: could not remove worktree $wt; $repo $b kept"; continue; }; fi
    if git -C "$g" branch -d "$b" >/dev/null 2>&1 || git -C "$g" branch -D "$b" >/dev/null 2>&1; then
      echo "done:  deleted local $repo $b"
      [ -f "$LIST" ] && { grep -vxF "$repo $b" "$LIST" > "$LIST.new"; mv "$LIST.new" "$LIST"; }
    else echo "FAILED: $repo $b"; fi
  else
    if git -C "$g" push origin --delete "$b" >/dev/null 2>&1; then echo "done:  deleted on GitHub $repo $b"; git -C "$g" fetch -q --prune origin 2>/dev/null
    else echo "FAILED: could not delete $repo origin/$b on GitHub"; fi
  fi
done
