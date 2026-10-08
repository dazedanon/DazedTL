"""Status polls must not launch Git again while the repository is unchanged."""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from dazedtl.translation.git_status_cache import RepositoryStatusCache


class RepositoryStatusCacheTests(unittest.TestCase):
    def test_polls_reuse_status_until_git_metadata_or_the_window_moves(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / ".git/refs/heads").mkdir(parents=True)
        (root / ".git/HEAD").write_text("ref: refs/heads/main\n")
        now = [100.0]
        computed = []

        def compute():
            computed.append(len(computed))
            return {"configured": len(computed) > 2}

        cache = RepositoryStatusCache(ttl=5, clock=lambda: now[0])
        read = lambda: cache.get("game", root, compute)
        self.assertEqual(read(), read())
        self.assertEqual(computed, [0])
        # A branch update rewrites a ref file; the next poll inspects again.
        branch = root / ".git/refs/heads/main"
        branch.write_text("a" * 40)
        os.utime(branch, ns=(1, 1))
        read()
        self.assertEqual(computed, [0, 1])
        now[0] += 5
        self.assertTrue(read()["configured"])
        self.assertEqual(computed, [0, 1, 2])
        # A repository that cannot be inspected costs the same launches, so the
        # failure is reused for the window too.
        failing = RepositoryStatusCache(ttl=5, clock=lambda: now[0])
        attempts = []

        def fail():
            attempts.append(True)
            raise ValueError("no git")

        for _ in range(2):
            with self.assertRaises(ValueError):
                failing.get("game", root, fail)
        self.assertEqual(len(attempts), 1)


if __name__ == "__main__":
    unittest.main()
