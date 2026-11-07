#!/usr/bin/env bash
# -*-Shell-*-

#################################################
#                                               #
#   Tests for shebanglab                        #
#                                               #
#################################################

errs=0
lab=./shebanglab

# The env2 in this directory is built for one kind of kernel (config.hh); the env2 rows
# can only be checked for that kernel unless "make lab" has built the other one too.
hostname=$(sed -n 's/^#define KERNEL KERNEL_//p' config.hh 2>/dev/null | tr A-Z a-z)
hostname=${hostname:-linux}
if [[ $hostname == linux ]]; then othername=naive; else othername=linux; fi

# cells ROW-PREFIX OPTION... LINE : the last two columns (the kernel results) of the first
# table row that starts with ROW-PREFIX
function cells {
  local prefix="$1"; shift
  $lab --format table --timeout 5 "$@" 2>&1 | grep "^$prefix" | head -1 | awk '{print $(NF-1), $NF}'
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

# The line with no helper: linux passes one string, naive splits it badly, so neither is right.
echo "==Test shebanglab-direct"
expect direct-table "X X" "$(cells direct --no-env --no-env2 --kernels linux,naive,solaris "$line")"

# solaris keeps only the first argument
echo "==Test shebanglab-kernel2"
expect kernel2 "ok" "$(lastcell direct --no-env --no-env2 --kernels solaris --want "-n|<script>" "$line")"

# the exact arguments, from the JSON output
echo "==Test shebanglab-json"
got=$($lab --format json --no-env --no-env2 --kernels linux,naive "$line" 2>&1 | perl -MJSON::PP -e '
  my $d = decode_json(join "", <STDIN>);
  my $c = $d->{rows}[0]{cells};
  my %want = (
    linux => [q{-n -q -d '"'"'x=a b'"'"'}, q{<script>}],
    naive => [q{-n}, q{-q}, q{-d}, q{'"'"'x=a}, q{b'"'"'}, q{<script>}],
  );
  my @bad = grep { join("\x1f", @{$c->{$_}{args}}) ne join("\x1f", @{$want{$_}}) } qw(linux naive);
  print @bad ? "differs for kernel(s) @bad" : "ok";')
expect json-args ok "$got"

# env2 (the build in this directory) fixes the kernel it was built for, in every mode
echo "==Test shebanglab-env2"
for m in classic shellwords wordexp; do
  expect "env2-$m" ok "$(lastcell env2 --no-env --no-direct --kernels $hostname --modes $m "$line")"
done

# GNU env -S fixes linux (one string) but not naive (quotes already lost)
if env -S true >/dev/null 2>&1; then
  echo "==Test shebanglab-env-S"
  expect env-S "ok X" "$(cells 'env -S' --no-env2 --no-direct --kernels linux,naive "$line")"
  echo "==Test shebanglab-env-plain"
  # plain env: on linux it cannot find a program called "php -n -q ..." (or loops, which is also an ERR)
  expect env-plain "ERR X" "$(cells 'env  ' --no-env2 --no-direct --kernels linux,naive "$line")"
fi

# a file whose line already names a helper: that line is tested as written, first
echo "==Test shebanglab-file"
tmpf=$(mktemp "${TMPDIR:-/tmp}/sbl.XXXXXX")
printf '#!/usr/bin/env2 -Sn php -n -q\n' > "$tmpf"
expect file-as-written ok "$(lastcell 'as written' --no-env --no-direct --no-env2 --kernels $hostname "$tmpf")"
rm -f "$tmpf"

# --strict: exit status 1 when something is not ok, 0 when all is
echo "==Test shebanglab-strict"
$lab --strict --format table --no-env --no-direct --kernels $hostname "$line" >/dev/null 2>&1; expect strict-ok 0 $?
$lab --strict --format table --no-env --no-env2 --kernels linux,naive "$line" >/dev/null 2>&1; expect strict-bad 1 $?

# no env2 build for a kernel: n/a (only checkable when "make lab" has not been run)
if [[ ! -x lab/env2-$othername && ! -x lab/env2-$othername.exe ]]; then
  echo "==Test shebanglab-no-build"
  out=$($lab --no-env --no-direct --kernels $othername --modes shellwords --env2-$hostname ./env2 "$line" 2>&1); st=$?
  expect na-refuses 2 $st
  [[ $out == *"make lab"* ]] || { echo "Test na-refuses: message does not mention make lab"; (( errs = errs + 1 )); }
fi

# --want overrides the intended arguments
echo "==Test shebanglab-want"
expect want ok "$(lastcell direct --no-env --no-env2 --kernels linux --want "-n -q -d 'x=a b'|<script>" "$line")"

if [[ $errs != 0 ]]; then echo "**FAIL=$errs**"; exit 1; fi
exit 0
