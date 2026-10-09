"""Dump a Unity game's TextAssets and MonoBehaviours for DazedTL's census.

  python unity_dump.py <game folder> <out folder>

Requires `pip install UnityPy TypeTreeGeneratorAPI`. Release builds strip
MonoBehaviour type trees; the generator rebuilds them from the game's own
assemblies (Managed/*.dll for Mono, GameAssembly + global-metadata.dat for
IL2CPP), so MonoBehaviours read as JSON; one the generator still can't read
keeps its serialized strings (int32 length + UTF-8, 4-aligned) in a
.strings.txt file, so the census counts its text. Files land under
<assets file>/<type>/<name>_<path id>, so scope rules can name a container
with a file pattern. Point `census --decoded` at the out folder, inside the
game.
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

import UnityPy
from UnityPy.helpers.TypeTreeGenerator import TypeTreeGenerator


def serialized_strings(raw):
    """Strings a MonoBehaviour serializes, read without its type tree."""
    found, at = [], 0
    while at + 4 <= len(raw):
        size = int.from_bytes(raw[at : at + 4], "little")
        if 0 < size <= len(raw) - at - 4:
            try:
                text = raw[at + 4 : at + 4 + size].decode("utf-8")
            except UnicodeDecodeError:
                text = ""
            if text.strip() and all(ch.isprintable() or ch in "\r\n\t" for ch in text):
                found.append(text.replace("\r", "\\r").replace("\n", "\\n"))
                at += 4 + (size + 3) // 4 * 4
                continue
        at += 4
    return found


def safe(name):
    return re.sub(r'[\\/:*?"<>|\s]+', "_", name).strip("_")[:80] or "unnamed"


def main(game, out):
    game, out = Path(game), Path(out)
    data = next(game.glob("*_Data"))
    env = UnityPy.load(str(data))
    generator = TypeTreeGenerator(env.objects[0].assets_file.unity_version)
    generator.load_local_game(str(game))
    env.typetree_generator = generator
    dumped, failed = Counter(), Counter()
    for obj in env.objects:
        kind = obj.type.name
        if kind not in ("TextAsset", "MonoBehaviour"):
            continue
        folder = out / safe(obj.assets_file.name) / kind
        read = kind
        try:
            if kind == "TextAsset":
                asset = obj.read()
                raw = asset.m_Script
                if isinstance(raw, str):
                    raw = raw.encode("utf-8", "surrogateescape")
                target = folder / f"{safe(asset.m_Name)}_{obj.path_id}.txt"
                body = bytes(raw)
            else:
                tree = obj.read_typetree()
                target = folder / f"{safe(tree.get('m_Name', ''))}_{obj.path_id}.json"
                body = json.dumps(tree, ensure_ascii=False, default=str).encode("utf-8")
        except Exception as error:  # report every unreadable object, keep going
            failed[(kind, type(error).__name__)] += 1
            if kind != "MonoBehaviour":
                continue
            target = folder / f"unread_{obj.path_id}.strings.txt"
            body = "\n".join(serialized_strings(obj.get_raw_data())).encode("utf-8")
            read = "strings only"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        dumped[read] += 1
    print("dumped", dict(dumped), "failed", dict(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(main(*sys.argv[1:]))
