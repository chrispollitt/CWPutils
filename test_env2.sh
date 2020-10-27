#!/bin/bash

# set vars
me="$0"
prog="${1%.exe}"
prog="${prog##*/}"
rc="${prog}rc"
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

# Run Test 0 - [no args]
echo "==Test 0"
./$prog >& t/out0
diff t/out0 t/exp0
[[ $? != 0 ]] && (( errs = errs + 1 ))

# Run Test 1 - help
echo "==Test 1"
./$prog -h >& t/out1
diff t/out1 t/exp1
[[ $? != 0 ]] && (( errs = errs + 1 ))

# Run Test 2 - debug, emit, default delim
echo "==Test 2"
./$prog '-d -ef perl -le ~~ "" "hello\\ two"' '$"=q/" "/;print qq/ARGV="@ARGV" FOO="$ENV{FOO}"/' 'goodbye' >& t/out2
diff t/out2 t/exp2
[[ $? != 0 ]] && (( errs = errs + 1 ))

# Run Test 3 strip, norc, custom delim
echo "==Test 3"
./$prog '-snf=@@ perl -le @@ "hello\\ three"' '$"=q/" "/;print qq/ARGV="@ARGV" FOO="$ENV{FOO}"/' 'goodbye' >& t/out3
diff t/out3 t/exp3
[[ $? != 0 ]] && (( errs = errs + 1 ))

# Run Test 4 - [no flags]
echo "==Test 4"
./$prog 'perl -le' '$"=q/" "/;print qq/ARGV="@ARGV" FAR="$ENV{FAR}"/' 'hello four' 'goodbye' >& t/out4
diff t/out4 t/exp4
[[ $? != 0 ]] && (( errs = errs + 1 ))

# Run Test 5 - bash
echo "==Test 5"
./$prog '-d bash -c' 'echo "Hi from 5"' >& t/out5
diff t/out5 t/exp5
[[ $? != 0 ]] && (( errs = errs + 1 ))

# Run Test 6 - norc bash
echo "==Test 6"
./$prog '-dn bash -x -c' 'echo "Hi from 6"' >& t/out6
diff t/out6 t/exp6
[[ $? != 0 ]] && (( errs = errs + 1 ))

#################################

# restore orig rc file
[[ -f ~/.$rc-ORIG ]] && mv -f ~/.$rc-ORIG ~/.$rc

# Look for test errors
if [[ $errs != 0 ]]; then echo "**FAIL=$errs**"; exit 1; fi

# Exit success
exit 0
