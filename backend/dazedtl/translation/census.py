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
    ".unity", ".rxdata", ".rvdata", ".rvdata2", ".yst",
}  # fmt: skip
OPENED = {".rgssad", ".rgss2a", ".rgss3a", ".asar", ".xp3"}
WOLF = {".mps", ".dat", ".project"}
WOLF_TEXT = {"basicdata", "mapdata", "data"}
NEEDS_DUMP = {
    ".ybn", ".pck", ".utoc", ".ucas", ".assets", ".bundle", ".unity3d",
    ".dts", ".nsa", ".sar", ".dxa", ".pfs",
}  # fmt: skip
# Archives whose index the census reads: only those holding scripts or text
# need a decoded dump, so pictures, music and voices are never decoded.
INDEXED = {".ypf"}
NEEDS_DUMP_NAMES = {"data.win", "game.unx", "globalgamemanagers", "scene.pck"}
SKIPPED_DIRS = {".git", ".dazedtl", "save", "saves", "locales", "swiftshader"}
# Mod loaders and runtimes installed beside a game hold their own text, such
# as an AutoTranslator cache, never the game's.
TOOL_DIRS = {"bepinex", "melonloader", "monobleedingedge"}


def candidate(name):
    """How the census treats a game file: 'read', 'open', 'index', 'wolf',
    'dump' or None."""
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
    if suffix in INDEXED:
        return "index"
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


def read_lines(kind, text):
    return [
        (kind, f"{number}:0", "line", line)
        for number, line in enumerate(text.splitlines(), 1)
    ]


_KANA = re.compile("[ぁ-ゖァ-ヺｦ-ｯｱ-ﾝ]")
_HAN = re.compile("[㐀-䶿一-鿿豈-﫿]")
_MARKUP = re.compile(r"\{[^{}]*\}|<[^<>]*>|\[[^\[\]]*\]")
# Script code also separates with commas, inside quotes and brackets.
_NESTED = re.compile(r'"[^"]*"|\'[^\']*\'|\([^()]*\)|\[[^\[\]]*\]')
# Traditional and Simplified Chinese forms that Japanese text doesn't use.
_CHINESE = set(
    "們们这说从还让你嗎吗呢吧啊您妳麼體發戰獸擇對會說與讓從點變關國學氣實數萬當應兒經歡聽覺樂寫戲讀擊將傳處餘隨寶"
)


@lru_cache(maxsize=65536)
def _japanese_charset(character):
    try:
        character.encode("cp932")
    except UnicodeEncodeError:
        return False
    return True


def _language(cells):
    """'chinese' or 'latin' for a column translating Japanese into another
    language: kana, outside markup such as {name} placeholders, only in the
    odd cell a translator left untranslated, and Chinese only where its
    characters show it."""
    text = [_MARKUP.sub("", cell) for cell in cells if cell.strip()]
    if not text or sum(1 for cell in text if _KANA.search(cell)) > len(text) // 20:
        return None
    if any(_HAN.search(cell) for cell in text):
        chinese = any(
            character in _CHINESE
            or (_HAN.match(character) and not _japanese_charset(character))
            for cell in text
            for character in cell
        )
        return "chinese" if chinese else None
    latin = sum(1 for cell in text if re.search("[A-Za-z]", cell))
    return "latin" if len(text) >= 2 and latin >= 0.8 * len(text) else None


def read_table(kind, text, separator=None):
    """Lines of comma or tab separated cells, by column. A table translating
    its Japanese first column into another language names that column
    table:key, and a Chinese column other_language: Japanese runs can't tell
    its characters apart."""
    lines = text.splitlines()
    if separator is None:
        filled = [line for line in lines if line.strip()]
        separator = next(
            (
                mark
                for mark in ("\t", ",")
                if len(filled) >= 2
                and sum(mark in _NESTED.sub("", line) for line in filled)
                >= 0.6 * len(filled)
            ),
            None,
        )
        if separator is None:
            return read_lines(kind, text)
    rows = [line.split(separator) for line in lines]
    width = max(map(len, rows), default=0)
    languages = [None] + [
        _language([row[column] for row in rows if len(row) > column])
        for column in range(1, width)
    ]
    table = any(languages) and any(_KANA.search(row[0]) for row in rows)

    def field(column):
        if not table:
            return f"column:{column}"
        if column == 0:
            return "table:key"
        if languages[column] == "chinese":
            return "other_language"
        return f"table:column:{column}"

    return [
        (kind, f"{number}:{column}", field(column), cell)
        for number, row in enumerate(rows, 1)
        for column, cell in enumerate(row)
    ]


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
        return read_table("text" + suffix, text, "," if suffix == ".csv" else "\t")
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
    if suffix == ".yst":
        return read_lines("script:yst", text)
    return read_table("text" + suffix, text)


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


def _swapped(*pairs):
    table = list(range(256))
    for i, j in pairs:
        table[i], table[j] = table[j], table[i]
    return table


# YU-RIS stores each name's length through a byte permutation, which
# version 500 changed (after Len's yuris_decompiler).
_YPF_SWAPS = ((6, 53), (9, 11), (12, 16), (13, 19), (21, 27), (28, 30), (32, 35), (38, 41), (44, 47))  # fmt: skip
_YPF_LENGTHS = _swapped((3, 72), (17, 25), (46, 50), *_YPF_SWAPS)
_YPF_LENGTHS_500 = _swapped((3, 10), (17, 24), (20, 46), *_YPF_SWAPS)


