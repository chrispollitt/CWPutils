"""Test suite for gitcheck (see ../gitcheck).

gitcheck is a bash script, so it is run with bash rather than the current Python.  Each test builds a scratch
directory of clones of a local bare "remote", so nothing touches the network.  A fake `gh` that always fails is
put first on PATH, so the GitHub lookup is skipped and the output does not depend on the real account.
Interactive answers are fed through GITCHECK_TTY instead of the terminal; an empty answers file makes any
unexpected prompt fail the run.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import script_path

HAVE_GIT = bool(shutil.which("git")) and bool(shutil.which("bash"))

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com",
    "GIT_CONFIG_NOSYSTEM": "1",
}


@unittest.skipUnless(HAVE_GIT, "needs git and bash")
class GitcheckTest(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="gitcheck-test-")
        self.top = os.path.join(self.base, "clones")
        os.makedirs(self.top)
        bindir = os.path.join(self.base, "bin")
        os.makedirs(bindir)
        with open(os.path.join(bindir, "gh"), "w") as f:
            f.write("#!/bin/sh\nexit 1\n")
        os.chmod(os.path.join(bindir, "gh"), 0o755)
        home = os.path.join(self.base, "home")
        os.makedirs(home)
        self.env = dict(os.environ, **GIT_ENV, HOME=home,
                        PATH=bindir + os.pathsep + os.environ.get("PATH", ""))
        self.env.pop("GIT_DIR", None)
        self.answers = os.path.join(self.base, "answers")
        self.remote = os.path.join(self.base, "remote.git")
        self.git("init", "-q", "--bare", self.remote, cwd=self.base)
        self.repo = os.path.join(self.top, "proj")
        self.git("clone", "-q", self.remote, self.repo, cwd=self.base)
        self.git("checkout", "-q", "-b", "main")
        self.write("README", "hello\n")
        self.git("add", "README")
        self.git("commit", "-q", "-m", "init")
        self.git("push", "-q", "-u", "origin", "main")

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def git(self, *args, cwd=None):
        r = subprocess.run(["git"] + list(args), cwd=cwd or self.repo, env=self.env,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def write(self, name, text):
        path = os.path.join(self.repo, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def run_gitcheck(self, *args, answers=None):
        with open(self.answers, "w") as f:
            f.write("".join(a + "\n" for a in answers or []))
        env = dict(self.env, GITCHECK_TTY=self.answers)
        return subprocess.run(["bash", script_path("gitcheck")] + list(args) + [self.top],
                              env=env, capture_output=True, text=True)

    # --- usage ---------------------------------------------------------------

    def test_no_options_is_usage_error(self):
        r = subprocess.run(["bash", script_path("gitcheck")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("Usage:", r.stdout)

    def test_interactive_alone_is_usage_error(self):
        r = subprocess.run(["bash", script_path("gitcheck"), "-i"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("-i needs -c and/or -u", r.stderr)

    def test_help_and_version(self):
        r = subprocess.run(["bash", script_path("gitcheck"), "-h"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn("-i", r.stdout)
        r = subprocess.run(["bash", script_path("gitcheck"), "-V"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertRegex(r.stdout, r"^gitcheck \d+\.\d+")

    def test_bad_directory(self):
        r = subprocess.run(["bash", script_path("gitcheck"), "-c", os.path.join(self.base, "nope")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)

    # --- report --------------------------------------------------------------

    def test_clean_repo(self):
        r = self.run_gitcheck("-c")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Processing proj...", r.stdout)
        self.assertIn("Uncommitted changes: No", r.stdout)
        self.assertIn("Unpushed commits: No", r.stdout)

    def test_non_repo_listed(self):
        os.makedirs(os.path.join(self.top, "plain"))
        r = self.run_gitcheck("-u")
        self.assertIn("plain: Not a Git repository", r.stdout)

    def test_builtin_ignored_names(self):
        for name in ("tmp", "BAK", "Old", "notes.bak", "keep", "plain"):
            os.makedirs(os.path.join(self.top, name))
        os.rename(self.repo, os.path.join(self.top, "backup"))   # a repo is reported whatever its name
        r = self.run_gitcheck("-u")
        for name in ("tmp", "BAK", "Old", "notes.bak"):
            self.assertNotIn(name + ":", r.stdout)
        self.assertIn("keep: Not a Git repository", r.stdout)
        self.assertIn("plain: Not a Git repository", r.stdout)
        self.assertIn("Processing backup...", r.stdout)

    def test_ignore_file(self):
        for name in ("scratch1", "plain", "keep"):
            os.makedirs(os.path.join(self.top, name))
        conf = os.path.join(self.env["HOME"], ".config", "gitcheck")
        os.makedirs(conf)
        top = subprocess.run(["bash", "-c", 'cd "$1" && pwd -P', "_", self.top],
                             capture_output=True, text=True).stdout.strip()
        with open(os.path.join(conf, "ignore"), "w") as f:
            f.write(f"# comment\n\nscratch*\n{top}/plain\n/elsewhere/keep\n")
        r = self.run_gitcheck("-u")
        self.assertNotIn("scratch1:", r.stdout)
        self.assertNotIn("plain:", r.stdout)
        self.assertIn("keep: Not a Git repository", r.stdout)

    def test_interactive_ignore_is_remembered(self):
        os.makedirs(os.path.join(self.top, "odd[1]"))
        os.makedirs(os.path.join(self.top, "later"))
        r = self.run_gitcheck("-c", "-i", answers=["s", "i"])   # sorted: later, odd[1]
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(os.path.join(self.env["HOME"], ".config", "gitcheck", "ignore")) as f:
            self.assertTrue(f.read().endswith("/odd\\[1\\]\n"))
        r = self.run_gitcheck("-c", "-i", answers=["s"])          # only 'later' is asked about
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("odd[1]:", r.stdout)
        self.assertIn("later: Not a Git repository", r.stdout)

    def make_plain_dir(self, name, files):
        d = os.path.join(self.top, name)
        os.makedirs(d)
        for f in files:
            with open(os.path.join(d, f), "w") as fh:
                fh.write("x\n")
        return d

    def test_interactive_new_repo(self):
        d = self.make_plain_dir("newproj", ["a.txt", "b.log"])
        # git init; add a.txt, ignore b.log; commit staged only; message
        r = self.run_gitcheck("-c", "-i", answers=["g", "a", "i", "s", "first"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        log = self.git("log", "--name-only", "--format=%s", cwd=d).split()
        self.assertEqual(log[0], "first")
        self.assertEqual(sorted(log[1:]), [".gitignore", "a.txt"])
        with open(os.path.join(d, ".gitignore")) as f:
            self.assertEqual(f.read(), "/b.log\n")

    def test_interactive_new_repo_on_github(self):
        self.fake_gh(["proj"])
        d = self.make_plain_dir("newproj", ["a.txt"])
        r = self.run_gitcheck("-c", "-i", answers=["g", "a", "a", "first", "p"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(os.path.join(self.base, "gh-create.log")) as f:
            self.assertEqual(f.read().split()[:4], ["repo", "create", "newproj", "--private"])
        self.assertEqual(self.git("log", "--format=%s", cwd=os.path.join(self.base, "created.git")).strip(),
                         "first")
        self.assertEqual(self.git("rev-parse", "--abbrev-ref", "@{u}", cwd=d).strip(),
                         "origin/" + self.git("branch", "--show-current", cwd=d).strip())

    def test_new_repo_not_created_if_name_taken(self):
        self.fake_gh(["proj", "newproj"])
        self.make_plain_dir("newproj", ["a.txt"])
        r = self.run_gitcheck("-c", "-i", answers=["g", "s", "n"])   # no GitHub prompt after this
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("tester/newproj already exists on GitHub", r.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.base, "gh-create.log")))

    # --- unpulled commits and potential conflicts -----------------------------

    def push_from_other(self, files, fetch=True):
        """Commit `files` ({name: text}) in a second clone and push them, then fetch in the first."""
        other = os.path.join(self.base, "other")
        if not os.path.exists(other):
            self.git("clone", "-q", "-b", "main", self.remote, other, cwd=self.base)
        for name, text in files.items():
            with open(os.path.join(other, name), "w") as f:
                f.write(text)
            self.git("add", name, cwd=other)
        self.git("commit", "-q", "-m", "upstream " + " ".join(files), cwd=other)
        self.git("push", "-q", cwd=other)
        if fetch:
            self.git("fetch", "-q")

    def commit_local(self, name, text):
        self.write(name, text)
        self.git("add", name)
        self.git("commit", "-q", "-m", "local " + name)

    def test_unpulled(self):
        self.push_from_other({"a.txt": "1\n"})
        self.push_from_other({"b.txt": "2\n"})
        r = self.run_gitcheck("-c")
        self.assertIn("Unpulled commits: Yes", r.stdout)
        self.assertIn("└─ main: 2 (from origin/main)", r.stdout)
        self.assertNotIn("⚠", r.stdout)
        self.assertIn("Unpushed commits: No", r.stdout)

    def test_diverged_with_conflict(self):
        self.push_from_other({"README": "theirs\n"})
        self.commit_local("README", "ours\n")
        r = self.run_gitcheck("-c")
        self.assertIn("└─ main: 1 (from origin/main)", r.stdout)
        self.assertIn("⚠ Diverged (1 local); merging would conflict in: README", r.stdout)

    def test_diverged_merges_cleanly(self):
        self.push_from_other({"theirs.txt": "x\n"})
        self.commit_local("ours.txt", "y\n")
        r = self.run_gitcheck("-c")
        self.assertIn("Diverged (1 local); merges cleanly", r.stdout)
        self.assertNotIn("⚠", r.stdout)

    def test_uncommitted_changes_clash_with_upstream(self):
        self.push_from_other({"README": "theirs\n", "new.txt": "theirs\n"})
        self.write("README", "ours\n")      # modified, not committed
        self.write("new.txt", "ours\n")     # untracked, would be overwritten
        self.write("unrelated.txt", "x\n")
        r = self.run_gitcheck("-c")
        self.assertIn("⚠ Uncommitted changes to files changed upstream: README, new.txt", r.stdout)

    def test_fetch_first_with_f(self):
        self.push_from_other({"a.txt": "1\n"}, fetch=False)
        r = self.run_gitcheck("-c")
        self.assertIn("Unpulled commits: No", r.stdout)
        r = self.run_gitcheck("-c", "-f")
        self.assertIn("└─ main: 1 (from origin/main)", r.stdout)
        self.assertIn("Remote status: Behind remote", r.stdout)

    # --- interactive pull ------------------------------------------------------

    def head(self, ref="HEAD"):
        return self.git("rev-parse", ref).strip()

    def test_pull_fast_forward_current(self):
        self.push_from_other({"a.txt": "1\n"})
        r = self.run_gitcheck("-c", "-i", answers=["y"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.head(), self.head("origin/main"))
        self.assertTrue(os.path.exists(os.path.join(self.repo, "a.txt")))

    def test_pull_fast_forward_other_branch(self):
        self.git("branch", "-q", "--track", "stale", "origin/main")
        self.push_from_other({"a.txt": "1\n"})
        before = self.head()
        r = self.run_gitcheck("-c", "-i", answers=["n", "y"])   # main: no; stale: yes
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.head(), before)
        self.assertEqual(self.head("stale"), self.head("origin/main"))

    def test_pull_merge_diverged(self):
        self.push_from_other({"theirs.txt": "x\n"})
        self.commit_local("ours.txt", "y\n")
        r = self.run_gitcheck("-c", "-i", answers=["m", "n"])   # merge; then don't push
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.git("rev-list", "--parents", "-n1", "HEAD").count(" "), 2)  # a merge
        self.assertIn("Merged origin/main into 'main'", r.stdout)
        self.assertIn("main: 2", r.stdout)                       # now 2 unpushed

    def test_pull_rebase_diverged(self):
        self.push_from_other({"theirs.txt": "x\n"})
        self.commit_local("ours.txt", "y\n")
        r = self.run_gitcheck("-c", "-i", answers=["r", "n"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.head("HEAD^"), self.head("origin/main"))

    def test_no_pull_offered_when_merge_would_conflict(self):
        self.push_from_other({"README": "theirs\n"})
        self.commit_local("README", "ours\n")
        before = self.head()
        r = self.run_gitcheck("-c", "-i", answers=["n"])         # only the push prompt
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("would not merge cleanly", r.stdout)
        self.assertEqual(self.head(), before)

    def test_no_pull_over_clashing_changes(self):
        self.push_from_other({"README": "theirs\n"})
        self.write("README", "ours\n")
        before = self.head()
        r = self.run_gitcheck("-c", "-i", answers=["n"])         # only the commit prompt
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Not pulling 'main': commit or stash the changes to README first", r.stdout)
        self.assertEqual(self.head(), before)

    def test_tracked_vs_untracked_and_branch(self):
        self.write("README", "changed\n")
        self.write("new1.txt", "x\n")
        self.write("newdir/a.txt", "x\n")
        self.write("newdir/b.txt", "x\n")
        r = self.run_gitcheck("-c")
        self.assertIn("Uncommitted changes: Yes (branch: main)", r.stdout)
        self.assertIn("Tracked files changed: 1", r.stdout)
        self.assertIn("Untracked files: 2", r.stdout)   # newdir/ counts once

    def test_unpushed_per_branch(self):
        self.git("commit", "-q", "--allow-empty", "-m", "ahead")
        self.git("checkout", "-q", "-b", "topic")
        self.git("commit", "-q", "--allow-empty", "-m", "t1")
        r = self.run_gitcheck("-c")
        self.assertIn("Unpushed commits: Yes", r.stdout)
        self.assertIn("└─ main: 1", r.stdout)
        self.assertIn("└─ topic: 2", r.stdout)   # never pushed: its own commit and main's

    def test_large_files(self):
        self.write("big file.bin", "x" * 1_500_000)
        self.git("add", "big file.bin")
        self.git("commit", "-q", "-m", "big")
        r = self.run_gitcheck("-l")
        self.assertIn("└─ big file.bin: 1.50MB", r.stdout)
        self.assertNotIn("README", r.stdout)

    # --- interactive ---------------------------------------------------------

    def test_interactive_add_ignore_commit_upstream_push(self):
        self.write("README", "changed\n")
        self.write("keep.txt", "x\n")
        self.write("junk[1].log", "x\n")
        self.git("checkout", "-q", "-b", "feature")
        # Untracked items come in sorted order: junk[1].log, keep.txt
        r = self.run_gitcheck("-c", "-i", answers=["i", "a", "a", "my message", "y", "y"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(os.path.join(self.repo, ".gitignore")) as f:
            self.assertEqual(f.read(), "/junk\\[1\\].log\n")
        log = self.git("log", "-1", "--name-only", "--format=%s")
        self.assertIn("my message", log)
        for name in (".gitignore", "keep.txt", "README"):
            self.assertIn(name, log)
        self.assertEqual(self.git("rev-parse", "--abbrev-ref", "feature@{u}").strip(), "origin/feature")
        self.assertIn("feature", self.git("branch", "--list", "feature", cwd=self.remote))
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_staged_only_commit(self):
        self.write("README", "changed\n")
        self.write("other.txt", "x\n")
        self.git("add", "other.txt")
        self.write("other.txt", "x\ny\n")
        # untracked: none; commit staged only; then decline the push
        r = self.run_gitcheck("-c", "-i", answers=["s", "staged", "n"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.git("log", "-1", "--name-only", "--format=").split(), ["other.txt"])
        self.assertIn(" M README", self.git("status", "--porcelain"))

    def test_empty_message_cancels_commit(self):
        self.write("README", "changed\n")
        r = self.run_gitcheck("-c", "-i", answers=["a", ""])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Commit cancelled", r.stdout)
        self.assertEqual(self.git("log", "-1", "--format=%s").strip(), "init")

    def test_no_upstream_answer_is_remembered(self):
        self.git("checkout", "-q", "-b", "local")
        self.git("commit", "-q", "--allow-empty", "-m", "l1")
        r = self.run_gitcheck("-c", "-i", answers=["n"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.git("config", "--bool", "branch.local.gitcheckNoUpstream").strip(), "true")
        # Second run: no answers available, so any prompt would make it fail
        r = self.run_gitcheck("-c", "-i")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("└─ local: 1 (local only)", r.stdout)
        self.assertNotIn("?", r.stdout)

    def test_skip_upstream_asks_again(self):
        self.git("checkout", "-q", "-b", "later")
        self.git("commit", "-q", "--allow-empty", "-m", "l1")
        r = self.run_gitcheck("-c", "-i", answers=["s"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = self.run_gitcheck("-c", "-i")
        self.assertEqual(r.returncode, 1)   # it asked again and could not read an answer

    # --- GitHub repositories not cloned (-u) ----------------------------------

    def fake_gh(self, names):
        """Replace the failing gh with one signed in as 'tester' that owns `names`
        and clones from the local bare remote."""
        with open(os.path.join(self.base, "bin", "gh"), "w") as f:
            f.write('#!/bin/sh\ncase "$1 $2" in\n'
                    '  "api user") echo tester ;;\n'
                    f'  "repo list") printf "%s\\n" {" ".join(names)} ;;\n'
                    f'  "repo clone") exec git clone -q "{self.remote}" "$4" ;;\n'
                    # repo create NAME VIS --source DIR --remote origin [--push]
                    f'  "repo create") echo "$@" > "{self.base}/gh-create.log"\n'
                    f'      git init -q --bare "{self.base}/created.git"\n'
                    f'      git -C "$6" remote add "$8" "{self.base}/created.git"\n'
                    '      [ "$9" = --push ] && git -C "$6" push -q -u "$8" HEAD ;;\n'
                    '  *) exit 1 ;;\nesac\n')
        self.env["XDG_CONFIG_HOME"] = os.path.join(self.base, "config")

    def test_uncloned_needs_gh(self):
        r = self.run_gitcheck("-u")
        self.assertIn("not cloned here: unknown", r.stdout)

    def test_uncloned_listed(self):
        self.fake_gh(["proj", "other", "third"])
        r = self.run_gitcheck("-u")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("└─ other", r.stdout)
        self.assertIn("└─ third", r.stdout)
        self.assertNotIn("└─ proj", r.stdout)

    def test_nothing_uncloned(self):
        self.fake_gh(["proj"])
        r = self.run_gitcheck("-u")
        self.assertIn("not cloned here: None", r.stdout)

    def test_interactive_clone_and_remember_no(self):
        self.fake_gh(["proj", "other", "third"])
        r = self.run_gitcheck("-u", "-i", answers=["y", "n"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(os.path.isdir(os.path.join(self.top, "other", ".git")))
        self.assertFalse(os.path.exists(os.path.join(self.top, "third")))
        with open(os.path.join(self.base, "config", "gitcheck", "noclone")) as f:
            self.assertEqual(f.read(), "tester/third\n")
        # Second run: 'third' is not offered again (no answers available)
        r = self.run_gitcheck("-u", "-i")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("└─ third (don't clone)", r.stdout)

    def test_quit(self):
        self.write("new.txt", "x\n")
        r = self.run_gitcheck("-c", "-i", answers=["q"])
        self.assertEqual(r.returncode, 0)
        self.assertIn("?? new.txt", self.git("status", "--porcelain"))


if __name__ == "__main__":
    unittest.main()
