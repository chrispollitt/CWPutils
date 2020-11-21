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
  
  echo "#!$inter$iargs" > sample_script.si
  if [[ -n $body ]]; then
    echo "$body" >> sample_script.si
  else
    cat sample_script.si.template >> sample_script.si
  fi
  chmod 755 sample_script.si
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
  
  # copy test rc file
  [[ -f ~/.$rc ]] && mv -f ~/.$rc ~/.$rc-ORIG
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
  set_sample_script '-dnf bash -x ~~ "tab\ttab"' 'echo -E "Hi from 6 $1"'
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
    
  #################################
  
  # restore orig rc file
  [[ -f ~/.$rc-ORIG ]] && mv -f ~/.$rc-ORIG ~/.$rc
  rm ~/.sample_interpreterrc
  
  # Look for test errors
  if [[ $errs != 0 ]]; then echo "**FAIL=$errs**"; exit 1; fi
  
  # Exit success
  exit 0
}
main ${1+"$@"}
