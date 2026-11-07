#!/usr/bin/env bash
# -*-Shell-*-

#################################################
#                                               #
#   Test configure (and env2) against each      #
#   flavour of kernel #! handling, using        #
#   t/fakekernel.pl to pretend to be that       #
#   kernel.                                     #
#                                               #
#################################################

errs=0
src="$PWD"

# GNU make is called gmake on Solaris and the BSDs
if [[ -z $MAKE ]]; then
  if command -v gmake >/dev/null 2>&1; then MAKE=gmake; else MAKE=make; fi
fi
export MAKE

###################################
# check_configure MODE EXPECT_KS INFO [MORE_INFO]
#   Run ./configure in a scratch copy with KERNEL_SHIM=MODE, check the
#   kernel it picks and the message it prints, then build env2
#   there and run a few scripts through the shim.
# (configure runs "make clean", so never run it in the source tree here.)
###################################
function check_configure {
  local mode="$1" want_ks="$2" want_info="$3" more_info="$4"
  local tmp got_ks name args want out

  echo "==Test configure $mode"
  tmp=$(mktemp -d "${TMPDIR:-/tmp}/cfgtest.XXXXXX") || { echo "mktemp failed"; (( errs++ )); return; }

  # copy only the sources (no build products, no config.*)
  mkdir "$tmp/t"
  cp Makefile configure sample_script.si.template env2.pod-header env2.pod-footer \
     dumpargs.pod *.cc env2.hh env2lib.hh sample_interpreter.hh "$tmp"
  cp -r t/linux t/naive t/env2rc t/fakekernel.pl "$tmp/t"

  # run configure pretending to be the kernel under test
  ( cd "$tmp" && KERNEL_SHIM=$mode ./configure > configure.log 2>&1 )
  if [[ $? != 0 ]]; then
    echo "Test configure $mode: configure failed:"
    sed 's/^/    /' "$tmp/configure.log"
    (( errs++ ))
    rm -rf "$tmp"
    return
  fi

  # which kernel did it pick?
  got_ks=$(sed -n 's/^#define KERNEL KERNEL_//p' "$tmp/config.hh" | tr A-Z a-z)
  if [[ $got_ks != "$want_ks" ]]; then
    echo "Test configure $mode: expected kernel $want_ks, got '$got_ks'"
    (( errs++ ))
  fi

  # and did it say the right thing?
  if [[ $(<"$tmp/configure.log") != *"$want_info"* ]]; then
    echo "Test configure $mode: configure output does not contain '$want_info'"
    (( errs++ ))
  fi
  if [[ -n $more_info && $(<"$tmp/configure.log") != *"$more_info"* ]]; then
    echo "Test configure $mode: configure output does not contain '$more_info'"
    (( errs++ ))
  fi

  # A kernel nobody has met cannot be run through: env2 takes its flags from the first
  # argument the kernel hands over.  What matters is that configure copes (warns, guesses).
  if [[ $mode == weird ]]; then rm -rf "$tmp"; return; fi

  # build env2 for that kernel and run scripts through the shim
  if ! ( cd "$tmp" && $MAKE -j4 env2 > make.log 2>&1 ); then
    echo "Test configure $mode: make env2 failed:"
    sed 's/^/    /' "$tmp/make.log" | tail -15
    (( errs++ ))
    rm -rf "$tmp"
    return
  fi
  # (a line far longer than 255 bytes must come through whole, wherever the kernel cuts it)
  local longword cases c
  longword=$(printf '%*s' 300 '' | tr ' ' w)
  cases=('plain|-n /bin/echo hello|hello' 'quoted|-n /bin/echo "two words" x|two words x')
  [[ $mode == *:r* ]] || cases+=("long|-n /bin/echo $longword|$longword")   # a refusing kernel never runs it
  for c in "${cases[@]}"; do
    IFS='|' read name args want <<<"$c"
    printf '#!%s %s\n' "$tmp/env2" "$args" > "$tmp/s_$name.sh"
    chmod +x "$tmp/s_$name.sh"
    out=$(cd "$tmp" && perl t/fakekernel.pl "$mode" "./s_$name.sh" 2>&1 | head -1)
    if [[ $out != "$want ./s_$name.sh" ]]; then
      echo "Test configure $mode/$name: expected '$want ./s_$name.sh' got '$out'"
      (( errs++ ))
    fi
  done

  rm -rf "$tmp"
}

# [mode] [kernel configure should pick] [message configure should print]
check_configure linux   linux "kernel does NOT split #! line" "kernel does NOT limit the length of the #! line"
check_configure naive   naive "kernel DOES split #! line but does NOT handle escaped whitespace"
check_configure perfect naive "kernel DOES split #! line and DOES handle escaped whitespace"
check_configure solaris solaris "kernel DOES truncate #! line"
check_configure linux:255  linux "kernel limits the #! line to about 255 bytes"   # Linux 5.1 and later
check_configure linux:127  linux "kernel limits the #! line to about 127 bytes"   # Linux before 5.1
check_configure naive:255  naive "kernel limits the #! line to about 255 bytes"
check_configure linux:r255 linux "kernel limits the #! line to about"             # a kernel that refuses long lines
check_configure weird      naive "unrecognised kernel handling of the #! line" "unrecognised handling of the script name"    # something never seen: guess, do not stop

if [[ $errs != 0 ]]; then echo "**FAIL=$errs**"; exit 1; fi
exit 0
