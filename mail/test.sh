#!/bin/bash

# Ensure this script is run from the directory containing mailx.py and sendmail.py
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
MAILX_PY="$SCRIPT_DIR/mailx.py"
SENDMAIL_PY="$SCRIPT_DIR/sendmail.py"

if [ ! -f "$MAILX_PY" ] || [ ! -f "$SENDMAIL_PY" ]; then
    echo "Error: mailx.py or sendmail.py not found in $SCRIPT_DIR"
    exit 1
fi

echo "--- Starting test.sh ---"

# 1. Set environment variables for sendmail.py to use in --dry-run mode
# These are needed because sendmail.py still validates presence of some args
# or uses them to construct the command it would have run.
#export SENDMAILPY_DRY_RUN="true"
export SENDMAILPY_SSH_HOST="cmpi"
export SENDMAILPY_SSH_USER="chris"
#export SENDMAILPY_REMOTE_SENDMAIL_PATH="/usr/sbin/dummy-remote-sendmail"
# Optional: set SENDMAILPY_VERBOSE="true" to see sendmail.py's own verbose output

# 2. Define test parameters
TEST_RECIPIENT="chris.pollitt@gmail.com"
TEST_SUBJECT="Test email from test.sh with sendmail.py dry run"
TEST_BODY="This is a test message from test.sh, expecting sendmail.py to dry-run."
TEST_ATTACHMENT_FILE="$SCRIPT_DIR/test.sh" # Attaching itself

# 3. Construct and run the mailx.py command
echo "Test Body: $TEST_BODY" | "$MAILX_PY" \
    --sendmail-path "$SENDMAIL_PY" \
    -s "${TEST_SUBJECT}" \
    -a "${TEST_ATTACHMENT_FILE}" \
    -v \
    "${TEST_RECIPIENT}"

# The -v for mailx.py will make mailx.py verbose.
# sendmail.py will be in dry-run mode due to SENDMAILPY_DRY_RUN=true.
# If you also want sendmail.py to be verbose about its own operations during dry run,
# you can add `export SENDMAILPY_VERBOSE="true"` above.

# 4. Unset environment variables (optional, good practice)
unset SENDMAILPY_DRY_RUN
unset SENDMAILPY_SSH_HOST
unset SENDMAILPY_SSH_USER
unset SENDMAILPY_REMOTE_SENDMAIL_PATH
# unset SENDMAILPY_VERBOSE

echo "--- test.sh finished ---"
# Add checks here if you want to verify output, e.g., using grep
# For example:
# OUTPUT=$(echo "Test Body" | "$MAILX_PY" ... )
# echo "$OUTPUT"
# if echo "$OUTPUT" | grep -q "\[DRY RUN\]"; then
#   echo "Test PASSED: Dry run detected."
# else
#   echo "Test FAILED: Dry run output not detected."
#   exit 1
# fi
