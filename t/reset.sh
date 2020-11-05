#!/bin/bash

read -p "Are you sure? " ans
if [[ $ans == YES ]]; then
  echo "OK then"
  for i in 0 1 2 3 4 5 6 7 s1 s2 s3 sp; do
    if [[ -f out$i && -s out$i ]]; then
      mv out$i exp$i
    else
      echo "Out empty or not found: out$i"
      exit 1
    fi
  done
else
  echo "Didn't think so"
fi
