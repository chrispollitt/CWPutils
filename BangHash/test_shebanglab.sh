#!/bin/bash
# -*-Shell-*-

#################################################
#                                               #
#   Tests for shebanglab                        #
#                                               #
#################################################

errs=0
lab=./shebanglab

# cells ROW-PREFIX OPTION... LINE : the last three columns (the kernel results) of the first
# table row that starts with ROW-PREFIX
function cells {
  local prefix="$1"; shift
  $lab --format table --timeout 5 "$@" 2>&1 | grep "^$prefix" | head -1 | awk '{print $(NF-2), $(NF-1), $NF}'
}

# last column only
function lastcell {
  local prefix="$1"; shift
  $lab --format table --timeout 5 "$@" 2>&1 | grep "^$prefix" | head -1 | awk '{print $NF}'
}

function expect {   # expect NAME WANT GOT
  if [[ $3 != "$2" ]]; then
    echo "Test $1: expected '$2' got '$3'"
    (( errs = errs + 1 ))
  fi
}

if [[ ! -x $lab ]]; then echo "Error: $lab not found"; exit 1; fi
line="php -n -q -d 'x=a b'"

echo "==Test shebanglab-usage"
$lab >/dev/null 2>&1; expect usage-exit 2 $?
$lab --version | grep -q '^shebanglab ' || { echo "Test shebanglab-usage: bad --version"; (( errs = errs + 1 )); }

# The line with no helper: kernel 0 passes one string, kernel 1 splits it badly, kernel 2 is right.
echo "==Test shebanglab-direct"
expect direct-table "X X ok" "$(cells direct --no-env --no-env2 --kernels 0,1,2 "$line")"

# the exact arguments, from the JSON output
echo "==Test shebanglab-json"
got=$($lab --format json --no-env --no-env2 --kernels 0,1,2 "$line" 2>&1 | perl -MJSON::PP -e '
  my $d = decode_json(join "", <STDIN>);
  my $c = $d->{rows}[0]{cells};
  my %want = (
    0 => [q{-n -q -d '"'"'x=a b'"'"'}, q{<script>}],
    1 => [q{-n}, q{-q}, q{-d}, q{'"'"'x=a}, q{b'"'"'}, q{<script>}],
    2 => [q{-n}, q{-q}, q{-d}, q{x=a b}, q{<script>}],
  );
  my @bad = grep { join("\x1f", @{$c->{$_}{args}}) ne join("\x1f", @{$want{$_}}) } 0, 1, 2;
  print @bad ? "differs for kernel(s) @bad" : "ok";')
expect json-args ok "$got"

# env2 (the build in this directory) fixes kernel 0 in every mode
echo "==Test shebanglab-env2"
for m in classic shellwords wordexp; do
  expect "env2-$m" ok "$(lastcell env2 --no-env --no-direct --kernels 0 --modes $m "$line")"
done

# GNU env -S fixes kernel 0 (one string) but not kernel 1 (quotes already lost)
if env -S true >/dev/null 2>&1; then
  echo "==Test shebanglab-env-S"
  expect env-S "ok X ok" "$(cells 'env -S' --no-env2 --no-direct --kernels 0,1,2 "$line")"
  echo "==Test shebanglab-env-plain"
  # plain env: on kernel 0 it cannot find a program called "php -n -q ..." (or loops, which is also an ERR)
  expect env-plain "ERR X ok" "$(cells 'env  ' --no-env2 --no-direct --kernels 0,1,2 "$line")"
fi

# a file whose line already names a helper: that line is tested as written, first
echo "==Test shebanglab-file"
tmpf=$(mktemp "${TMPDIR:-/tmp}/sbl.XXXXXX")
printf '#!/usr/bin/env2 -Sn php -n -q\n' > "$tmpf"
expect file-as-written ok "$(lastcell 'as written' --no-env --no-direct --no-env2 --kernels 0 "$tmpf")"
rm -f "$tmpf"

# --strict: exit status 1 when something is not ok, 0 when all is
echo "==Test shebanglab-strict"
$lab --strict --format table --no-env --no-direct --kernels 0 "$line" >/dev/null 2>&1; expect strict-ok 0 $?
$lab --strict --format table --no-env --no-env2 --kernels 0,1,2 "$line" >/dev/null 2>&1; expect strict-bad 1 $?

# no env2 build for a kernel: n/a (only checkable when "make lab" has not been run)
if [[ ! -x lab/env2-ks1 && ! -x lab/env2-ks1.exe ]]; then
  echo "==Test shebanglab-na"
  expect na n/a "$(lastcell env2 --no-env --no-direct --kernels 1 --modes shellwords --env2-ks0 ./env2 "$line")"
fi

# --want overrides the intended arguments
echo "==Test shebanglab-want"
expect want ok "$(lastcell direct --no-env --no-env2 --kernels 0 --want "-n -q -d 'x=a b'|<script>" "$line")"

if [[ $errs != 0 ]]; then echo "**FAIL=$errs**"; exit 1; fi
exit 0
