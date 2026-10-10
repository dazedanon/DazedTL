"""Extract and inject YU-RIS text through the game's own compiled scripts.

Works on YPF archives and YSTB scripts that yuris_decompiler reads, including
YPF 500 and YSTB 555. Requires `pip install murmurhash2`.

  yuris_text.py unpack    <archive.ypf> <out dir>
  yuris_text.py key       <ybn dir>
  yuris_text.py decompile <ybn dir> <out dir>
  yuris_text.py strings   <ybn dir>
  yuris_text.py units     <ybn dir> <units.json> [<command.argument> ...]
  yuris_text.py patch     <ybn dir> <translations.json> <out ybn dir>
  yuris_text.py pack      <original.ypf> <changed ybn dir> <out.ypf>

`decompile` writes the scripts' YST source as UTF-8, for DazedTL's census.
A line break in text is the bytes EF F0, outside Shift-JIS; units show it as
"\n" and patch writes "\n" (or "\r\n") in a translation back as those bytes.

Text lines are the scripts' WORD commands. Japanese string literals in
command arguments, such as choices, character names or confirmation
messages, are listed by `strings` as command.argument selectors with counts
and examples; pass the selectors that hold player text to `units`. Unit IDs
are `<ybn>/<command>` for text and `<ybn>/<command>/<argument>/<instruction>`
for a literal, and `patch` takes {unit ID: translation}.

YSTB scripts are XOR-encrypted with a per-game key. The first argument's
offset is always zero, so its encrypted bytes are the key. Patching appends
new text to the script's expression section and repoints the argument;
`pack` appends changed scripts to a copy of the archive and repoints their
entries, so every other byte keeps its place and a pack without changes
reproduces the archive exactly.
"""

import collections
import contextlib
import functools
import io
import json
import re
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "yuris_decompiler"))
from murmurhash2 import murmurhash2  # noqa: E402
from yurislib import y_decompile  # noqa: E402
from yurislib.fileformat import (  # noqa: E402
    YPF,
    YSCM,
    YSTB,
    YSTL,
    NameXorV000,
    NameXorV500,
    NLTransV000,
    NLTransV500,
    Rdr,
    xor_trans,
)

JAPANESE = re.compile("[぀-ヿ㐀-鿿ｦ-ﾟ]")
SPEAKER = re.compile(r"^([^「『（]{1,12})[「『（]")
STRING = 0x4D
# The E-ris text engine breaks a line on these bytes (VNTextPatch writes them
# for "\r\n").
LINE_BREAK = b"\xef\xf0"


def text_of(data):
    return "\n".join(part.decode("cp932", "replace") for part in bytes(data).split(LINE_BREAK))


@functools.cache
def key(ybn):
    counts = collections.Counter()
    for path in sorted(Path(ybn).glob("yst0*.ybn")):
        data = path.read_bytes()
        code, arg = struct.unpack_from("<II", data, 12)
        if arg >= 12:
            counts[data[32 + code + 8 : 32 + code + 12]] += 1
    if not counts:
        raise SystemExit("No scripts with arguments to read the key from.")
    return int.from_bytes(counts.most_common(1)[0][0], "big")


def scripts(ybn):
    """(script path, ybn name, YSTB, command table) for each compiled script."""
    ybn = Path(ybn)
    yscm = YSCM(Rdr((ybn / "ysc.ybn").read_bytes()))
    ystl = YSTL(Rdr((ybn / "yst_list.ybn").read_bytes()))
    secret = key(str(ybn))
    for script in ystl.scrs:
        if script.nvar < 0:
            continue
        name = f"yst{script.idx:05}.ybn"
        with open(ybn / name, "rb") as handle:
            yield script.path.replace("\\", "/"), name, YSTB(handle, yscm.kcc, secret), yscm


def instructions(data):
    """(index, start, end, code, payload) of each instruction in an argument's
    expression bytes; every instruction is a code, a 16-bit size and size bytes."""
    position, index = 0, 0
    while position < len(data):
        code, size = struct.unpack_from("<BH", data, position)
        yield index, position, position + 3 + size, code, data[position + 3 : position + 3 + size]
        position += 3 + size
        index += 1


