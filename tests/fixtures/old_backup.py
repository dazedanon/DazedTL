"""A game's backup as DazedTL saved them before it kept original files in
Git, for tests of projects set up then."""

import hashlib
import os
import stat
from datetime import UTC, datetime
from pathlib import Path

from dazedtl.storage import write_bytes, write_json
from dazedtl.translation import backups


def snapshot(game):
    """Saves every file of `game` but .git and .dazedtl in its own backup
    store, and returns the record lifecycle.json kept of it."""
    game = Path(game).resolve()
    store = game / backups.STORE_RELATIVE
    write_json(store / "store.json", {"version": 2})
    value = {
        "version": 2,
        "source": str(game),
        "kind": "source",
        "created": datetime.now(UTC).isoformat(),
        "files": {},
        "sizes": {},
        "modes": {},
        "directories": [],
    }
    for directory, folders, files in os.walk(game):
        here = Path(directory)
        if here == game:
            folders[:] = [name for name in folders if name not in {".git", ".dazedtl"}]
        value["directories"].extend(
            (here / name).relative_to(game).as_posix() for name in folders
        )
        for name in files:
            path = here / name
            raw = path.read_bytes()
            fingerprint = hashlib.sha256(raw).hexdigest()
            relative = path.relative_to(game).as_posix()
            value["files"][relative] = fingerprint
            value["sizes"][relative] = len(raw)
            value["modes"][relative] = stat.S_IMODE(path.stat().st_mode) & 0o777
            write_bytes(store / "objects" / fingerprint[:2] / fingerprint, raw)
    value["directories"].sort()
    value["fingerprint"] = backups._identity(value)
    value["id"] = value["fingerprint"][:32]
    folder = store / "snapshots" / value["id"]
    write_json(folder / "manifest.json", value)
    return {
        "id": value["id"],
        "path": str(folder),
        "files": len(value["files"]),
        "kind": "source",
        "version": 2,
    }
