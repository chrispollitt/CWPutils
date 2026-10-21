"""Test suite for fixperms (see ../fixperms).

fixperms is a bash script, so it is run with bash rather than the current Python.  Each test builds a scratch
tree with a deliberately messy ACL of the kind an elevated install leaves behind (a named entry for the owner
with no rights, a mask, a grant to the owner's group, a default ACL that gives new files nothing) and checks
what fixperms makes of it.  Needs getfacl/setfacl and a file system with ACLs, so it runs on Cygwin and on
Linux with the acl tools; elsewhere it is skipped.  Taking ownership from another account needs an elevated
shell and is not covered beyond the failure path (chown to an account we cannot give files to).

The rule table is tested with rules files whose patterns point into the scratch tree; the built-in rules for
real places (~/.ssh, /var/mail, ...) are only checked for being listed, and for /tmp, where the scratch trees are.
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


def run(args, rules=False):
    """Run fixperms.  The scratch trees live under the temp directory, which the built-in rules treat
    specially (/tmp keeps its modes), so the rules are off unless a test asks for them."""
    extra = [] if rules else ["--no-rules"]
    return subprocess.run(["bash", script_path("fixperms")] + extra + list(args), capture_output=True, text=True)


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

    def run_on_pty(self, args):
        """Run fixperms with stderr on a pseudo-terminal; return (result, what reached the terminal)."""
        master, slave = os.openpty()
        r = subprocess.run(["bash", script_path("fixperms"), "--no-rules"] + args,
                           stdout=subprocess.PIPE, stderr=slave, text=True)
        os.close(slave)
        out = b""
        while True:
            try:
                chunk = os.read(master, 4096)
            except OSError:
                break
            if not chunk:
                break
            out += chunk
        os.close(master)
        return r, out.decode(errors="replace")

    def test_progress_only_on_a_terminal(self):
        r = run(["-n", self.t])
        self.assertNotIn("\r", r.stderr)
        r, tty = self.run_on_pty(["-n", self.t])
        self.assertEqual(r.returncode, 0)
        self.assertRegex(tty, r"\r\x1b\[K[|/\\-] \d+ checked, \d+ would be fixed: ")
        self.assertTrue(tty.endswith("\r\x1b[K"), repr(tty[-40:]))   # cleared before the summary
        self.assertIn("checked", r.stdout)

    def test_no_progress_option(self):
        r, tty = self.run_on_pty(["-n", "-P", self.t])
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("checked", tty)

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


@unittest.skipUnless(HAVE_ACL, "needs getfacl/setfacl on a POSIX system")
class RulesTest(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="fixperms-rules-")
        self.me = subprocess.run(["id", "-un"], capture_output=True, text=True).stdout.strip()

    def tearDown(self):
        subprocess.run(["chmod", "-R", "u+rwx", self.base], capture_output=True)
        shutil.rmtree(self.base, ignore_errors=True)

    def make(self, rel, content=b"x\n", acl="u::rwx,g::rwx,o::rwx"):
        """Create a file (or a directory, if rel ends in /) under base with a loose ACL."""
        p = os.path.join(self.base, rel.rstrip("/"))
        os.makedirs(p if rel.endswith("/") else os.path.dirname(p), exist_ok=True)
        if not rel.endswith("/"):
            with open(p, "wb") as f:
                f.write(content)
        subprocess.run(["setfacl", "-s", acl, p], check=True)
        return p

    def rules(self, text):
        path = os.path.join(self.base, "rules")
        with open(path, "w") as f:
            f.write(text.replace("BASE", self.base))
        return path

    def test_rule_modes(self):
        d = self.make("tree/secret/")
        key = self.make("tree/secret/key")
        pub = self.make("tree/secret/key.pub")
        script = self.make("tree/secret/hook", b"#!/bin/sh\n")
        other = self.make("tree/other.txt")
        rf = self.rules("BASE/tree/secret/*.pub  700  644  user\n"
                        "BASE/tree/secret       700  -    user\n"
                        "BASE/tree/secret/**    700  600  user\n")
        r = run(["-R", "--rules", rf, "-v", os.path.join(self.base, "tree")], rules=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(mode(d), "700")
        self.assertEqual(mode(key), "600")  # its old x bits do not count under a rule
        self.assertEqual(mode(pub), "644")
        self.assertEqual(mode(script), "700")  # #! adds x where the rule mode has r
        self.assertEqual(mode(other), "755")  # no rule: the default, keeping x
        self.assertIn("(rule BASE/tree/secret/**)".replace("BASE", self.base), r.stdout)

    def test_keep_mode_never_loosens(self):
        private = self.make("tree/private", acl="u::rw-,g::---,o::---")
        loose = self.make("tree/loose", acl="u::r--,g::rw-,o::rw-")
        masked = self.make("tree/masked")
        if sys.platform == "cygwin":
            # Cygwin's own group "chris" is the same SID as the user, so its rights would show as the owner's.
            os.chown(masked, -1, 545)  # Users
        subprocess.run(["setfacl", "-s", "u::rw-,g::rwx,m::---,o::---", masked], check=True)
        rf = self.rules("BASE/tree/**  =  =  user\n")
        r = run(["-R", "--rules", rf, os.path.join(self.base, "tree")], rules=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(mode(private), "600")
        self.assertEqual(mode(loose), "644")  # write taken from group and others, rw for the owner
        self.assertEqual(mode(masked), "600")  # the group's rights were masked off

    def test_group_write_under_keep_rule(self):
        private = self.make("tree/private", acl="u::rw-,g::---,o::---")
        shared = self.make("tree/shared", acl="u::rw-,g::r--,o::r--")
        rf = self.rules("BASE/tree/**  =  =  user\n")
        run(["-R", "--rules", rf, "-w", os.path.join(self.base, "tree")], rules=True)
        self.assertEqual(mode(private), "600")  # -w does not open up a private file
        self.assertEqual(mode(shared), "664")

    def test_world_writable_dir_gets_tight_defaults(self):
        spool = self.make("spool/")
        rf = self.rules("BASE/spool  1777  -  user\n")
        r = run(["-R", "--rules", rf, spool], rules=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(mode(spool), "1777")
        acl = getfacl(spool)
        self.assertIn("other::rwx", acl)
        self.assertIn("default:other::r-x", acl)

    def test_base_owner(self):
        mine = self.make(f"spool/{self.me}")
        nobody = self.make("spool/no-such-account-xyz")
        rf = self.rules("BASE/spool/*  -  600  base\n")
        r = run(["-R", "--rules", rf, "-v", os.path.join(self.base, "spool")], rules=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(mode(mine), "600")
        self.assertEqual(mode(nobody), "600")
        self.assertEqual(os.lstat(nobody).st_uid, UID)  # no such account: owner left alone
        self.assertFalse([l for l in r.stdout.splitlines() if l.startswith("fix ") and "owner " in l])

    def test_bad_rules(self):
        for text in ["relative/path - - user\n", "/x 99 - user\n", "/x - -\n", "/x - - no-such-account-xyz\n"]:
            r = run(["--rules", self.rules(text), "--list-rules"], rules=True)
            self.assertEqual(r.returncode, 2, text)

    def test_list_rules(self):
        rf = self.rules("/srv/www/**  -  -  user  # comment\n")
        r = run(["--rules", rf, "--list-rules"], rules=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertIn("/srv/www/**", lines[1])  # rules files come first
        self.assertIn("~/.ssh", r.stdout)
        self.assertIn("/var/mail/*", r.stdout)
        r = run(["--no-rules", "--list-rules"], rules=True)
        self.assertIn("no rules", r.stdout)

    def test_builtin_tmp_rule_keeps_modes(self):
        if not os.path.abspath(self.base).startswith("/tmp/"):
            self.skipTest("temp directory is not under /tmp")
        private = self.make("tree/private", acl="u::rw-,g::---,o::---")
        loose = self.make("tree/loose", acl="u::rw-,g::rw-,o::rw-")
        r = run([os.path.join(self.base, "tree")], rules=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(mode(private), "600")
        self.assertEqual(mode(loose), "644")


def winpath(p):
    return subprocess.run(["cygpath", "-w", p], capture_output=True, text=True).stdout.strip()


def icacls(p):
    return subprocess.run(["icacls", winpath(p)], capture_output=True, text=True).stdout


@unittest.skipUnless(sys.platform == "cygwin" and shutil.which("icacls"), "inheritance is Cygwin-only")
class InheritTest(unittest.TestCase):
    """The fast path: whole subtrees reset by inheritance with icacls."""

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="fixperms-inherit-")
        self.t = os.path.join(self.base, "tree")
        for d in ["a/sub", "b/deep"]:
            os.makedirs(os.path.join(self.t, d))
        self.plain = os.path.join(self.t, "a", "sub", "plain.txt")
        self.script = os.path.join(self.t, "a", "sub", "run.sh")
        for p, data in [(self.plain, "x\n"), (self.script, "#!/bin/sh\n")]:
            with open(p, "w") as f:
                f.write(data)
            subprocess.run(["setfacl", "-s", FILE_MESS, p], check=True)
        self.outside = os.path.join(self.base, "outside")
        os.makedirs(os.path.join(self.outside, "inner"))
        subprocess.run(["setfacl", "-s", "u::rwx,g::---,o::---", self.outside], check=True)

    def tearDown(self):
        subprocess.run(["icacls", winpath(self.base), "/grant", "*S-1-3-4:(OI)(CI)(F)", "/T", "/C", "/Q"],
                       capture_output=True)
        subprocess.run(["chmod", "-R", "u+rwx", self.base], capture_output=True)
        shutil.rmtree(self.base, ignore_errors=True)

    def test_subtree_inherits(self):
        r = run(["-v", self.t])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("reset by inheritance: ", r.stdout)
        self.assertEqual(mode(self.plain), "644")
        self.assertEqual(mode(self.script), "755")
        self.assertIn("(I)", icacls(self.plain))  # inherited, not an explicit ACL
        self.assertEqual(getfacl(self.plain), ["user::rw-", "group::r--", "other::r--"])
        # An entry-by-entry check afterwards finds nothing to do.
        r = run(["-I", self.t])
        self.assertIn(" 0 fixed", r.stdout)

    def test_no_inherit_option(self):
        r = run(["-I", "-v", self.t])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("reset by inheritance", r.stdout)
        self.assertNotIn("(I)", icacls(self.plain))
        self.assertEqual(mode(self.plain), "644")

    def test_dry_run_does_not_inherit(self):
        r = run(["-n", self.t])
        self.assertNotIn("reset by inheritance", r.stdout)
        self.assertIn("mask::", "".join(getfacl(self.plain)))

    def test_junction_is_not_followed(self):
        junction = os.path.join(self.t, "a", "sub", "junction")
        mk = subprocess.run(["cmd", "/c", "mklink", "/J", winpath(junction), winpath(self.outside)],
                            capture_output=True, text=True)
        if mk.returncode != 0:
            self.skipTest("cannot create a junction: " + mk.stdout + mk.stderr)
        before = (mode(self.outside), icacls(self.outside), icacls(os.path.join(self.outside, "inner")))
        r = run(["-v", self.t])
        self.assertEqual(r.returncode, 0, r.stderr)
        after = (mode(self.outside), icacls(self.outside), icacls(os.path.join(self.outside, "inner")))
        self.assertEqual(after, before)
        # The directories holding the junction were done entry by entry; b was inherited.
        sub = os.path.join(self.t, "a", "sub")
        self.assertNotIn(f"reset by inheritance: {sub} ", r.stdout)
        self.assertIn("reset by inheritance: " + os.path.join(self.t, "b") + " ", r.stdout)
        self.assertEqual(mode(self.plain), "644")
        self.assertEqual(mode(self.script), "755")


if __name__ == "__main__":
    unittest.main()
