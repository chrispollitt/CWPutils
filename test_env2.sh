#!/bin/bash

# set vars
me="$0"
prog="${1%.exe}"
rc="${prog}rc"
rc="${rc##*/}"
errs=0

# test prog
if [[ -z $prog || ! -x $prog ]]; then
  echo "Error: prog not found: '$1'"
  exit 1
fi

# copy test rc file
[[ -f ~/.$rc ]] && mv -f ~/.$rc ~/.$rc-ORIG
cp t/$rc ~/.$rc

#############################################

### no args OR help ######

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
$prog '-d -ef perl -le ~~ "" "hello\\ two"' '$"=q/" "/;print qq/ARGV="@ARGV" FOO="$ENV{FOO}"/' 'goodbye' >& t/out2
diff t/out2 t/exp2
[[ $? != 0 ]] && (( errs = errs + 1 ))

# Run Test 3 - +strip
echo "==Test 3"
$prog '-defs perl -le ~~ "hello\\ three"' '$"=q/" "/;print qq/ARGV="@ARGV" FOO="$ENV{FOO}"/' 'goodbye' >& t/out3
diff t/out3 t/exp3
[[ $? != 0 ]] && (( errs = errs + 1 ))

# Run Test 4 - [no flags]
echo "==Test 4"
$prog 'perl -le' '$"=q/" "/;print qq/ARGV="@ARGV" FAR="$ENV{FAR}"/' 'hello four' 'goodbye' >& t/out4
diff t/out4 t/exp4
[[ $? != 0 ]] && (( errs = errs + 1 ))

### bash #################

# Run Test 5 - debug, expand
echo "==Test 5"
$prog '-dxf   bash -c ~~ "tab\ttab"' 'echo -E "Hi from 5 $0"' >& t/out5
diff t/out5 t/exp5
[[ $? != 0 ]] && (( errs = errs + 1 ))

# Run Test 6 - debug, norc 
echo "==Test 6"
$prog '-dnf  bash -x -c ~~ "tab\ttab"' 'echo -E "Hi from 6 $0"' >& t/out6
diff t/out6 t/exp6
[[ $? != 0 ]] && (( errs = errs + 1 ))

# Run Test 7 - debug, norc, comment
echo "==Test 7"
$prog '-dnc bash -x -c # comment' 'echo "Hi from 7"' >& t/out7
diff t/out7 t/exp7
[[ $? != 0 ]] && (( errs = errs + 1 ))

#################################

# restore orig rc file
[[ -f ~/.$rc-ORIG ]] && mv -f ~/.$rc-ORIG ~/.$rc

# Look for test errors
if [[ $errs != 0 ]]; then echo "**FAIL=$errs**"; exit 1; fi

# Exit success
exit 0
