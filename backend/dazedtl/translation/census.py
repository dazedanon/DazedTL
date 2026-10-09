"""The game's Japanese text, found by the tool itself, so what the assistant
extracts can be checked against everything the game holds.

Readers know file formats, never content. Each string the game holds becomes
an entry with its file, exact location, a kind from a fixed vocabulary and a
field: the location with every index and data-named key wildcarded, which is
what scope rules match, so no rule can single out one map, event or scene.
Coverage compares Japanese runs, so an extractor may split lines, join them
with separators or mask control codes without losing track of a line.
"""

from __future__ import annotations

import json
import re
import struct
import zlib
from collections import Counter
from functools import cache, lru_cache
from pathlib import PurePosixPath

VERSION = 1

_RUN = re.compile("[　-〿぀-ヿㇰ-ㇿ㐀-䶿一-鿿豈-﫿！-｠｡-ﾟ￠-￮]+")
_WORD = re.compile("[぀-ヿㇰ-ㇿ㐀-䶿一-鿿豈-﫿ｦ-ﾟ]")


def runs(text):
    """Maximal runs of Japanese characters that hold at least one kana or kanji."""
    if not isinstance(text, str):
        return []
    return [match for match in _RUN.findall(text) if _WORD.search(match)]


# What the census reads directly, opens itself, decodes with WolfDawn, or
# needs the assistant's decoded dump for.
TEXT = {
    ".json", ".js", ".ks", ".tjs", ".rpy", ".html", ".htm", ".txt", ".csv",
    ".tsv", ".ini", ".xml", ".cfg", ".yaml", ".yml", ".asset", ".prefab",
    ".unity", ".rxdata", ".rvdata", ".rvdata2",
}  # fmt: skip
OPENED = {".rgssad", ".rgss2a", ".rgss3a", ".asar", ".xp3"}
WOLF = {".mps", ".dat", ".project"}
WOLF_TEXT = {"basicdata", "mapdata", "data"}
NEEDS_DUMP = {
    ".ypf", ".pck", ".utoc", ".ucas", ".assets", ".bundle", ".unity3d",
    ".dts", ".nsa", ".sar", ".dxa", ".pfs",
}  # fmt: skip
NEEDS_DUMP_NAMES = {"data.win", "game.unx", "globalgamemanagers", "scene.pck"}
SKIPPED_DIRS = {".git", ".dazedtl", "save", "saves", "locales", "swiftshader"}
# Mod loaders and runtimes installed beside a game hold their own text, such
# as an AutoTranslator cache, never the game's.
TOOL_DIRS = {"bepinex", "melonloader", "monobleedingedge"}


def candidate(name):
    """How the census treats a game file: 'read', 'open', 'wolf', 'dump' or None."""
    path = PurePosixPath(name)
    folders = [part.casefold() for part in path.parts[:-1]]
    if any(
        part in SKIPPED_DIRS
        or part in TOOL_DIRS
        or part.endswith("_burstdebuginformation_donotship")
        for part in folders
    ):
        return None
    suffix = path.suffix.casefold()
    if suffix in TEXT:
        return "read"
    if suffix in OPENED:
        return "open"
    # Wolf keeps text in BasicData and MapData, or one Data archive; the
    # others hold pictures and sound, often gigabytes of them.
    if suffix == ".wolf":
        return "wolf" if path.stem.casefold() in WOLF_TEXT else None
    if suffix in WOLF and "data" in folders:
        return "wolf"
    if path.name.casefold() in NEEDS_DUMP_NAMES or suffix in NEEDS_DUMP:
        return "dump"
    # Unreal keeps its archives under Paks; NW.js and Electron ship Chromium's
    # own .pak resources, whose Japanese is the browser's, not the game's.
    if suffix == ".pak" and "paks" in folders:
        return "dump"
    return None


