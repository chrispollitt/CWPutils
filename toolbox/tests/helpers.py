"""Shared helpers for the cut2 utility test suites."""

import os
import subprocess
import sys

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIR = os.path.dirname(TESTS_DIR)


def script_path(name):
    return os.path.join(TOOLS_DIR, name)


def run(name, args, stdin_text=""):
    """Run one of the cut2 utils via the current Python interpreter and
    return the completed process (text mode, stdin/stdout/stderr captured).
    """
    return subprocess.run(
        [sys.executable, script_path(name)] + list(args),
        input=stdin_text,
        capture_output=True,
        text=True,
    )
