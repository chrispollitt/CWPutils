#!/bin/bash

ks=$(perl -lne '/KERNEL_SPLIT (\d+)/ and print $1' ../config.hh)

read -p "Are you sure? " ans
if [[ $ans == YES ]]; then
  rm -f *~
  echo "OK then"
  for i in exp*; do
    i=${i#exp}
    if [[ -f out$i && -s out$i ]]; then
      mv out$i exp$i
    else
      echo "Out empty or not found: out$i"
      exit 1
    fi
  done
  read -p "Copy to ks$ks? " ans
  if [[ $ans == YES ]]; then
    cp exp* ks$ks
  fi
else
  echo "Didn't think so"
fi
