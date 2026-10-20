"""Test suite for fixperms (see ../fixperms).

fixperms is a bash script, so it is run with bash rather than the current Python.  Each test builds a scratch
tree with a deliberately messy ACL of the kind an elevated install leaves behind (a named entry for the owner
with no rights, a mask, a grant to the owner's group, a default ACL that gives new files nothing) and checks
what fixperms makes of it.  Needs getfacl/setfacl and a file system with ACLs, so it runs on Cygwin and on
Linux with the acl tools; elsewhere it is skipped.  Taking ownership from another account needs an elevated
shell and is not covered beyond the failure path (chown to an account we cannot give files to).
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import script_path

UID = os.getuid() if hasattr(os, "getuid") else None
GID = os.getgid() if hasattr(os, "getgid") else None
HAVE_ACL = os.name == "posix" and bool(shutil.which("setfacl")) and bool(shutil.which("getfacl"))

DIR_MESS = (f"u::r-x,u:{UID}:---,g::---,g:{GID}:rwx,m::rwx,o::r-x,"
            f"d:u::---,d:g::---,d:g:{GID}:rwx,d:m::rwx,d:o::---")
FILE_MESS = f"u::r--,u:{UID}:---,g::---,g:{GID}:rwx,m::rw-,o::r--"


def run(args):
    return subprocess.run(["bash", script_path("fixperms")] + list(args), capture_output=True, text=True)


def getfacl(path):
    out = subprocess.run(["getfacl", "-c", "--", path], capture_output=True, text=True).stdout
    return [line.split("\t")[0] for line in out.splitlines() if line]


def mode(path):
    return oct(os.lstat(path).st_mode & 0o7777)[2:]


@unittest.skipUnless(HAVE_ACL, "needs getfacl/setfacl on a POSIX system")
class FixpermsTest(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="fixperms-test-")
        self.t = os.path.join(self.base, "tree")
        d = os.path.join(self.t, "dir with spaces")
        os.makedirs(os.path.join(d, "sub"))
        os.makedirs(os.path.join(self.t, "unread"))
        self.files = {
            "plain": os.path.join(d, "a.py"),
            "script": os.path.join(d, "run.sh"),
            "dll": os.path.join(d, "lib.dll"),
            "deep": os.path.join(d, "sub", "f.txt"),
            "hidden": os.path.join(self.t, "unread", "inner.txt"),
        }
        content = {"plain": b"print(1)\n", "script": b"#!/bin/sh\necho hi\n", "dll": b"MZ\x90\x00rest",
                   "deep": b"x\n", "hidden": b"y\n"}
        for k, p in self.files.items():
            with open(p, "wb") as f:
                f.write(content[k])
        self.outside = os.path.join(self.base, "outside")
        with open(self.outside, "w") as f:
            f.write("outside\n")
        os.chmod(self.outside, 0o600)
        os.symlink(self.outside, os.path.join(self.t, "link"))
        self.mess(self.t)
        # A directory nobody may list, not even the owner.
        subprocess.run(["setfacl", "-s", "u::---,g::---,o::---", os.path.join(self.t, "unread")], check=True)

    def mess(self, top):
        files, dirs = [], []
        for root, dn, fn in os.walk(top):
            dirs += [os.path.join(root, x) for x in dn]
            files += [os.path.join(root, x) for x in fn if not os.path.islink(os.path.join(root, x))]
        if files:
            subprocess.run(["setfacl", "-s", FILE_MESS, "--"] + files, check=True)
        subprocess.run(["setfacl", "-s", DIR_MESS, "--"] + dirs[::-1] + [top], check=True)

    def tearDown(self):
        subprocess.run(["chmod", "-R", "u+rwx", self.base], capture_output=True)
        shutil.rmtree(self.base, ignore_errors=True)

    def snapshot(self):
        return {p: (mode(p), tuple(getfacl(p))) for p in [self.t, *self.files.values()]
                if os.access(os.path.dirname(p), os.X_OK)}

    def test_dry_run_changes_nothing(self):
        before = self.snapshot()
        r = run(["-n", self.t])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("dry run", r.stdout)
        self.assertIn("would fix", r.stdout)
        self.assertIn("(ACL cleaned)", r.stdout)
        self.assertIn("not checked", r.stdout)  # the unreadable directory
        self.assertEqual(self.snapshot(), before)

    def test_fixes_tree(self):
        outside_before = (mode(self.outside), getfacl(self.outside))
        r = run([self.t])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(getfacl(self.t), ["user::rwx", "group::r-x", "other::r-x",
                                           "default:user::rwx", "default:group::r-x", "default:other::r-x"])
        self.assertEqual(getfacl(self.files["plain"]), ["user::rw-", "group::r--", "other::r--"])
        self.assertEqual(mode(self.files["plain"]), "644")
        self.assertEqual(mode(self.files["deep"]), "644")
        self.assertEqual(mode(self.files["hidden"]), "644")  # under the dir nobody could list
        self.assertEqual(mode(self.files["script"]), "755")  # #! line
        self.assertEqual(mode(self.files["dll"]), "755")  # MZ header
        self.assertEqual(mode(os.path.join(self.t, "unread")), "755")
        # The symlink was not followed out of the tree.
        self.assertEqual((mode(self.outside), getfacl(self.outside)), outside_before)

    def test_new_files_inherit_clean_acl(self):
        run([self.t])
        new = os.path.join(self.t, "dir with spaces", "new.txt")
        with open(new, "w"):
            pass
        self.assertEqual(getfacl(new), ["user::rw-", "group::r--", "other::r--"])

    def test_second_run_is_a_no_op(self):
        run([self.t])
        r = run(["-v", self.t])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(" 0 fixed", r.stdout)
        self.assertNotIn("fix ", r.stdout.replace("fixperms:", ""))

    def test_no_recurse(self):
        r = run(["-d", self.t])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(mode(self.t), "755")
        self.assertIn("mask::rw-", getfacl(self.files["plain"]))  # contents untouched

    def test_keeps_x_unless_exec_by_content(self):
        p = self.files["plain"]
        subprocess.run(["setfacl", "-s", "u::rwx,g::r-x,o::r-x", p], check=True)
        run([self.t])
        self.assertEqual(mode(p), "755")
        subprocess.run(["setfacl", "-s", "u::rwx,g::r-x,o::r-x", p], check=True)
        run(["-x", self.t])
        self.assertEqual(mode(p), "644")
        self.assertEqual(mode(self.files["script"]), "755")

    def test_group_write(self):
        run(["-w", self.t])
        self.assertEqual(mode(self.t), "775")
        self.assertEqual(mode(self.files["plain"]), "664")
        self.assertEqual(mode(self.files["script"]), "775")

    def test_bundled_flags(self):
        r = run(["-nvd", self.t])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("1 checked", r.stdout)

    def test_refuses_root_and_top_level(self):
        for p in ["/", "/usr", "/tmp/"]:
            r = run(["-n", p])
            self.assertEqual(r.returncode, 1, p)
            self.assertIn("refusing", r.stderr)

    def test_missing_path(self):
        r = run([os.path.join(self.base, "nope")])
        self.assertEqual(r.returncode, 1)
        self.assertIn("no such file", r.stderr)

    def test_usage_errors(self):
        self.assertEqual(run([]).returncode, 2)
        self.assertEqual(run(["--bogus", self.t]).returncode, 2)
        self.assertEqual(run(["--user"]).returncode, 2)
        r = run(["--help"])
        self.assertEqual(r.returncode, 0)
        self.assertIn("--dry-run", r.stdout)

    @unittest.skipUnless(sys.platform == "cygwin", "SYSTEM account is Cygwin-only")
    @unittest.skipIf(sys.platform == "cygwin" and 544 in os.getgroups(), "elevated: the chown would succeed")
    def test_failed_chown_reports_and_continues(self):
        r = run(["--user", "SYSTEM", self.files["plain"], self.files["deep"]])
        self.assertEqual(r.returncode, 1)
        self.assertIn("chown", r.stderr)
        self.assertIn("elevated", r.stderr)
        # It did not touch the ACL of a file it could not take over.
        self.assertIn("mask::rw-", getfacl(self.files["plain"]))


if __name__ == "__main__":
    unittest.main()
