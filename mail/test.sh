#!/bin/bash
echo "This is a test message" | mailx -a test.sh -s "Test email" chris.pollitt@gmail.com
