"""Test suite for tcping (see ../tcping).

Success-path tests run a throwaway local TCP server on 127.0.0.1 so
they don't depend on any real network access. Failure-path tests use
timeouts against a non-routable address / a non-resolving hostname so
they fail deterministically without depending on how the local
network stack signals refusal (which varies by OS/firewall).
"""

import os
import re
import socket
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import run

# RFC 5737 TEST-NET-3: reserved, non-routable, safe to dial and expect
# either a timeout or an unreachable error.
UNROUTABLE_HOST = "203.0.113.1"


def start_local_server(banner=None):
    """Start a background TCP server on an ephemeral localhost port.

    Accepts exactly one connection, optionally sends `banner`, then
    closes it. Returns the bound port number.
    """
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def serve():
        try:
            srv.settimeout(5)
            conn, _ = srv.accept()
            try:
                if banner is not None:
                    conn.sendall(banner.encode("utf-8"))
            finally:
                conn.close()
        except OSError:
            pass
        finally:
            srv.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return port


class TestSuccessfulConnect(unittest.TestCase):
    def test_reports_elapsed_time(self):
        port = start_local_server()
        r = run("tcping", ["127.0.0.1", str(port), "-b", "0.3"])
        self.assertEqual(r.returncode, 0)
        self.assertRegex(r.stdout, r"127\.0\.0\.1:\d+ connected in \d+\.\d+ ms")

    def test_no_banner_reports_none(self):
        port = start_local_server()
        r = run("tcping", ["127.0.0.1", str(port), "-b", "0.3"])
        self.assertEqual(r.returncode, 0)
        self.assertIn("banner: (none within 0.3s)", r.stdout)

    def test_detects_welcome_banner(self):
        port = start_local_server(banner="220 hello service ready\r\n")
        r = run("tcping", ["127.0.0.1", str(port), "-b", "1"])
        self.assertEqual(r.returncode, 0)
        self.assertIn("banner: 220 hello service ready", r.stdout)

    def test_no_banner_flag_skips_check_entirely(self):
        port = start_local_server(banner="220 hello service ready\r\n")
        r = run("tcping", ["127.0.0.1", str(port), "--no-banner"])
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("banner:", r.stdout)
        self.assertIn("connected in", r.stdout)


class TestFailureReporting(unittest.TestCase):
    def test_unreachable_host_reports_failure_and_exit_1(self):
        r = run("tcping", [UNROUTABLE_HOST, "80", "-w", "0.5"])
        self.assertEqual(r.returncode, 1)
        self.assertRegex(r.stderr, r"failed after \d+\.\d+ ms")

    def test_dns_failure_reports_failure_and_exit_1(self):
        r = run("tcping", ["this.host.does.not.exist.invalid", "80", "-w", "2"])
        self.assertEqual(r.returncode, 1)
        self.assertIn("failed after", r.stderr)


class TestUsage(unittest.TestCase):
    def test_missing_args_is_usage_error(self):
        r = run("tcping", [])
        self.assertEqual(r.returncode, 2)

    def test_missing_port_is_usage_error(self):
        r = run("tcping", ["127.0.0.1"])
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
