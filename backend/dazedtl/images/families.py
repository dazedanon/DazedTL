"""Find image variant families in the inventory.

A family is a set of same-size images whose pixels are identical except in a
local region, such as name cards or area banners that differ only in their
lettering. Their shared backdrop can be rebuilt exactly from the members
(background.py), so editing never has to inpaint it.

Each image gets a tile signature of its untranslated original: a digest per
tile and which tiles hold one flat colour. Members of a family share most of
their non-flat tiles at the same positions; flat tiles, such as transparent
margins, prove nothing.
"""

import hashlib
from functools import cache

# Tiles along an image's longer side.
TILES = 32
# Share of the non-flat tiles that two members must have identical.
MATCH = 0.4
VERSION = 2
BACKUPS = ".dazedtl/image_backups/"


def tile_size(width, height):
    return max(4, -(-max(width, height) // TILES))


@cache
def _weights(size):
    import numpy as np

    # Fixed random odd weights make each tile's digest a linear hash of its
    # packed pixels modulo 2**64: equal tiles always match, and two different
    # tiles collide with a chance below 2**-33.
    random = np.random.default_rng(VERSION)
    return random.integers(0, 2**63, (size, size), dtype=np.uint64) * 2 + 1


def signature(pixels):
    """The tile signature of an RGBA uint8 image, as bytes."""
    import numpy as np

    height, width = pixels.shape[:2]
    size = tile_size(width, height)
    rows, columns = -(-height // size), -(-width // size)
    padded = np.ascontiguousarray(pixels)
    if height % size or width % size:
        padded = np.zeros((rows * size, columns * size, 4), np.uint8)
        padded[:height, :width] = pixels
    # Hidden colour under full transparency is invisible, so it never differs.
    packed = padded.view("<u4")[..., 0] * (padded[..., 3] != 0)
    tiles = packed.reshape(rows, size, columns, size)
    with np.errstate(over="ignore"):
        digests = (tiles * _weights(size)[None, :, None, :]).sum(
            (1, 3), dtype=np.uint64
        )
    flat = (tiles == tiles[:, :1, :, :1]).all((1, 3))
    return (
        bytes([VERSION]) + digests.astype("<u8").tobytes() + np.packbits(flat).tobytes()
    )


def _parse(blob, width, height):
    import numpy as np

    size = tile_size(width, height)
    count = -(-height // size) * -(-width // size)
    if not blob or blob[0] != VERSION or len(blob) != 1 + 8 * count + -(-count // 8):
        return None
    digests = np.frombuffer(blob, "<u8", count, 1)
    flat = np.unpackbits(np.frombuffer(blob, np.uint8, offset=1 + 8 * count))[:count]
    return digests, flat.astype(bool)


def _root(parent, index):
    while parent[index] != index:
        parent[index] = parent[parent[index]]
        index = parent[index]
    return index


def group(entries):
    """Families among (id, width, height, mode, signature) entries, each as
    its sorted members and the [x, y, width, height] region where they differ."""
    import numpy as np

    buckets = {}
    for identity, width, height, mode, blob in entries:
        parsed = _parse(blob, width, height) if width and height else None
        if parsed:
            buckets.setdefault((width, height, mode), []).append((identity, parsed))
    families = []
    for (width, height, mode), members in sorted(buckets.items()):
        if len(members) < 2:
            continue
        members.sort(key=lambda item: item[0].casefold())
        digests = np.stack([parsed[0] for _, parsed in members])
        solid = ~np.stack([parsed[1] for _, parsed in members])
        counts = solid.sum(1)
        parent = list(range(len(members)))

        for start in range(0, len(members), 32):
            same = digests[start : start + 32, None] == digests[None]
            # Equal digests mean equal tiles, so a match is flat in both or neither.
            matches = (same & solid[None]).sum(-1)
            need = np.maximum(
                2,
                np.ceil(
                    MATCH * np.maximum(counts[start : start + 32, None], counts[None])
                ),
            )
            for left, right in zip(*np.nonzero(matches >= need), strict=True):
                if right > start + left:
                    parent[_root(parent, start + int(left))] = _root(parent, int(right))
        components = {}
        for index in range(len(members)):
            components.setdefault(_root(parent, index), []).append(index)
        size = tile_size(width, height)
        columns = -(-width // size)
        for indices in components.values():
            varying = ~(digests[indices] == digests[indices[0]]).all(0)
            if len(indices) < 2 or not varying.any():
                continue
            tiles = np.nonzero(varying)[0]
            x0, y0 = (
                int((tiles % columns).min() * size),
                int((tiles // columns).min() * size),
            )
            x1 = min(width, int(((tiles % columns).max() + 1) * size))
            y1 = min(height, int(((tiles // columns).max() + 1) * size))
            identities = [members[index][0] for index in indices]
            families.append(
                {
                    "id": hashlib.sha256("\0".join(identities).encode()).hexdigest()[
                        :16
                    ],
                    "members": identities,
                    "region": [x0, y0, x1 - x0, y1 - y0],
                }
            )
    return families


def original_file(root, row):
    """Where an inventory row's untranslated original is: its frozen copy, the
    Qt publisher's backup, or the runtime file, and whether it is encrypted."""
    from dazedtl.translation.files import project_path

    if row.get("frozen"):
        return row["frozen"], False
    if not row.get("runtime"):
        raise ValueError("The image has no runtime source.")
    backup = BACKUPS + row["runtime"]
    if project_path(root, backup, exists=False).is_file():
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
