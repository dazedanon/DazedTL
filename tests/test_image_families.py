"""Image variant families: find them and rebuild their exact text-free backdrop."""

import sqlite3
import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

import cv2
import numpy as np
from dazedtl.compatibility.images import ImageCompatibility
from dazedtl.images import background, families
from dazedtl.images.inventory import Index, inspect_row
from PIL import Image

# Strokes of five name cards. The first two share one at x=60, so pure white
# fill there matches across cards and must not pass for the backdrop, and each
# card has a stroke in one cluster that leaves no card untouched around it.
TEXTS = tuple(
    strokes + [(96 + 3 * index, 64, 2, 10)]
    for index, strokes in enumerate(
        (
            [(30, 40, 3, 14), (40, 40, 12, 3), (60, 38, 3, 16)],
            [(36, 42, 14, 3), (60, 38, 3, 16), (90, 40, 3, 14)],
            [(70, 44, 16, 3), (100, 36, 3, 18)],
            [(50, 40, 3, 14), (110, 42, 10, 3)],
            [(80, 38, 3, 16), (44, 46, 18, 3), (120, 40, 3, 12)],
        )
    )
)


def backdrop(seed=1, width=160, height=96):
    """A translucent nebula with stars."""
    rng = np.random.default_rng(seed)
    noise = cv2.GaussianBlur(
        rng.random((height, width, 4)).astype(np.float32), (0, 0), 6
    )
    noise = (noise - noise.min()) / (noise.max() - noise.min())
    image = np.dstack(
        [
            90 + 120 * noise[..., 0],
            40 + 80 * noise[..., 1],
            120 + 100 * noise[..., 2],
            110 + 90 * noise[..., 3],
        ]
    )
    image[rng.integers(0, height, 120), rng.integers(0, width, 120)] = (
        255,
        255,
        255,
        230,
    )
    return np.round(image).astype(np.uint8)


def letter(base, strokes):
    """White strokes with a black outline over a neutral dark glow."""
    fill = np.zeros(base.shape[:2], np.uint8)
    for x, y, w, h in strokes:
        fill[y : y + h, x : x + w] = 1
    outline = cv2.dilate(fill, np.ones((3, 3), np.uint8))
    core = cv2.dilate(outline, np.ones((3, 3), np.uint8)).astype(np.float32)
    glow = np.clip(0.85 * cv2.GaussianBlur(core, (21, 21), 2.5), 0, 1)[..., None]
    values = base / 255
    alpha = glow + values[..., 3:] * (1 - glow)
    colour = values[..., :3] * values[..., 3:] * (1 - glow) / np.maximum(alpha, 1e-6)
    result = np.round(np.dstack([colour, alpha]) * 255).astype(np.uint8)
    result[outline > 0] = (0, 0, 0, 255)
    result[fill > 0] = (255, 255, 255, 255)
    return result


def premultiplied(image):
    values = image / 255
    return np.dstack([values[..., :3] * values[..., 3:], values[..., 3:]]) * 255


def png(pixels):
    stream = BytesIO()
    Image.fromarray(pixels, "RGBA").save(stream, format="PNG")
    return stream.getvalue()


class BackgroundTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = backdrop()
        cls.members = [letter(cls.base, strokes) for strokes in TEXTS]
        cls.family = background.analyse(cls.members)

    def test_lettering_is_removed_exactly_and_nothing_else_changes(self):
        solution = background.solve(self.family, 0)
        error = np.abs(premultiplied(solution.pixels) - premultiplied(self.base)).max(
            -1
        )
        method = solution.method
        self.assertEqual(self.family.report["open"], "inverted")
        self.assertLess(self.family.report["validation"]["inverted"]["mean"], 1.5)
        # Untouched pixels keep the target's own bytes; consensus comes from
        # members whose lettering reaches no further than faint tails.
        self.assertTrue(
            np.array_equal(
                solution.pixels[method == background.KEPT],
                self.members[0][method == background.KEPT],
            )
        )
        consensus = method == background.CONSENSUS
        self.assertGreater(consensus.sum(), 1000)
        self.assertGreater(
            (solution.pixels[consensus] == self.base[consensus]).all(-1).mean(), 0.95
        )
        self.assertLessEqual(error[consensus].max(), 1)
        rebuilt = method >= background.INVERTED
        self.assertGreater(rebuilt.sum(), 50)
        self.assertLess(error[rebuilt].mean(), 1.5)
        self.assertLessEqual(error[rebuilt].max(), 4)
        # Under the white stroke two cards share, the backdrop comes back.
        self.assertLessEqual(error[45, 61], 2)
        shared = background.solve(self.family)
        error = np.abs(premultiplied(shared.pixels) - premultiplied(self.base)).max(-1)
        self.assertLessEqual(error.max(), 4)

    def test_members_that_disagree_away_from_lettering_are_rejected(self):
        changed = [member.copy() for member in self.members]
        changed[3][4:10, 4:10, 0] += 20
        with self.assertRaises(background.FamilyError) as raised:
            background.analyse(changed)
        self.assertEqual(list(raised.exception.details["membersOffConsensus"]), [3])
        self.assertEqual(raised.exception.details["conflictBox"], [4, 4, 6, 6])

    def test_check_finds_lettering_ghosts_in_a_saved_background(self):
        shared = background.solve(self.family).pixels
        report, _residual = background.check(self.family, shared)
        self.assertTrue(report["ok"])
        # A faint dark copy of the last card's strokes left in the backdrop.
        ghosted = shared.copy()
        strokes = letter(self.base, TEXTS[4])[..., 3] == 255
        ghosted[strokes, :3] = ghosted[strokes, :3] * 0.6
        report, _residual = background.check(self.family, ghosted)
        self.assertFalse(report["ok"])
        self.assertEqual(report["ghosts"][0]["member"], 4)
        self.assertIn(4, [ghost["member"] for ghost in report["ghosts"]])


class FamilyTests(unittest.TestCase):
    def test_variants_group_and_unrelated_or_duplicate_images_do_not(self):
        base = backdrop()
        other = backdrop(seed=2)
        entries = [
            (f"card{index}", 160, 96, "RGBA", families.signature(letter(base, strokes)))
            for index, strokes in enumerate(TEXTS)
        ]
        entries += [
            (name, 160, 96, "RGBA", families.signature(other))
            for name in ("other", "other copy")
        ]
        entries.append(("small", 80, 48, "RGBA", families.signature(base[:48, :80])))
        found = families.group(entries)
        self.assertEqual(
            [family["members"] for family in found],
            [[f"card{index}" for index in range(5)]],
        )
        x, y, w, h = found[0]["region"]
        # The region holds every stroke and its glow, at tile precision.
        self.assertTrue(x <= 22 and y <= 30 and x + w >= 128 and y + h >= 60)
        self.assertLess(w * h, 160 * 96 / 2)

    def test_inventory_records_originals_families_and_translation_state(self):
        base = backdrop()
        with TemporaryDirectory() as folder:
            root = Path(folder)
            adapter = ImageCompatibility(None)
            index = Index(root / "inventory.sqlite3")
            entries, rows = [], []
            for number, strokes in enumerate(TEXTS):
                name = f"img/pictures/Card{number}.png"
                original = letter(base, strokes)
                runtime = root / name
                runtime.parent.mkdir(parents=True, exist_ok=True)
                if number == 0:
                    # Translated by an earlier workflow: the Qt backup keeps the original.
                    backup = root / ".dazedtl/image_backups" / name
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    backup.write_bytes(png(original))
                    original = letter(base, [(20, 30, 40, 20)])
                runtime.write_bytes(png(original))
                entry = {
                    "id": name,
                    "path": name,
                    "profile": "generic",
                    "runtime": name,
                    "destination": name,
                    "editable": ".dazedtl/images/" + name,
                    "encrypted": False,
                }
                entries.append(entry)
                # The image service adds each row's state before storing it.
                rows.append(
                    {
                        **inspect_row(root, adapter, entry, None, None),
                        "state": "not_prepared",
                    }
                )
            with index.connection() as db:
                for row in rows:
                    Index.put(db, row)
            stored = (
                sqlite3.connect(index.path)
                .execute("SELECT count(*), max(instr(data, 'familyTiles')) FROM assets")
                .fetchone()
            )
            self.assertEqual(stored, (5, 0))
            self.assertEqual(
                index.refresh_families()[0]["members"], [row["id"] for row in rows]
            )
            family = index.family("img/pictures/Card1.png")
            self.assertEqual(
                [
                    (member["original"], member["translated"])
                    for member in family["members"]
                ][:2],
                [
                    (".dazedtl/image_backups/img/pictures/Card0.png", "game"),
                    ("img/pictures/Card1.png", ""),
                ],
            )
            # An unchanged original is not decoded again on the next scan.
            again = inspect_row(
                root, adapter, entries[1], index.get(entries[1]["id"]), None
            )
            self.assertNotIn("familyTiles", again)
