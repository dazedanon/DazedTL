"""The one rule for whether saved work is still current."""

import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from dazedtl.freshness import Basis, Change, Digests, compare


class FreshnessTests(unittest.TestCase):
    def test_compare_names_what_changed_and_reads_older_records(self):
        saved = Basis(1, {"a": "1", "b": "2"}, settings="s", shape="p")
        self.assertIsNone(compare(saved, Basis(1, {"a": "1", "b": "2"}, "s", "p")))
        self.assertEqual(
            compare(saved, Basis(1, {"a": "9", "c": "3"}, "s", "p")),
            Change(added=("c",), removed=("b",), changed=("a",)),
        )
        self.assertEqual(
            compare(saved, Basis(2, saved.inputs, "s", "p")), Change(version=True)
        )
        self.assertEqual(compare(None, saved), Change(missing=True))
        # A price-only switch keeps the work only while the prices are unknown.
        moved = Basis(1, saved.inputs, settings="t", shape="p")
        self.assertEqual(compare(saved, moved), Change(settings=True))
        self.assertIsNone(compare(saved, moved, prices_unknown=True))
        reshaped = Basis(1, saved.inputs, settings="t", shape="q")
        self.assertEqual(
            compare(saved, reshaped, prices_unknown=True), Change(settings=True)
        )
        # A record whose inputs cannot be named reads as changed.
        self.assertEqual(compare(Basis(1), saved), Change(unnamed=True))
        self.assertEqual(Basis.read(saved.record()), saved)

    def test_a_file_is_read_again_until_it_has_settled(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "a.txt"
            path.write_bytes(b"one")
            digests = Digests()
            frozen = os.lstat(path)
            digests.file(path, frozen)
            # Rewritten within one tick: the signature holds, the bytes do not.
            path.write_bytes(b"two")
            self.assertEqual(digests.file(path, frozen), digests.file(path))
            # Once it has been still for longer, the saved digest is reused.
            old = time.time_ns() - 3_000_000_000
            times = {"st_atime_ns": old, "st_mtime_ns": old, "st_ctime_ns": old}
            settled = os.stat_result(tuple(frozen)[:10], times)
            first = digests.file(path, settled)
            path.write_bytes(b"333")
            self.assertEqual(digests.file(path, settled), first)


if __name__ == "__main__":
    unittest.main()
