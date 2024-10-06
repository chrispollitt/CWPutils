#!/bin/bash

cd t

# Initialize counters for passed and failed tests
pass_count=0
fail_count=0

# Function to run a test
run_test() {
  local test_num=$1
  local test_cmd=$2
  local expected_file="test${test_num}.expected"
  local output_file="test${test_num}.out"

  echo "Running Test $test_num: $test_cmd"

#  echo -e "\033]46;${output_file}\007"
  eval $test_cmd
#	echo -e "\033]46;\007"

  # Compare the output with the expected output
  if diff -q "$output_file" "$expected_file" > /dev/null; then
    echo "Test $test_num PASSED"
    ((pass_count++))
  else
    echo "Test $test_num FAILED"
    ((fail_count++))
  fi
  echo "----------------------------------------"
}

# Test 1: Basic usage with a text string
run_test 1 'bidet "Hello, world!"'

# Test 2: Basic usage with a text file
echo "This is a test file." > testfile.txt
run_test 2 'bidet testfile.txt'

# Test 3: Piped input
run_test 3 'echo "This is piped text" | bidet -'

# Test 4: Using options --ansi and --preserve
run_test 4 'bidet --ansi --preserve "This is a preserved ANSI text"'

# Test 5: Using shortened options -b for background, -c for colour
run_test 5 'bidet -b green -c yellow "Text with green background and yellow text"'

# Test 6: Using random values for colour and font
run_test 6 'bidet -c random -f random "Random font and random colour"'

# Test 7: Rotating text by 90 degrees
run_test 7 'bidet --rotate "Rotated text"'

# Test 8: Setting specific width and font size
run_test 8 'bidet --width=30 --size=50 "Text with width 30 and font size 50"'

# Test 9: Listing available fonts
run_test 9 'bidet -f list'

# Test 10: Listing available colours
run_test 10 'bidet -c list'

# Test 11: Showing help
run_test 11 'bidet --help'

# Test 12: Showing version
run_test 12 'bidet --version'

# Cleanup
echo "Cleaning up the test file."
rm -f testfile.txt

# Summary of results
echo "----------------------------------------"
echo "Test Summary:"
echo "Passed: $pass_count"
echo "Failed: $fail_count"

if [ $fail_count -eq 0 ]; then
  echo "All tests PASSED!"
else
  echo "Some tests FAILED. Please check the output files for details."
fi

# xterm -l -lf filename 