"""Find image variant families in the inventory.

A family is a set of same-size images whose pixels are identical except in a
local region, such as name cards or area banners that differ only in their
lettering. Their shared backdrop can be rebuilt exactly from the members
(background.py), so editing never has to inpaint it.

Each image gets a tile signature of its untranslated original: a digest of a
grid of samples per tile and which tiles hold one flat colour. Members of a
family share most of their non-flat tiles at the same positions; flat tiles,
such as transparent margins, prove nothing.

Grouping never compares every pair: each image's few smallest tile keys, a
bottom-k sketch, name its likely siblings, and only those pairs are counted.
"""

import hashlib
from fractions import Fraction
from functools import cache
from math import ceil
from pathlib import Path

# Tiles along an image's longer side, and samples along each tile's side.
TILES = 32
SAMPLES = 8
# Share of the non-flat tiles that two members must have identical.
MATCH = Fraction(2, 5)
# Tile keys per image that name its candidate siblings.
SKETCH = 24
# Components one shared tile may link before it counts as too common to tell,
# and the members of each that a newcomer is checked against.
CROWD = 32
REPRESENTATIVES = 4
VERSION = 3
BACKUPS = ".dazedtl/image_backups/"


def tile_size(width, height):
    return max(4, -(-max(width, height) // TILES))


def _grid(width, height):
    size = tile_size(width, height)
    return -(-height // size), -(-width // size), min(SAMPLES, size)


def _count(width, height):
    rows, columns, _samples = _grid(width, height)
    return rows * columns


@cache
def _weights(samples):
    import numpy as np

    # Fixed random odd weights make a tile's digest a linear hash of its packed
    # samples modulo 2**64, folded to 32 bits: equal tiles always match and
    # different ones almost never do.
    random = np.random.default_rng(VERSION)
    return random.integers(0, 2**63, (samples, samples), dtype=np.uint64) * 2 + 1


def signature(image):
    """The tile signature of a PIL image or RGBA uint8 array, as bytes. It
    reads a grid of samples, so it costs little beside decoding the image."""
    import numpy as np
    from PIL import Image

    if isinstance(image, np.ndarray):
        image = Image.fromarray(image, "RGBA")
    width, height = image.size
    rows, columns, samples = _grid(width, height)
    grid = image.resize((columns * samples, rows * samples), Image.Resampling.NEAREST)
    if grid.mode != "RGBA":
        grid = grid.convert("RGBA")
    pixels = np.asarray(grid)
    # Hidden colour under full transparency is invisible, so it never differs.
    packed = pixels.view("<u4")[..., 0] * (pixels[..., 3] != 0)
    tiles = np.ascontiguousarray(
        packed.reshape(rows, samples, columns, samples).transpose(0, 2, 1, 3)
    ).reshape(rows * columns, samples * samples)
    with np.errstate(over="ignore"):
        wide = (tiles * _weights(samples).reshape(-1)).sum(1, dtype=np.uint64)
    digests = (wide ^ (wide >> np.uint64(32))).astype("<u4")
    flat = (tiles == tiles[:, :1]).all(1)
    return bytes([VERSION]) + digests.tobytes() + np.packbits(flat).tobytes()


def _valid(blob, count):
    return (
        bool(blob)
        and blob[0] == VERSION
        and len(blob) == 1 + 4 * count + -(-count // 8)
    )


def _root(parent, index):
    while parent[index] != index:
        parent[index] = parent[parent[index]]
        index = parent[index]
    return index


def _sketch(digests, solid):
    """Per image, its SKETCH smallest keys of non-flat tiles; a key is a
    bijective mix of the tile's position and digest, so equal keys are equal
    tiles at one position. Images are taken in blocks to bound memory."""
    import numpy as np

    count, tiles = digests.shape
    size = min(SKETCH, tiles)
    positions = np.arange(tiles, dtype=np.uint64)
    empty = np.uint64(np.iinfo(np.uint64).max)
    blocks = []
    for start in range(0, count, 256):
        keys = (
            digests[start : start + 256].astype(np.uint64) << np.uint64(16)
        ) | positions
        with np.errstate(over="ignore"):
            keys *= np.uint64(0x9E3779B97F4A7C15)
        keys[~solid[start : start + 256]] = empty
        # A copy, so the block it was cut from is freed.
        blocks.append(np.partition(keys, size - 1, axis=1)[:, :size].copy())
    keys = np.concatenate(blocks).ravel()
    owners = np.repeat(np.arange(count), size)
    keep = keys != empty
    return keys[keep], owners[keep]


def _components(digests, solid):
    """Union-find over the pairs that share a sketch key and at least MATCH of
    their non-flat tiles."""
    import numpy as np

    counts = solid.sum(1)
    parent = list(range(len(digests)))

    def linked(left, right):
        need = max(2, ceil(MATCH * int(max(counts[left], counts[right]))))
        same = (digests[left] == digests[right]) & solid[left]
        return int(np.count_nonzero(same)) >= need

    keys, owners = _sketch(digests, solid)
    order = np.lexsort((owners, keys))
    keys, owners = keys[order], owners[order]
    starts = np.flatnonzero(np.r_[True, keys[1:] != keys[:-1]])
    ends = np.r_[starts[1:], len(keys)]
    for start, end in zip(starts.tolist(), ends.tolist(), strict=True):
        if end - start < 2:
            continue
        # A few members of each component this key has met: a family joins in
        # a chain of checks, and a key shared by many unrelated images stops.
        met = {}
        for member in owners[start:end].tolist():
            mine = _root(parent, member)
            for theirs in [root for root in met if root != mine]:
                if any(linked(member, other) for other in met[theirs]):
                    parent[theirs] = mine
                    met[mine] = (met.get(mine, []) + met.pop(theirs))[:REPRESENTATIVES]
            known = met.setdefault(mine, [])
            if len(known) < REPRESENTATIVES:
                known.append(member)
            if len(met) > CROWD:
                break
    components = {}
    for index in range(len(digests)):
        components.setdefault(_root(parent, index), []).append(index)
    return components.values()


def group(entries):
    """Families among (id, width, height, mode, signature) entries, each as
    its sorted members and the [x, y, width, height] region where they differ."""
    buckets = {}
    for identity, width, height, mode, blob in entries:
        if width and height and _valid(blob, _count(width, height)):
            buckets.setdefault((width, height, mode), []).append((identity, blob))
    families = []
    for (width, height, _mode), members in sorted(buckets.items(), key=str):
        families += group_size(width, height, members, len(members))
    return families


def group_size(width, height, members, count):
    """Families among count (id, signature) members of one size and mode,
    read once into arrays so their signatures need not all stay in memory."""
    import numpy as np

    if count < 2:
        return []
    rows, columns, _samples = _grid(width, height)
    tiles = rows * columns
    digests = np.empty((count, tiles), np.uint32)
    packed = np.empty((count, -(-tiles // 8)), np.uint8)
    identities = []
    for identity, blob in members:
        if len(identities) < count and _valid(blob, tiles):
            digests[len(identities)] = np.frombuffer(blob, "<u4", tiles, 1)
            packed[len(identities)] = np.frombuffer(
                blob, np.uint8, offset=1 + 4 * tiles
            )
            identities.append(identity)
    digests = digests[: len(identities)]
    solid = ~np.unpackbits(packed[: len(identities)], axis=1, count=tiles).view(bool)
    del packed
    families = []
    for indices in _components(digests, solid):
        varying = ~(digests[indices] == digests[indices[0]]).all(0)
        if len(indices) < 2 or not varying.any():
            continue
        changed = np.nonzero(varying)[0]
        x0 = int((changed % columns).min()) * width // columns
        y0 = int((changed // columns).min()) * height // rows
        x1 = -(-(int((changed % columns).max()) + 1) * width // columns)
        y1 = -(-(int((changed // columns).max()) + 1) * height // rows)
        names = sorted((identities[index] for index in indices), key=str.casefold)
        families.append(
            {
                "id": hashlib.sha256("\0".join(names).encode()).hexdigest()[:16],
                "members": names,
                "region": [x0, y0, x1 - x0, y1 - y0],
            }
        )
    return families


def original_file(root, row):
    """Where an inventory row's untranslated original is: its frozen copy, the
    Qt publisher's backup, or the runtime file, and whether it is encrypted."""
    if row.get("frozen"):
        return row["frozen"], False
    if not row.get("runtime"):
        raise ValueError("The image has no runtime source.")
    backup = BACKUPS + row["runtime"]
    # A plain stat; reading the file goes through project_path's checks.
    if (Path(root) / backup).is_file():
        return backup, bool(row["encrypted"])
    return row["runtime"], bool(row["encrypted"])


def translated(row):
    """How a member is translated: applied by DazedTL, edited in its working
    copy, already in the game from earlier work, or not at all."""
    if row.get("state") == "applied":
        return "applied"
    if row.get("changed"):
        return "edited"
    original = row.get("original") or {}
    if (
        original.get("path") not in (None, row.get("runtime"))
        and original.get("pngHash")
        and original["pngHash"] != row.get("sourcePngHash")
    ):
        return "game"
    return ""