def decode_text(data):
    """Text in the encodings games use; None when it is not text."""
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", "replace")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", "replace")
    if b"\0" in data[:4096]:
        return None
    for encoding in ("utf-8", "cp932"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


# --- Structure of JSON-like trees ---------------------------------------------

_DATABASE = {
    "Actors", "Armors", "Classes", "Enemies", "Items", "Skills", "States",
    "Weapons", "Animations", "Tilesets",
}  # fmt: skip


def rpgmaker_kind(name, prefix):
    """The kind of an RPG Maker data file: prefix 'rpgmaker' for MV/MZ JSON,
    'rgss' for XP, VX and Ace data."""
    stem = PurePosixPath(name).stem
    if re.fullmatch(r"Map\d+", stem):
        return prefix + ":map"
    named = {
        "MapInfos": "map_infos",
        "CommonEvents": "common_events",
        "Troops": "troops",
        "System": "system",
        "Scripts": "scripts",
    }
    if stem in named:
        return prefix + ":" + named[stem]
    if stem in _DATABASE:
        return prefix + ":database:" + stem
    return None


def _segment(value):
    """'*' for a list element; event commands keep their code, and plugin
    commands their plugin or keyword, which are identifiers."""
    if isinstance(value, dict):
        code, parameters = value.get("code"), value.get("parameters")
        if type(code) is int and isinstance(parameters, list):
            if code == 357 and parameters:
                return f"*[code=357:{parameters[0]}]"
            if code == 356 and parameters and isinstance(parameters[0], str):
                return f"*[code=356:{parameters[0].split(' ', 1)[0]}]"
            return f"*[code={code}]"
    return "*"


_KEY = re.compile(r"[A-Za-z_@$][A-Za-z0-9_@$.-]{0,63}")


def walk(value, location=(), field=(), positional=False):
    """String leaves of a JSON-like tree as (location, field, text). Lists and
    objects keyed by data (numbers, non-ASCII names) become '*' in the field;
    an event command's parameters keep their positions, which mean different
    things (MZ's speaker name is parameter 4, the face file parameter 0)."""
    if isinstance(value, str):
        yield "/".join(location), "/".join(field), value
    elif isinstance(value, list):
        for index, child in enumerate(value):
            segment = str(index) if positional else _segment(child)
            yield from walk(child, (*location, str(index)), (*field, segment))
    elif isinstance(value, dict):
        command = _segment(value) != "*"
        data = any(not _KEY.fullmatch(str(key)) for key in value)
        for key, child in value.items():
            segment = "*" if data else str(key)
            yield from walk(
                child,
                (*location, str(key)),
                (*field, segment),
                positional=command and key == "parameters",
            )


# --- Readers: each returns rows of (kind, location, field, text) ---------------


def _json(text):
    try:
        return json.loads(text)
    except ValueError:
        return None


def read_json(name, text):
    document = _json(text)
    if document is None:
        return None
    folders = [part.casefold() for part in PurePosixPath(name).parts[:-1]]
    kind = rpgmaker_kind(name, "rpgmaker") if "data" in folders else None
    if kind is None:
        kind = "json:package" if PurePosixPath(name).name == "package.json" else "json"
    return [(kind, *row) for row in walk(document)]


def read_plugins(text):
    """MV/MZ js/plugins.js: the $plugins array, with struct parameters that
    are themselves JSON read in place."""
    start, end = text.find("["), text.rfind("]")
    plugins = _json(text[start : end + 1]) if 0 <= start < end else None
    if not isinstance(plugins, list):
        return None
    rows = []
    for index, plugin in enumerate(plugins):
        if not isinstance(plugin, dict):
            continue
        name = str(plugin.get("name", ""))
        if isinstance(plugin.get("description"), str):
            rows.append(
                (f"{index}/description", f"{name}/description", plugin["description"])
            )
        parameters = plugin.get("parameters")
        for key, raw in (parameters if isinstance(parameters, dict) else {}).items():
            key = key if _KEY.fullmatch(key) else "*"
            rows.extend(_parameter(raw, f"{index}/parameters/{key}", f"{name}/{key}"))
    return [("rpgmaker:plugins", *row) for row in rows]


def _parameter(raw, location, field):
    parsed = _json(raw) if isinstance(raw, str) and raw[:1] in "[{" else None
    if isinstance(parsed, (list, dict)):
        for child_location, child_field, text in walk(parsed):
            yield from _parameter(
                text, f"{location}/{child_location}", f"{field}/{child_field}"
            )
    elif isinstance(raw, str):
        yield location, field, raw


_REGEX_BEFORE = set("(,=:[!&|?{};+-*%<>~^")
_REGEX_WORDS = {"return", "typeof", "case", "do", "else", "in", "of", "void"}


def lex_code(text, ruby=False, multiline=False):
    """Comments and string literals of JavaScript-like or Ruby code as
    (offset, field, text). Text past the point the lexer can't follow, such
    as KAG3's closing END_OF_TJS_SCRIPT, comes last as 'unparsed', which no
    rule sets aside."""
    out = []
    i, length, last, word = 0, len(text), "", ""
    while i < length:
        char = text[i]
        line_start = i == 0 or text[i - 1] == "\n"
        if ruby and line_start and text.startswith("=begin", i):
            end = text.find("\n=end", i)
            end = length if end < 0 else end + 5
            out.append((i, "comment", text[i:end]))
            i = end
            continue
        if ruby and char == "#" or not ruby and text.startswith("//", i):
            end = text.find("\n", i)
            end = length if end < 0 else end
            out.append((i, "comment", text[i:end]))
            i = end
            continue
        if not ruby and text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                return out + [(i, "unparsed", text[i:])]
            out.append((i, "comment", text[i : end + 2]))
            i = end + 2
            continue
        if char in "'\"" or char == "`" and not ruby:
            j = i + 1
            while j < length and text[j] != char:
                if text[j] == "\\":
                    j += 1
                elif text[j] == "\n" and char != "`" and not ruby and not multiline:
                    return out + [(i, "unparsed", text[i:])]
                j += 1
            if j >= length:
                return out + [(i, "unparsed", text[i:])]
            out.append((i, "string", text[i + 1 : j]))
            i, last, word = j + 1, "x", ""
            continue
        if char == "/" and (last in _REGEX_BEFORE or not last or word in _REGEX_WORDS):
            j, inside = i + 1, False
            while j < length and (inside or text[j] != "/"):
                if text[j] == "\\":
                    j += 1
                elif text[j] in "[]":
                    inside = text[j] == "["
                elif text[j] == "\n":
                    return out + [(i, "unparsed", text[i:])]
                j += 1
            if j >= length:
                return out + [(i, "unparsed", text[i:])]
            out.append((i, "regex", text[i + 1 : j]))
            i, last, word = j + 1, "x", ""
            continue
        if not char.isspace():
            if char.isalnum() or char in "_$":
                word = word + char if last == "w" else char
                last = "w"
            else:
                last, word = char, ""
            if _WORD.match(char):
                end = i
                while end < length and _RUN.match(text[end]):
                    end += 1
                out.append((i, "code", text[i:end]))
                i = end
                continue
        i += 1
    return out


def read_code(kind, text, ruby=False, multiline=False):
    """Code's comments and strings; TJS strings, unlike JavaScript's, may
    span lines."""
    return [
        (kind, str(offset), field, value)
        for offset, field, value in lex_code(text, ruby, multiline)
    ]


def read_kag(text):
    """KiriKiri and TyranoScript scenarios: comments, labels and their save
    titles, speaker lines, tag attributes and body text; iscript blocks are
    read as code."""
    rows, script, start = [], None, 0
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if script is not None:
            if re.match(r"\[endscript\]|@endscript", stripped):
                rows += [
                    ("script:ks", f"{start}:{offset}", field, value)
                    for _kind, offset, field, value in read_code("script:ks", script)
                ]
                script = None
            else:
                script += line + "\n"
            continue
        if re.match(r"\[iscript\]|@iscript", stripped):
            script, start = "", number
        elif stripped.startswith(";"):
            rows.append(("script:ks", str(number), "comment", stripped))
        elif stripped.startswith("*"):
            label, _bar, title = stripped.partition("|")
            rows.append(("script:ks", str(number), "label", label))
            if title:
                rows.append(("script:ks", str(number), "label_title", title))
        elif stripped.startswith("#"):
            rows.append(("script:ks", str(number), "speaker", stripped[1:]))
        elif stripped.startswith("@"):
            rows += _tag(f"{number}:0", stripped[1:])
        else:
            position = 0
            for match in re.finditer(r"\[([^\]]*)\]", line):
                if line[position : match.start()].strip():
                    rows.append(
                        (
                            "script:ks",
                            f"{number}:{position}",
                            "body",
                            line[position : match.start()],
                        )
                    )
                rows += _tag(f"{number}:{match.start()}", match.group(1))
                position = match.end()
            if line[position:].strip():
                rows.append(
                    ("script:ks", f"{number}:{position}", "body", line[position:])
                )
    return rows


def _tag(location, content):
    name, _space, attributes = content.strip().partition(" ")
    rows = [("script:ks", location, "tag", name)]
    for match in re.finditer(r"([\w.-]+)\s*=\s*(\"[^\"]*\"|'[^']*'|\S+)", attributes):
        attribute = match.group(1) if _KEY.fullmatch(match.group(1)) else "*"
        rows.append(
            (
                "script:ks",
                location,
                f"tag:{name}.{attribute}",
                match.group(2).strip("\"'"),
            )
        )
    return rows


def read_renpy(text):
    """Ren'Py scripts: say statements, other statements' strings and comments."""
    tokens = lex_code(text, ruby=True)
    rows = []
    for offset, field, value in tokens:
        if field == "string":
            before = text[text.rfind("\n", 0, offset) + 1 : offset].strip()
            if not before or re.fullmatch(r"[\w.]+", before):
                field = "say"
            else:
                head = re.match(r"[A-Za-z_$]+", before)
                field = "stmt:" + (head.group() if head else "expr")
        rows.append(("script:rpy", str(offset), field, value))
    return rows


def read_html(text):
    rows = []
    pattern = r"<title>(.*?)</title>|<!--(.*?)-->|<script[^>]*>(.*?)</script>|>([^<]+)<"
    for match in re.finditer(pattern, text, re.DOTALL | re.IGNORECASE):
        if match.group(1) is not None:
            rows.append(("html", str(match.start()), "title", match.group(1)))
        elif match.group(2) is not None:
            rows.append(("html", str(match.start()), "comment", match.group(2)))
        elif match.group(3) is not None:
            rows += [
                ("html", f"{match.start()}:{offset}", "script:" + field, value)
                for _kind, offset, field, value in read_code("html", match.group(3))
            ]
        else:
            rows.append(("html", str(match.start()), "text", match.group(4)))
    return rows


def read_lines(kind, text, separator=None):
    rows = []
    for number, line in enumerate(text.splitlines(), 1):
        for column, cell in enumerate(line.split(separator) if separator else [line]):
            rows.append(
                (
                    kind,
                    f"{number}:{column}",
                    f"column:{column}" if separator else "line",
                    cell,
                )
            )
    return rows


def read_yaml(kind, text):
    """Decoded dumps such as an AssetRipper export: each value keyed by the
    path of keys above it, with list items wildcarded."""
    rows, stack = [], []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.match(r"(\s*)(-\s+)?([^:'\"]+?):(?:\s+(.*))?$", line)
        if not match:
            path = "/".join(key for _indent, key in stack)
            rows.append((kind, str(number), path, line.strip()))
            continue
        indent = len(match.group(1))
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if match.group(2):
            stack.append((indent, "*"))
            indent += len(match.group(2))
        key = match.group(3).strip()
        stack.append((indent, key if _KEY.fullmatch(key) else "*"))
        if match.group(4):
            rows.append(
                (kind, str(number), "/".join(k for _i, k in stack), match.group(4))
            )
    return rows


def marshal_tree(value):
    """A Ruby Marshal value from util.ace.ruby_marshal as plain data:
    objects become their instance variables without '@', so RPG Maker XP,
    VX and Ace read like MV/MZ JSON."""
    name = type(value).__name__
    if name == "RString":
        return (
            value.data
            if value.encoding is None
            else value.data.decode("utf-8", "replace")
        )
    if name == "RObject":
        return {
            key.lstrip("@"): marshal_tree(child) for key, child in value.ivars.items()
        }
    if name == "RHash":
        return {
            str(marshal_tree(key)): marshal_tree(child) for key, child in value.pairs
        }
    if name == "Symbol":
        return value.text
    if isinstance(value, list):
        return [marshal_tree(child) for child in value]
    return value if isinstance(value, (int, float, bool)) or value is None else None


def read_marshal(name, tree):
    kind = rpgmaker_kind(name, "rgss") or "rgss:data"
    if kind != "rgss:scripts":
        return [(kind, *row) for row in walk(tree)]
    rows = []
    for index, entry in enumerate(tree if isinstance(tree, list) else []):
        if isinstance(entry, list) and len(entry) >= 3 and isinstance(entry[2], bytes):
            try:
                code = zlib.decompress(entry[2]).decode("utf-8", "replace")
            except zlib.error:
                continue
            rows += [
                (kind, f"{index}:{offset}", field, text)
                for _kind, offset, field, text in read_code(kind, code, ruby=True)
            ]
    return rows


def read_wolf(document):
    """A WolfDawn strings-extract document: each line's source text, typed
    by WolfDawn as a message, choice, narration or UI string. WolfDawn
    already keeps only translatable strings."""
    if not isinstance(document, dict) or not isinstance(document.get("kind"), str):
        return None
    kind = "wolf:" + document["kind"]
    rows = []

    def lines(value, location):
        if isinstance(value, dict):
            if isinstance(value.get("source"), str):
                source = str(value.get("speaker_src") or "line")
                field = "message" if source.startswith("literal_line") else source
                rows.append((kind, location, field, value["source"]))
                return
            for key, child in value.items():
                lines(child, f"{location}/{key}" if location else str(key))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                lines(child, f"{location}/{index}")

    lines(document, "")
    return rows


def read(name, data):
    """The rows of one readable game file, or None when it cannot be read."""
    suffix = PurePosixPath(name).suffix.casefold()
    text = decode_text(data)
    if text is None:
        return None
    lowered = "/" + name.casefold()
    if lowered.endswith("/js/plugins.js"):
        return read_plugins(text)
    if suffix == ".json":
        return read_json(name, text)
    if suffix == ".js":
        return read_code("js:plugin" if "/plugins/" in lowered else "js", text)
    if suffix == ".tjs":
        return read_code("script:tjs", text, multiline=True)
    if suffix == ".ks":
        return read_kag(text)
    if suffix == ".rpy":
        return read_renpy(text)
    if suffix in {".html", ".htm"}:
        return read_html(text)
    if suffix in {".csv", ".tsv"}:
        return read_lines("text" + suffix, text, "," if suffix == ".csv" else "\t")
    # Readmes, credits and version notes beside the game are never shown in
    # it; NScripter keeps its numbered scripts (0.txt) there, which count.
    if (
        "/" not in name
        and suffix in {".txt", ".md"}
        and not PurePosixPath(name).stem.isdigit()
    ):
        return read_lines("document", text)
    if suffix in {".yaml", ".yml", ".asset", ".prefab", ".unity"}:
        return read_yaml("dump:yaml", text)
    return read_lines("text" + suffix, text)


# --- Containers the census opens itself -----------------------------------------


def asar_members(data):
    """(name, offset, size) of each file packed in an Electron ASAR archive."""
    if len(data) < 16 or struct.unpack_from("<I", data, 0)[0] != 4:
        raise ValueError("Not an ASAR archive.")
    header_size = struct.unpack_from("<I", data, 4)[0]
    json_size = struct.unpack_from("<I", data, 12)[0]
    header = json.loads(data[16 : 16 + json_size].rstrip(b"\0").decode("utf-8"))
    base = 8 + header_size

    def files(node, prefix):
        for key, entry in (node.get("files") or {}).items():
            if "files" in entry:
                yield from files(entry, prefix + key + "/")
            elif not entry.get("unpacked"):
                yield (
                    prefix + key,
                    base + int(entry.get("offset", 0)),
                    int(entry.get("size", 0)),
                )

    return list(files(header, ""))


XP3_MAGIC = b"XP3\r\n \n\x1a\x8b\x67\x01"


def xp3_members(data):
    """(name, segments, adler32) of each file in a KiriKiri XP3 archive."""
    if not data.startswith(XP3_MAGIC):
        raise ValueError("Not an XP3 archive.")
    offset = struct.unpack_from("<Q", data, len(XP3_MAGIC))[0]
    if data[offset] & 0x80:
        first, after = struct.unpack_from("<QQ", data, offset + 1)
        offset = after or first
    method = data[offset] & 0x7F
    if method == 1:
        size = struct.unpack_from("<Q", data, offset + 1)[0]
        index = zlib.decompress(data[offset + 17 : offset + 17 + size])
    elif method == 0:
        size = struct.unpack_from("<Q", data, offset + 1)[0]
        index = data[offset + 9 : offset + 9 + size]
    else:
        raise ValueError("Unsupported XP3 index.")
    position, members = 0, []
    while position < len(index):
        size = struct.unpack_from("<Q", index, position + 4)[0]
        body = index[position + 12 : position + 12 + size]
        name, segments, adler, inner = None, [], None, 0
        while inner < len(body):
            tag = body[inner : inner + 4]
            length = struct.unpack_from("<Q", body, inner + 4)[0]
            chunk = body[inner + 12 : inner + 12 + length]
            if tag == b"info":
                count = struct.unpack_from("<H", chunk, 20)[0]
                name = chunk[22 : 22 + count * 2].decode("utf-16le")
            elif tag == b"segm":
                segments = [
                    struct.unpack_from("<IQQQ", chunk, at)
                    for at in range(0, len(chunk), 28)
                ]
            elif tag == b"adlr":
                adler = struct.unpack_from("<I", chunk, 0)[0]
            inner += 12 + length
        if name:
            members.append((name.replace("\\", "/"), segments, adler))
        position += 12 + size
    return members


def xp3_read(data, segments, adler):
    """One XP3 member's bytes; ValueError when its checksum shows encryption."""
    content = b"".join(
        zlib.decompress(data[start : start + stored])
        if flags & 7 == 1
        else data[start : start + stored]
        for flags, start, _original, stored in segments
    )
    if adler is not None and zlib.adler32(content) != adler:
        raise ValueError("The XP3 archive is encrypted.")
    return content


# --- Scope rules ------------------------------------------------------------------

REASONS = {"asset_name", "identifier", "comment", "script_code", "not_displayed"}
# Code files may be named by a rule; a map, event or scene never can.
CODE_KINDS = {"js", "js:plugin", "script:tjs", "rgss:scripts", "html"}

_RM = ("rpgmaker", "rgss")
_ASSET_PARAMETERS = (
    "101/parameters/0", "231/parameters/1", "261/parameters/0", "283/parameters/*",
    "284/parameters/0", "322/parameters/*", "323/parameters/1",
    "241/parameters/0/name", "245/parameters/0/name", "249/parameters/0/name",
    "250/parameters/0/name",
)  # fmt: skip
_ASSET_KEYS = (
    "characterName", "faceName", "battlerName", "parallaxName", "battleback1Name",
    "battleback2Name", "title1Name", "title2Name", "tilesetNames", "windowskin",
    "character_name", "face_name", "battler_name", "parallax_name", "battleback1_name",
    "battleback2_name", "title1_name", "title2_name", "tileset_names", "animation1_name",
    "animation2_name", "panorama_name", "fog_name", "icon_name",
)  # fmt: skip


def _both(rules):
    return [(f"{prefix}:{kind}", *rest) for prefix in _RM for kind, *rest in rules]


# (kind pattern, field pattern, reason): what the tool sets aside itself,
# from Len's never-translate lists.
BUILT_IN = [
    *_both(
        [
            ("*", "**/*[code=118]/**", "identifier"),
            ("*", "**/*[code=119]/**", "identifier"),
            ("*", "**/*[code=111]/**", "script_code"),
            ("*", "**/*[code=108]/**", "comment"),
            ("*", "**/*[code=408]/**", "comment"),
            # A choice branch's label mirrors its 102 choice; the engine
            # branches on the index.
            ("*", "**/*[code=402]/parameters/1", "identifier"),
            *(
                ("*", "**/*[code={}]/{}".format(*path.split("/", 1)), "asset_name")
                for path in _ASSET_PARAMETERS
            ),
            *(("*", f"**/{key}", "asset_name") for key in _ASSET_KEYS),
            *(("*", f"**/{key}/*", "asset_name") for key in _ASSET_KEYS),
            *(
                ("*", f"**/{key}/name", "asset_name")
                for key in ("bgm", "bgs", "me", "se")
            ),
            ("*", "**/sounds/*/name", "asset_name"),
            ("*", "**/*Bgm/name", "asset_name"),
            ("*", "**/*Me/name", "asset_name"),
            ("*", "**/*_bgm/name", "asset_name"),
            ("*", "**/*_me/name", "asset_name"),
            ("*", "**/*_se/name", "asset_name"),
            ("system", "switches/*", "identifier"),
            ("system", "variables/*", "identifier"),
            ("map", "events/*/name", "identifier"),
            ("common_events", "*/name", "identifier"),
            ("troops", "*/name", "identifier"),
            ("database:Animations", "*/name", "identifier"),
            ("database:Tilesets", "*/name", "identifier"),
            ("map_infos", "*/name", "identifier"),
        ]
    ),
    ("rpgmaker:plugins", "*/description", "not_displayed"),
    ("document", "line", "not_displayed"),
    # Unity Addressables' catalog lists asset addresses.
    ("json", "m_InternalIds/*", "identifier"),
    ("*", "comment", "comment"),
    ("*", "script:comment", "comment"),
    ("*", "label", "identifier"),
    ("script:ks", "tag", "identifier"),
    *(
        ("script:ks", f"tag:*.{attribute}", "asset_name")
        for attribute in ("storage", "graphic", "file", "folder", "src")
    ),
    ("script:ks", "tag:*.target", "identifier"),
]

# Text the player reads, which no rule sets aside.
PROTECTED = [
    *_both(
        [
            ("*", "**/*[code=401]/**"),
            ("*", "**/*[code=405]/**"),
            ("*", "**/*[code=102]/**"),
            ("*", "**/*[code=101]/parameters/4"),
            ("*", "**/*[code=320]/**"),
            ("*", "**/*[code=324]/**"),
            ("*", "**/*[code=325]/**"),
            ("database:*", "*/name"),
            ("database:*", "*/description"),
            ("database:*", "*/message*"),
            ("database:*", "*/nickname"),
            ("database:*", "*/profile"),
            ("map", "displayName"),
            ("map", "display_name"),
            ("system", "gameTitle"),
            ("system", "game_title"),
            ("system", "terms/**"),
            ("system", "words/**"),
        ]
    ),
    ("wolf:*", "**"),
    ("script:ks", "body"),
    ("script:ks", "speaker"),
    ("script:ks", "label_title"),
    ("script:rpy", "say"),
    ("html", "title"),
    ("*", "unparsed"),
]


@lru_cache(maxsize=4096)
def _glob(pattern):
    return re.compile(".*".join(re.escape(part) for part in pattern.split("*")))


def _kind(pattern, kind):
    return _glob(pattern).fullmatch(kind) is not None


def matches(pattern, field):
    """Field patterns compare whole segments: '**' spans any number of them,
    '*' alone any one, and '*' inside a segment any characters, so
    '*[code=357:*]' is every plugin command."""
    want, have = pattern.split("/"), field.split("/")

    @cache
    def at(i, j):
        if i == len(want):
            return j == len(have)
        if want[i] == "**":
            return any(at(i + 1, k) for k in range(j, len(have) + 1))
        if j == len(have):
            return False
        part = want[i]
        if part == "*" or part == have[j]:
            return at(i + 1, j + 1)
        if "*" in part and _glob(part).fullmatch(have[j]):
            return at(i + 1, j + 1)
        return False

    return at(0, 0)


@lru_cache(maxsize=65536)
def protected(kind, field):
    return any(_kind(k, kind) and matches(f, field) for k, f in PROTECTED)


def rules_input(value, fields):
    """The assistant's scope rules, given the census's {kind: fields}. A rule
    can't name an index, can name a file only for code, and is refused when
    it would cover text the player reads."""
    if value is None:
        return []
    if not isinstance(value, dict) or set(value) != {"version", "rules"}:
        raise ValueError("Scope rules are an object with version 1 and rules.")
    if value["version"] != 1 or not isinstance(value["rules"], list):
        raise ValueError("Scope rules require version 1 and a list of rules.")
    result = []
    for index, rule in enumerate(value["rules"], 1):
        if not isinstance(rule, dict) or set(rule) - {
            "kind",
            "field",
            "reason",
            "file",
        }:
            raise ValueError(
                f"Scope rule {index} accepts kind, field, reason and, for code, file."
            )
        kind, field, reason = rule.get("kind"), rule.get("field"), rule.get("reason")
        if kind not in fields:
            raise ValueError(
                f"Scope rule {index} names a kind the census did not find."
            )
        # Census fields never hold a map, event or scene index, so a rule that
        # matches one applies to every map, event and scene alike.
        if not isinstance(field, str) or not any(
            matches(field, have) for have in fields[kind]
        ):
            raise ValueError(
                f"Scope rule {index} needs a field pattern that matches a census field of its kind."
            )
        if reason not in REASONS:
            raise ValueError(
                f"Scope rule {index} needs a reason: {', '.join(sorted(REASONS))}."
            )
        if "file" in rule and (
            kind not in CODE_KINDS or not isinstance(rule["file"], str)
        ):
            raise ValueError(f"Scope rule {index} can name a file only for code.")
        if any(protected(kind, have) and matches(field, have) for have in fields[kind]):
            raise ValueError(
                f"Scope rule {index} covers text the player reads, which is always translated."
            )
        result.append(
            {
                key: rule[key]
                for key in ("kind", "field", "reason", "file")
                if key in rule
            }
        )
    return result


# --- Census entries and coverage ------------------------------------------------


def entries(rows, name, source):
    """Census entries for one file's rows: only strings that hold Japanese."""
    result = []
    for kind, location, field, text in rows or []:
        found = runs(text)
        if found:
            result.append(
                {
                    "file": name,
                    "location": location,
                    "kind": kind,
                    "field": field,
                    "runs": found,
                    "source": source,
                }
            )
    return result


def fields(census):
    result = {}
    for entry in census["entries"]:
        result.setdefault(entry["kind"], set()).add(entry["field"])
    return result


def coverage(census, sources, glossary, rules):
    """The census's runs as extracted (in a unit or the glossary), set aside
    by a built-in or assistant rule, or uncovered; protected text is never
    set aside."""
    # Occurrences count: a line extracted once doesn't cover the same words
    # in another map, so each census run takes one matching unit run. Units
    # hold the game's text exactly, so their runs match the census's.
    available = Counter(run for text in sources for run in runs(text))
    unit_runs = set(available)
    terms = {run for term in glossary for run in runs(term)}

    def extracted(run):
        if run in terms:
            return True
        if available[run] > 0:
            available[run] -= 1
            return True
        return False

    every = [
        *({"kind": k, "field": f, "reason": r, "by": "tool"} for k, f, r in BUILT_IN),
        *({**rule, "by": "assistant"} for rule in rules),
    ]
    chosen = {}

    def rule_for(entry):
        key = (entry["kind"], entry["field"], entry["file"])
        if key not in chosen:
            chosen[key] = None
            if not protected(entry["kind"], entry["field"]):
                for rule in every:
                    if (
                        _kind(rule["kind"], entry["kind"])
                        and rule.get("file", entry["file"]) == entry["file"]
                        and matches(rule["field"], entry["field"])
                    ):
                        chosen[key] = rule
                        break
        return chosen[key]

    counts, aside, uncovered, traced = Counter(), Counter(), [], set()
    for entry in census["entries"]:
        traced.update(entry["runs"])
        missing = [run for run in entry["runs"] if not extracted(run)]
        counts["runs"] += len(entry["runs"])
        counts["extracted"] += len(entry["runs"]) - len(missing)
        if not missing:
            continue
        rule = rule_for(entry)
        if rule is not None:
            counts["set_aside"] += len(missing)
            aside[
                (
                    rule["by"],
                    rule["kind"],
                    rule["field"],
                    rule["reason"],
                    rule.get("file"),
                )
            ] += len(missing)
        else:
            counts["uncovered"] += len(missing)
            uncovered.append({**entry, "runs": missing})
    return {
        "runs": counts["runs"],
        "extracted": counts["extracted"],
        "set_aside": counts["set_aside"],
        "uncovered": counts["uncovered"],
        # Units holding Japanese the census never saw: a container it can't
        # read, whose text needs the assistant's decoded dump.
        "untraced": len(unit_runs - traced),
        "unit_runs": len(unit_runs),
        "rules": [
            {
                "by": by,
                "kind": kind,
                "field": field,
                "reason": reason,
                **({"file": file} if file else {}),
                "runs": count,
            }
            for (by, kind, field, reason, file), count in sorted(
                aside.items(), key=lambda item: tuple(map(str, item[0]))
            )
        ],
    }, uncovered


def summary(uncovered, limit=20):
    """Uncovered runs counted by kind and field, never by text."""
    counts = Counter()
    for entry in uncovered:
        counts[(entry["kind"], entry["field"])] += len(entry["runs"])
    return [
        {"kind": kind, "field": field, "runs": count}
        for (kind, field), count in counts.most_common(limit)
    ]


# --- The scan -------------------------------------------------------------------


def wanted(names):
    """The game files a census reads, opens or hands to WolfDawn."""
    return [name for name in names if candidate(name) in {"read", "open", "wolf"}]


def scan(names, load, decoders, decoded=None, progress=lambda _message: None):
    """The census of a game's files.

    names: every file in the untranslated game; load(name) -> bytes for the
    wanted ones. decoders: marshal(data) -> Marshal value, rgssad(data) ->
    [(name, data)] and wolf(names) -> [(name, document)] for WolfDawn files.
    decoded: (name, data) pairs of the assistant's decoded dump, if any.
    """
    found, unreadable, opened, needs_dump, wolf = [], [], [], [], []

    def take(name, data, source):
        if PurePosixPath(name).suffix.casefold() in {".rxdata", ".rvdata", ".rvdata2"}:
            try:
                rows = read_marshal(name, marshal_tree(decoders.marshal(data)))
            except ValueError:
                rows = None
        else:
            rows = read(name, data)
        if rows is None:
            unreadable.append(name)
        else:
            found.extend(entries(rows, name, source))

    for count, name in enumerate(names, 1):
        how = candidate(name)
        if count % 500 == 0:
            progress(f"Read {count:,} of {len(names):,} files")
        if how == "dump":
            needs_dump.append(name)
        elif how == "wolf":
            wolf.append(name)
        elif how == "read":
            take(name, load(name), "tool")
        elif how == "open":
            suffix = PurePosixPath(name).suffix.casefold()
            data = load(name)
            try:
                if suffix == ".asar":
                    members = [
                        (f"{name}/{member}", data[offset : offset + size])
                        for member, offset, size in asar_members(data)
                    ]
                elif suffix == ".xp3":
                    members = [
                        (f"{name}/{member}", xp3_read(data, segments, adler))
                        for member, segments, adler in xp3_members(data)
                        if candidate(member) == "read"
                    ]
                else:
                    members = [
                        (f"{name}/{member}", body)
                        for member, body in decoders.rgssad(data)
                    ]
            except ValueError, zlib.error, struct.error, KeyError, IndexError:
                needs_dump.append(name)
                continue
            opened.append(name)
            for member, body in members:
                if candidate(member) == "read":
                    take(member, body, "tool")
    if wolf:
        progress("Reading Wolf data with WolfDawn")
        archives = [name for name in wolf if name.casefold().endswith(".wolf")]
        try:
            documents = decoders.wolf(wolf)
        except ValueError:
            needs_dump += archives
            documents = []
        else:
            opened += archives
        for name, document in documents:
            rows = read_wolf(document)
            if rows is None:
                unreadable.append(name)
            else:
                found.extend(entries(rows, name, "tool"))
    for name, data in decoded or []:
        if candidate(name) == "read":
            take(name, data, "assistant_dump")
    return {
        "version": VERSION,
        "entries": found,
        "unreadable": sorted(unreadable),
        "opened": sorted(opened),
        "needs_dump": sorted(needs_dump),
        "decoded": decoded is not None,
    }