def ypf_members(head):
    """The file names in a YU-RIS YPF archive's index, or None for another
    kind of file under that name, such as a video; head(size) reads the
    archive's first bytes, so the archive itself is never loaded."""
    first = head(16)
    if not first.startswith(b"YPF\0"):
        return None
    _magic, version, count, size = struct.unpack("<4sIII", first)
    end = size if version >= 300 else size + 32
    index = head(end)
    lengths = _YPF_LENGTHS_500 if version == 500 else _YPF_LENGTHS
    key = 0xFF ^ {290: 0x40, 500: 0x36}.get(version, 0)
    tail = 22 if version >= 470 else 18
    position, names = 32, []
    for _ in range(count):
        length = lengths[index[position + 4] ^ 0xFF]
        raw = bytes(byte ^ key for byte in index[position + 5 : position + 5 + length])
        names.append(raw.decode("cp932").replace("\\", "/"))
        position += 5 + length + tail
    if position != end:
        raise ValueError("Unsupported YPF index.")
    return names


# --- Scope rules ------------------------------------------------------------------

REASONS = {
    "asset_name", "identifier", "comment", "script_code", "not_displayed",
    "other_language",
}  # fmt: skip

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
    ("*", "other_language", "other_language"),
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


def rules_input(value, fields, files=None):
    """The assistant's scope rules, given the census's {kind: fields} and
    {kind: files}. A rule sets aside a field across the game, optionally only
    in files matching a path pattern or only exact runs (values), and is
    refused when its field holds text the player reads in a format DazedTL
    knows."""
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
            "values",
        }:
            raise ValueError(
                f"Scope rule {index} accepts kind, field, reason, file and values."
            )
        kind, field, reason = rule.get("kind"), rule.get("field"), rule.get("reason")
        if kind not in fields:
            raise ValueError(
                f"Scope rule {index} names a kind the census did not find."
            )
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
            not isinstance(rule["file"], str)
            or not any(
                matches(rule["file"], have) for have in (files or {}).get(kind, ())
            )
        ):
            raise ValueError(
                f"Scope rule {index} needs a file pattern that matches a census file of its kind."
            )
        if "values" in rule and (
            not isinstance(rule["values"], list)
            or not rule["values"]
            or any(runs(item) != [item] for item in rule["values"])
        ):
            raise ValueError(
                f"Scope rule {index} needs values that are each one Japanese run as the census counts it."
            )
        if any(protected(kind, have) and matches(field, have) for have in fields[kind]):
            raise ValueError(
                f"Scope rule {index} covers text the player reads, which is always translated."
            )
        result.append(
            {
                key: rule[key]
                for key in ("kind", "field", "reason", "file", "values")
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


def files(census):
    result = {}
    for entry in census["entries"]:
        result.setdefault(entry["kind"], set()).add(entry["file"])
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
        *(
            {**rule, "by": "assistant", "values": frozenset(rule["values"])}
            if "values" in rule
            else {**rule, "by": "assistant"}
            for rule in rules
        ),
    ]
    chosen = {}

    def rule_for(entry, run):
        key = (entry["kind"], entry["field"], entry["file"])
        if key not in chosen:
            chosen[key] = (
                []
                if protected(entry["kind"], entry["field"])
                else [
                    index
                    for index, rule in enumerate(every)
                    if _kind(rule["kind"], entry["kind"])
                    and matches(rule.get("file", entry["file"]), entry["file"])
                    and matches(rule["field"], entry["field"])
                ]
            )
        for index in chosen[key]:
            if run in every[index].get("values", (run,)):
                return index
        return None

    counts, aside, uncovered, traced = Counter(), Counter(), [], set()
    for entry in census["entries"]:
        traced.update(entry["runs"])
        missing = []
        # Rules first: an identifier a rule sets aside must not use up the
        # unit that covers the same words where the player reads them.
        for run in entry["runs"]:
            if (index := rule_for(entry, run)) is not None:
                counts["set_aside"] += 1
                aside[index] += 1
            elif extracted(run):
                counts["extracted"] += 1
            else:
                missing.append(run)
        counts["runs"] += len(entry["runs"])
        if missing:
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
                "by": every[index]["by"],
                "kind": every[index]["kind"],
                "field": every[index]["field"],
                "reason": every[index]["reason"],
                **({"file": every[index]["file"]} if "file" in every[index] else {}),
                **(
                    {"values": len(every[index]["values"])}
                    if "values" in every[index]
                    else {}
                ),
                "runs": count,
            }
            for index, count in sorted(aside.items())
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


def scan(
    names, load, decoders, decoded=None, progress=lambda _message: None, peek=None
):
    """The census of a game's files.

    names: every file in the untranslated game; load(name) -> bytes for the
    wanted ones, and peek(name, size) -> the first bytes of an indexed
    archive. decoders: marshal(data) -> Marshal value, rgssad(data) ->
    [(name, data)] and wolf(names) -> [(name, document)] for WolfDawn files.
    decoded: (name, data) pairs of the assistant's decoded dump, if any.
    """
    found, unreadable, opened, needs_dump, wolf = [], [], [], [], []
    head = peek or (lambda name, size: load(name)[:size])

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
        elif how == "index":
            try:
                members = ypf_members(lambda size, name=name: head(name, size))
            except ValueError, UnicodeDecodeError, struct.error, IndexError:
                needs_dump.append(name)
                continue
            # Scripts and text need the assistant's dump; an archive of only
            # pictures or sound holds no text.
            if members is None:
                continue
            if any(candidate(member) is not None for member in members):
                needs_dump.append(name)
            else:
                opened.append(name)
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