def literals(ybn):
    """(unit ID, script path, selector, text) of each Japanese string literal
    in a command argument."""
    for path, name, ystb, yscm in scripts(ybn):
        exp = expression(Path(ybn, name).read_bytes(), key(str(ybn)))
        for command, cmd in enumerate(ystb.cmds):
            spec = yscm.cmds[cmd.code]
            name_of = lambda arg: (spec.args[arg.id].name if arg.id < len(spec.args) else "") or f"arg{arg.id}"
            # A GOSUB's parameters mean what its macro (#) makes of them.
            target = spec.name
            for arg in cmd.args:
                if spec.name == "GOSUB" and name_of(arg) == "#" and isinstance(arg.dat, list):
                    called = [i.arg for i in arg.dat if isinstance(i.arg, str)]
                    target = f"GOSUB[{called[0][1:-1] if called else '?'}]"
            for argument, arg in enumerate(cmd.args):
                # Arguments without parsed data hold jump targets, not text.
                if cmd.code == yscm.kcc.WORD or not isinstance(arg.dat, list):
                    continue
                selector = f"{target}.{name_of(arg)}"
                for index, _start, _end, code, payload in instructions(exp[arg.off : arg.off + arg.len]):
                    if code != STRING:
                        continue
                    text = payload[1:-1].decode("cp932", "replace")
                    if JAPANESE.search(text):
                        yield f"{name}/{command}/{argument}/{index}", path, selector, text


def expression(raw, secret):
    _, _, _, lcmd, larg, lexp, _, _ = struct.unpack_from("<8I", raw)
    start = 32 + lcmd + larg
    return bytes(xor_trans(bytearray(raw[start : start + lexp]), secret))


def strings(ybn):
    found = collections.defaultdict(list)
    for _id, _path, selector, text in literals(ybn):
        found[selector].append(text)
    for selector, texts in sorted(found.items(), key=lambda item: -len(item[1])):
        examples = list(dict.fromkeys(texts))[:3]
        print(f"{len(texts):6}  {selector}  e.g. {' | '.join(examples)}")


def units(ybn, out, *selectors):
    """Text lines and the selected literals, in play order within each script."""
    wanted = set(selectors)
    chosen = collections.defaultdict(list)
    for unit_id, path, selector, text in literals(ybn):
        if selector in wanted:
            name, *place = unit_id.split("/")
            chosen[name].append((tuple(map(int, place)), unit_id, text))
    found = []
    for path, name, ystb, yscm in scripts(ybn):
        rows = list(chosen[name])
        exp = expression(Path(ybn, name).read_bytes(), key(str(Path(ybn))))
        for command, cmd in enumerate(ystb.cmds):
            word = cmd.args[0] if cmd.code == yscm.kcc.WORD else None
            text = text_of(exp[word.off : word.off + word.len]) if word else ""
            if text.strip():
                rows.append(((command,), f"{name}/{command}", text))
        for _place, unit_id, text in sorted(rows):
            match = SPEAKER.match(text) if unit_id.count("/") == 1 else None
            found.append(
                {
                    "id": unit_id,
                    "group": path,
                    "scene": path,
                    "source": text,
                    "kind": ("dialogue" if match else "narration") if unit_id.count("/") == 1 else "ui",
                    "speaker": match.group(1) if match else None,
                }
            )
    Path(out).write_text(
        json.dumps({"version": 1, "units": found}, ensure_ascii=False, indent=1), "utf-8"
    )
    print(len(found), "units")


def encode(unit_id, text):
    parts = text.replace("\r\n", "\n").split("\n")
    try:
        return LINE_BREAK.join(part.encode("cp932") for part in parts)
    except UnicodeEncodeError as error:
        raise SystemExit(f"{unit_id}: {error.object[error.start]!r} is not in Shift-JIS; replace it.")


