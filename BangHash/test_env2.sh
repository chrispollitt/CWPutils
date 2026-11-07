#!/bin/bash
# -*-Shell-*-

#################################################
#                                               #
#   Run the unit tests for env2                 #
#                                               #
#################################################

###################################
# Prepare the sample_script with the desired #! line
###################################
function set_sample_script {
  local iargs="$1"
  local body="$2"
  local inter
  
  if [[ $iargs == /* ]]; then
    inter=""
  else
    inter="$PWD/sample_interpreter "
  fi
  
  echo -E "#!$inter$iargs" > sample_script.si
  if [[ -n $body ]]; then
    echo -E "$body" >> sample_script.si
  else
    cat sample_script.si.template >> sample_script.si
  fi
  chmod 755 sample_script.si
}

###################################
# Run env2 the way a #! line would, whatever the kernel does.
#   run_line 'ARGS-STRING' [script-args ...]
# ARGS-STRING is what follows "env2" on the #! line (flags, interpreter, its args).
#   KERNEL_SPLIT 0 (Linux, Cygwin): the kernel hands env2 the whole string as one
#     argument, so call env2 that way, with /bin/true standing in for the script.
#   KERNEL_SPLIT 1 (Solaris, macOS): the kernel splits or truncates the line, and
#     env2 re-reads it from the script file, so write a real script file with that
#     line and run it. Its path is replaced by /bin/true in the output, so the
#     expected results are the same for both.
# Needs $prog and $ks (set in main) and $target_script and $prog_abs.
# Returns the exit status; in the KERNEL_SPLIT 1 case stderr is merged into stdout.
###################################
function run_line {
  local line="$1"; shift
  if [[ $ks == 0 ]]; then
    "$prog" "$line" /bin/true "$@"
    return
  fi
  printf '#!%s %s\n' "$prog_abs" "$line" > "$target_script"
  chmod 755 "$target_script"
  local output status
  output=$("$target_script" "$@" 2>&1)
  status=$?
  if [[ -n $output ]]; then printf '%s\n' "${output//"$target_script"//bin/true}"; fi
  return $status
}

###################################
# main
###################################
function main {
  # set vars
  local prog="${1%.exe}"
  local errs=0
  local ks=""
  local inter=""
  local rc="${prog}rc"
  rc="${rc##*/}"
  ks=$(perl -lne '/KERNEL_SPLIT (\d+)/ and print $1' config.hh)
  
  # make sure . is first in PATH
  export PATH=".:$PATH"
  
  # test prog
  if [[ -z $prog || ! -x $prog ]]; then
    echo "Error: prog not found: '$1'"
    exit 1
  fi
  
  # Use a private HOME for the test rc files, so the tests never touch (or leave
  # anything behind in) the user's real home directory.
  local tmphome
  tmphome=$(mktemp -d "${TMPDIR:-/tmp}/env2test.XXXXXX") || { echo "mktemp failed"; exit 1; }
  trap 'rm -rf "$tmphome"' EXIT
  export HOME="$tmphome"
  target_script="$tmphome/target.si"      # used by run_line when KERNEL_SPLIT is 1
  case $prog in /*) prog_abs=$prog ;; *) prog_abs="$PWD/${prog#./}" ;; esac
  cp t/$rc ~/.$rc
  cp t/$rc ~/.sample_interpreterrc
  
  #############################################
  
  ### no args OR help ######

  ln -fs $prog sample_interpreter
  
  # Run Test 0 - [no args]
  echo "==Test 0"
  $prog >& t/out0
  diff t/out0 t/exp0
  [[ $? != 0 ]] && (( errs = errs + 1 ))
  
  # Run Test 1 - help
  echo "==Test 1"
  $prog -h >& t/out1
  diff t/out1 t/exp1
  [[ $? != 0 ]] && (( errs = errs + 1 ))
  
  ### perl #################
  
  # Run Test 2 - debug, emit, delim
  echo "==Test 2"
  set_sample_script '-dpef perl -l ~~ "" "hello\\ two"' '$"=q/" "/;print qq/ARGV="@ARGV" FOO="$ENV{FOO}"/'
  script_args='goodbye'
  ./sample_script.si $script_args >& t/out2
  diff t/out2 t/exp2
  [[ $? != 0 ]] && (( errs = errs + 1 ))
  
  # Run Test 3 - +strip
  echo "==Test 3"
  set_sample_script '-defs perl -l ~~ "hello\\ three"' '$"=q/" "/;print qq/ARGV="@ARGV" FOO="$ENV{FOO}"/'
  script_args='goodbye'
  ./sample_script.si $script_args >& t/out3
  diff t/out3 t/exp3
  [[ $? != 0 ]] && (( errs = errs + 1 ))
  
  # Run Test 4 - [no flags]
  echo "==Test 4"
  set_sample_script 'perl -l' '$"=q/" "/;print qq/ARGV="@ARGV" FAR="$ENV{FAR}"/'  
  script_args='hello four'
  ./sample_script.si $script_args >& t/out4
  diff t/out4 t/exp4
  [[ $? != 0 ]] && (( errs = errs + 1 ))
  
  ### bash #################
  
  # Run Test 5 - debug, expand
  echo "==Test 5"
  set_sample_script '-dxf bash ~~ "tab\ttab"' 'echo -E "Hi from 5 $1"'
  script_args=''
  ./sample_script.si $script_args >& t/out5
  diff t/out5 t/exp5
  [[ $? != 0 ]] && (( errs = errs + 1 ))
  
  # Run Test 6 - debug, norc 
  echo "==Test 6"
  # (C: this test covers the classic splitter keeping the backslash in "tab\ttab")
  set_sample_script '-dnCf bash -x ~~ "tab\ttab"' 'echo -E "Hi from 6 $1"'
  script_args=''
  ./sample_script.si $script_args >& t/out6
  diff t/out6 t/exp6
  [[ $? != 0 ]] && (( errs = errs + 1 ))
  
  # Run Test 7 - debug, norc, comment
  echo "==Test 7"
  set_sample_script '-dnc bash -x # comment' 'echo "Hi from 7" $1' 
  script_args=''
  ./sample_script.si $script_args >& t/out7
  diff t/out7 t/exp7
  [[ $? != 0 ]] && (( errs = errs + 1 ))
  
  ### sample_interpreter ############
  
  set_sample_script "-a -b -c:foo ~~ -1 -2 -3"
  script_args="-4 -5 -6"
  
  (( i = 1 ))
  while (( i <= 2 ));do
    echo "==Test s$i"
    ln -fs sample_interpreter$i sample_interpreter
    ./sample_script.si $script_args >& t/outs$i
    diff t/outs$i t/exps$i
    [[ $? != 0 ]] && (( errs = errs + 1 ))
    (( i = i + 1 ))
  done
    
  ### regressions: fixed-size buffers ############

  echo "==Test long-arg"
  long=$(printf 'a%.0s' $(seq 300))
  got=$(run_line "-n /bin/echo $long" 2>&1)
  if [[ $got != "$long /bin/true" ]]; then
    echo "Test long-arg: unexpected output (${#got} chars)"
    (( errs = errs + 1 ))
  fi

  echo "==Test many-args"
  got=$(run_line "-n /bin/echo" $(seq 300) 2>&1 | wc -w)
  if [[ $got != 301 ]]; then
    echo "Test many-args: expected 301 words got '$got'"
    (( errs = errs + 1 ))
  fi

  echo "==Test version"
  for v in -v --version; do
    got=$($prog $v 2>&1 | head -1)
    if [[ $got != "env2 (CWPutils) version "* ]]; then
      echo "Test version: '$v' gave '$got'"
      (( errs = errs + 1 ))
    fi
  done

  echo "==Test exec-failure-exit-code"
  run_line "-n /no/such/interpreter" >/dev/null 2>&1
  status=$?
  if [[ $status != 127 ]]; then
    echo "Test exec-failure-exit-code: expected 127 got $status"
    (( errs = errs + 1 ))
  fi

  ### parse_switches() via sample_interpreter3 (arg 1 is the #! args string) ###
  if [[ $ks == 0 && -x ./sample_interpreter3 ]]; then
    echo "==Test switches"
    got=$(./sample_interpreter3 "-ab -c=x perl -w" script 2>&1 | tr '\n' '|')
    exp="switch -a|switch -b|switch -c arg='x'|clusters=2|rest='perl -w'|"
    if [[ $got != "$exp" ]]; then
      echo "Test switches: expected '$exp' got '$got'"
      (( errs = errs + 1 ))
    fi

    echo "==Test switches-long"
    got=$(./sample_interpreter3 "--aaa -c perl" script 2>&1 | tr '\n' '|')
    exp="switch -a|switch -c|clusters=2|rest='perl'|"
    if [[ $got != "$exp" ]]; then
      echo "Test switches-long: expected '$exp' got '$got'"
      (( errs = errs + 1 ))
    fi

    echo "==Test switches-help"
    got=$(./sample_interpreter3 "--help" script 2>&1 | sed 's/ *$//' | tr '\n' '|')
    exp="Switches:|  a     : the first switch|  b     : the second switch|  c[=S] : the third switch, with an optional arg|  h     : this Help|"
    if [[ $got != "$exp" ]]; then
      echo "Test switches-help: expected '$exp' got '$got'"
      (( errs = errs + 1 ))
    fi

    echo "==Test switches-bad"
    got=$(./sample_interpreter3 "-abz perl" script 2>&1 | head -1)
    if [[ $got != *"error: unrecognized flag z" ]]; then
      echo "Test switches-bad: got '$got'"
      (( errs = errs + 1 ))
    fi
  fi

  ### shellwords (Perl-compatible splitting, split_shellwords) is the default ###
  # -C (or -s, -p, -x, which imply it) selects the classic splitter; -S is accepted; -W is wordexp.

  echo "==Test default-shellwords"
  got=$(run_line "-n /bin/echo 'two words' a\\ b \"\" x" 2>&1)
  if [[ $got != "two words a b  x /bin/true" ]]; then
    echo "Test default-shellwords: got '$got'"
    (( errs = errs + 1 ))
  fi

  echo "==Test default-comment"
  got=$(run_line "-nc /bin/echo hi # -*-Python-*-" 2>&1)
  if [[ $got != "hi /bin/true" ]]; then
    echo "Test default-comment: got '$got'"
    (( errs = errs + 1 ))
  fi

  echo "==Test default-unmatched"
  got=$(run_line "-n /bin/echo 'oops" 2>&1 | head -1)
  if [[ $got != *"error: unmatched quote" ]]; then
    echo "Test default-unmatched: got '$got'"
    (( errs = errs + 1 ))
  fi

  echo "==Test S-accepted"
  got=$(run_line "-Sn /bin/echo 'a b' x" 2>&1)
  if [[ $got != "a b x /bin/true" ]]; then
    echo "Test S-accepted: got '$got'"
    (( errs = errs + 1 ))
  fi

  # a backslash-escaped space: shellwords makes it part of the word; the classic splitter keeps the backslash
  echo "==Test C-classic"
  for f in -Cn --classic -Ln; do      # -L is the old name of -C
    got=$(run_line "$f /bin/echo a\\ b" 2>&1)
    if [[ $got != 'a\ b /bin/true' ]]; then
      echo "Test C-classic: '$f' gave '$got'"
      (( errs = errs + 1 ))
    fi
  done
  # (a long name is the only flag word here: on a kernel that splits the line only
  #  the first word is read as flags)
  got=$(run_line "--shellwords /bin/echo a\\ b" 2>&1)
  if [[ $got != 'a b /bin/true' ]]; then
    echo "Test C-classic: --shellwords gave '$got'"
    (( errs = errs + 1 ))
  fi

  ### -W: wordexp mode (a POSIX shell's rules; no command substitution) ###
  # (printf '[%s]' with no newline shows where each argument starts and ends)

  echo "==Test wordexp-basics"
  s=$'-Wn /usr/bin/printf [%s] a "b c" \'d e\' f\\ g'
  got=$(run_line "$s" 2>&1)
  if [[ $got != '[a][b c][d e][f g][/bin/true]' ]]; then
    echo "Test wordexp-basics: got '$got'"
    (( errs = errs + 1 ))
  fi

  # unlike shellwords: an unquoted $VAR is split on its spaces, a quoted one is not
  echo "==Test wordexp-variables"
  s=$'-Wn /usr/bin/printf [%s] $FOO_W "$FOO_W" \'$FOO_W\''
  got=$(FOO_W='two words' run_line "$s" 2>&1)
  if [[ $got != '[two][words][two words][$FOO_W][/bin/true]' ]]; then
    echo "Test wordexp-variables: got '$got'"
    (( errs = errs + 1 ))
  fi

  echo "==Test wordexp-tilde-arith"
  got=$(run_line '-Wn /usr/bin/printf [%s] ~ $((1+2))' 2>&1)
  if [[ $got != "[$HOME][3][/bin/true]" ]]; then
    echo "Test wordexp-tilde-arith: got '$got'"
    (( errs = errs + 1 ))
  fi

  # shell rules differ from Perl's: inside double quotes a backslash only escapes $ ` " \
  echo "==Test wordexp-shell-rules"
  s=$'-Wn /usr/bin/printf [%s] "a\\b"'
  got=$(run_line "$s" 2>&1)
  if [[ $got != '[a\b][/bin/true]' ]]; then
    echo "Test wordexp-shell-rules: got '$got'"
    (( errs = errs + 1 ))
  fi

  echo "==Test wordexp-no-commands"
  for bad in '$(echo HI)' '`echo HI`' 'x$(echo HI)y' '"$(echo HI)"'; do
    got=$(run_line "-Wn /usr/bin/printf [%s] $bad" 2>&1 | head -1)
    if [[ $got != *"command substitution is not allowed" ]]; then
      echo "Test wordexp-no-commands: '$bad' gave '$got'"
      (( errs = errs + 1 ))
    fi
  done
  # ... but a $( inside single quotes is just text, and $(( )) is arithmetic
  got=$(run_line "-Wn /usr/bin/printf [%s] '\$(echo HI)'" 2>&1)
  if [[ $got != '[$(echo HI)][/bin/true]' ]]; then
    echo "Test wordexp-no-commands: single-quoted gave '$got'"
    (( errs = errs + 1 ))
  fi

  echo "==Test wordexp-errors"
  got=$(run_line '-Wn /usr/bin/printf [%s] "oops' 2>&1 | head -1)
  # (Solaris's library accepts an unmatched quote and gives [oops]; others report an error)
  if [[ $got != *"error: wordexp: unmatched quote"* && $got != '[oops][/bin/true]' ]]; then
    echo "Test wordexp-errors: unmatched quote gave '$got'"
    (( errs = errs + 1 ))
  fi
  got=$(run_line '-Wn /usr/bin/printf [%s] (x)' 2>&1 | head -1)
  if [[ $got != *"error: wordexp: unquoted"* ]]; then
    echo "Test wordexp-errors: ( ) gave '$got'"
    (( errs = errs + 1 ))
  fi

  echo "==Test mode-conflicts"
  for f in -CS -CW -SW -WC; do
    got=$(run_line "${f}n /usr/bin/printf [%s] x" 2>&1 | head -1)
    if [[ $got != *"only one of -C"* ]]; then
      echo "Test mode-conflicts: '$f' gave '$got'"
      (( errs = errs + 1 ))
    fi
  done
  for f in -WE -Wa -Wc; do
    got=$(run_line "${f}n /usr/bin/printf [%s] x" 2>&1 | head -1)
    if [[ $got != *"is not supported with -W"* ]]; then
      echo "Test mode-conflicts: '$f' gave '$got'"
      (( errs = errs + 1 ))
    fi
  done
  got=$(run_line "--wordexp /usr/bin/printf [%s] a\\ b" 2>&1)
  if [[ $got != '[a b][/bin/true]' ]]; then
    echo "Test mode-conflicts: --wordexp gave '$got'"
    (( errs = errs + 1 ))
  fi

  echo "==Test s-implies-classic"
  got=$(run_line "-sn /bin/echo a\\ b" 2>&1)
  if [[ $got != 'a\ b /bin/true' ]]; then
    echo "Test s-implies-classic: got '$got'"
    (( errs = errs + 1 ))
  fi

  echo "==Test Ss-is-shellwords"
  got=$(run_line "-Ssn /bin/echo a\\ b" 2>&1)
  if [[ $got != "a b /bin/true" ]]; then
    echo "Test Ss-is-shellwords: got '$got'"
    (( errs = errs + 1 ))
  fi

  ### -E: expand ${NAME} environment variables (shellwords splitter only) ###
  # (printf '[%s]' with no newline shows where each argument starts and ends)

  echo "==Test expand"
  s=$'-En /usr/bin/printf [%s] ${FOO} "${FOO}" \'${FOO}\' \\${FOO} a${FOO}b'
  got=$(FOO='two words' run_line "$s" 2>&1)
  if [[ $got != '[two words][two words][${FOO}][${FOO}][atwo wordsb][/bin/true]' ]]; then
    echo "Test expand: got '$got'"
    (( errs = errs + 1 ))
  fi

  echo "==Test expand-unset"
  s=$'-En /usr/bin/printf [%s] ${NOPE_E} "${NOPE_E}" pre${NOPE_E}post'
  got=$( (unset NOPE_E; run_line "$s" 2>&1) )
  if [[ $got != '[][prepost][/bin/true]' ]]; then
    echo "Test expand-unset: got '$got'"
    (( errs = errs + 1 ))
  fi

  # a variable that is SET but empty gives an empty argument (like GNU env -S); only an unset one vanishes
  echo "==Test expand-set-but-empty"
  s=$'-En /usr/bin/printf [%s] ${EMPTY_E} x'
  got=$(EMPTY_E= run_line "$s" 2>&1)
  if [[ $got != '[][x][/bin/true]' ]]; then
    echo "Test expand-set-but-empty: got '$got'"
    (( errs = errs + 1 ))
  fi

  echo "==Test expand-off"
  s=$'-n /usr/bin/printf [%s] ${FOO}'
  got=$(FOO='two words' run_line "$s" 2>&1)
  if [[ $got != '[${FOO}][/bin/true]' ]]; then
    echo "Test expand-off: got '$got'"
    (( errs = errs + 1 ))
  fi

  echo "==Test expand-errors"
  for bad in 'a$b' '${}' '${FOO' '${1A}' 'x$'; do
    got=$(FOO=x run_line "-En /usr/bin/printf [%s] $bad" 2>&1 | head -1)
    if [[ $got != *'error: only ${NAME} expansion is supported' ]]; then
      echo "Test expand-errors: '$bad' gave '$got'"
      (( errs = errs + 1 ))
    fi
  done

  echo "==Test expand-needs-shellwords"
  for f in -ECn -ELn -Esn -Epn -Exn; do
    got=$(run_line "$f /usr/bin/printf [%s] x" 2>&1 | head -1)
    if [[ $got != *"-E needs the shellwords splitter"* ]]; then
      echo "Test expand-needs-shellwords: '$f' gave '$got'"
      (( errs = errs + 1 ))
    fi
  done
  got=$(run_line "-ESsn /usr/bin/printf [%s] x" 2>&1)
  if [[ $got != '[x][/bin/true]' ]]; then
    echo "Test expand-needs-shellwords: -ESsn gave '$got'"
    (( errs = errs + 1 ))
  fi

  # variables set by the rc file are visible to ${NAME} in the #! line (the rc file sets BOO)
  echo "==Test expand-rc-variable"
  got=$( (unset BOO; run_line "-E /usr/bin/printf [%s] \"\${BOO}\"" 2>&1) )
  if [[ $got != "[BABBLE MUTTER][/bin/true]" ]]; then
    echo "Test expand-rc-variable: got '$got'"
    (( errs = errs + 1 ))
  fi

  # interpreter-argument lines in the rc file are expanded too
  echo "==Test expand-rc-args"
  mkdir -p "$HOME/bin" && ln -sf /bin/echo "$HOME/bin/xprog"
  echo 'xprog: -I${HOME}/lib' >> ~/.$rc
  got=$(run_line "-E $HOME/bin/xprog a" 2>&1)
  if [[ $got != "-I$HOME/lib a /bin/true" ]]; then
    echo "Test expand-rc-args: got '$got'"
    (( errs = errs + 1 ))
  fi

  # the default splitter must agree with Perl's shellwords() on every short string
  if [[ -x ./splitcheck ]] && perl -MText::ParseWords -e1 2>/dev/null; then
    echo "==Test shellwords-vs-perl"
    out=$(perl t/splitcompare.pl ./splitcheck "" 5 2>&1) || {
      echo "Test shellwords-vs-perl: disagrees with Perl:"; echo "$out" | head -20
      (( errs = errs + 1 ))
    }
    out=$(SPLITCMP_WS=1 perl t/splitcompare.pl ./splitcheck "" 4 2>&1) || {
      echo "Test shellwords-vs-perl (whitespace): disagrees with Perl:"; echo "$out" | head -20
      (( errs = errs + 1 ))
    }
  fi

  # wordexp mode must agree with a real POSIX sh on every short string
  if [[ -x ./splitcheck && -x /bin/sh ]]; then
    echo "==Test wordexp-vs-sh"
    # (one shell process per string, so this is the slow test on systems where fork is
    #  expensive; length 3 already shows every kind of difference seen at length 4 or 6.
    #  SPLITCMP_WLEN=6 for a thorough run.)
    out=$(perl t/splitcompare.pl ./splitcheck W "${SPLITCMP_WLEN:-3}" 2>&1) || {
      echo "Test wordexp-vs-sh: disagrees with sh:"; echo "$out" | head -20
      (( errs = errs + 1 ))
    }
  fi

  echo "==Test no-interpreter"
  got=$(run_line "-n" 2>&1 | head -1)
  if [[ $got != *"No interpreter found" ]]; then
    echo "Test no-interpreter: got '$got'"
    (( errs = errs + 1 ))
  fi

  ### windows path (Cygwin only) ############

  if [[ $(uname -s) == CYGWIN* ]]; then
    echo "==Test w"
    # call env2 directly (not via sample_interpreter)
    set_sample_script "$PWD/${prog#./} -w perl" 'print "$0\n"'
    # Cygwin passes the script path symlink-resolved, so compare against that
    exp=$(cygpath -w "$(readlink -f "$PWD/sample_script.si")")
    got=$(./sample_script.si 2>&1)
    if [[ $got != "$exp" ]]; then
      echo "Test w: expected '$exp' got '$got'"
      (( errs = errs + 1 ))
    fi
  fi

  #################################

  # (the private HOME and its rc files are removed by the EXIT trap)

  # Look for test errors
  if [[ $errs != 0 ]]; then echo "**FAIL=$errs**"; exit 1; fi
  
  # Exit success
  exit 0
}
main ${1+"$@"}