def patch(ybn, translations, out):
    wanted = collections.defaultdict(dict)
    for unit_id, text in json.loads(Path(translations).read_text("utf-8")).items():
        name, *place = unit_id.split("/")
        wanted[name][tuple(map(int, place))] = text
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    secret = key(str(ybn))
    patched = 0
    for _path, name, ystb, yscm in scripts(ybn):
        if name not in wanted:
            continue
        raw = (Path(ybn) / name).read_bytes()
        head = list(struct.unpack_from("<8I", raw))
        _, _, _, lcmd, larg, lexp, _, _ = head
        arg = xor_trans(bytearray(raw[32 + lcmd : 32 + lcmd + larg]), secret)
        exp = bytearray(expression(raw, secret))
        position = 0  # argument index in the argument section
        for command, cmd in enumerate(ystb.cmds):
            for argument, item in enumerate(cmd.args):
                at = (position + argument) * 12
                if (command,) in wanted[name] and cmd.code == yscm.kcc.WORD:
                    data = encode(f"{name}/{command}", wanted[name][(command,)])
                else:
                    changes = {
                        place[2]: text
                        for place, text in wanted[name].items()
                        if place[:2] == (command, argument)
                    }
                    if not changes:
                        continue
                    data = b""
                    for index, start, end, code, payload in instructions(
                        exp[item.off : item.off + item.len]
                    ):
                        if index not in changes:
                            data += exp[item.off + start : item.off + end]
                            continue
                        if code != STRING:
                            raise SystemExit(f"{name}/{command}/{argument}/{index} is not a string literal.")
                        quote = payload[:1]
                        text = encode(f"{name}/{command}/{argument}/{index}", changes[index])
                        if quote in text:
                            raise SystemExit(f"{name}/{command}/{argument}/{index}: remove {quote.decode()} from the translation.")
                        data += struct.pack("<BH", STRING, len(text) + 2) + quote + text + quote
                struct.pack_into("<II", arg, at + 4, len(data), len(exp))
                exp += data
                patched += 1
            position += len(cmd.args)
        if position * 12 != larg:
            raise SystemExit(f"{name}: arguments don't fill the argument section.")
        head[5] = len(exp)
        body = raw[32 : 32 + lcmd] + xor_trans(arg, secret) + xor_trans(exp, secret)
        body += raw[32 + lcmd + larg + lexp :]
        (out / name).write_bytes(struct.pack("<8I", *head) + body)
    print(patched, "arguments patched")


def decompile(ybn, out):
    # The decompiler prints every script path, which a Windows console's
    # code page can't encode.
    with contextlib.redirect_stdout(io.StringIO()) as log:
        y_decompile(str(ybn), str(out), None, key(str(Path(ybn))), o_encoding="utf-8")
    print(sum(1 for line in log.getvalue().splitlines() if line[:1].isdigit()), "scripts decompiled")


def unpack(archive, out):
    with open(archive, "rb") as handle:
        YPF(handle).extract(out, log=None)


def pack(original, changed, out):
    blob = bytearray(Path(original).read_bytes())
    _, version, count, _ = struct.unpack_from("<4I", blob)
    sizes = NLTransV500 if version == 500 else NLTransV000
    names = NameXorV500 if version == 500 else NameXorV000
    if version < 470:
        raise SystemExit("pack writes the 64-bit entries of YPF 470 and later.")
    changed = {path.name.casefold(): path for path in Path(changed).glob("*.ybn")}
    position, replaced = 32, 0
    for _ in range(count):
        size = sizes[blob[position + 4] ^ 0xFF]
        name = bytes(blob[position + 5 : position + 5 + size]).translate(names).decode("cp932")
        entry = position + 5 + size
        position = entry + 22
        source = changed.get(name.replace("\\", "/").rsplit("/", 1)[-1].casefold())
        if not source:
            continue
        data = source.read_bytes()
        stored = zlib.compress(data) if blob[entry + 1] else data
        struct.pack_into("<IIQI", blob, entry + 2, len(data), len(stored), len(blob), murmurhash2(stored, 0))
        blob += stored
        replaced += 1
    Path(out).write_bytes(blob)
    print(replaced, "files replaced")


if __name__ == "__main__":
    # Japanese text and paths print as UTF-8 whatever the console's code page.
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    command, *rest = sys.argv[1:] or ["help"]
    commands = {
        "unpack": unpack, "decompile": decompile, "strings": strings,
        "units": units, "patch": patch, "pack": pack,
    }
    if command == "key":
        print(hex(key(str(Path(*rest)))))
    elif command in commands:
        commands[command](*rest)
    else:
        print(__doc__)
