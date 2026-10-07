"""Literal inventories and exact replacement boundaries, without evaluating code."""

import json
import re
import shutil
import subprocess
from pathlib import Path

from dazedtl.translation.files import digest, unique_object

JAPANESE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
# The start of a JSON object or array, for values that fail to decode.
OPAQUE = re.compile(r'^\s*(?:\{\s*"|\[\s*["\[{])')
TOKENS = re.compile(
    r"\$\{[^}]*\}|#\{[^}]*\}|\\(?:[A-Za-z]+\[[^\]]*\]|[A-Za-z.!|^><{}$]|[nrtbfv0])|%(?:\d+\$)?[-+0 #]*\d*(?:\.\d+)?[a-zA-Z%]|\{\d+\}"
)


def decode(value):
    return json.loads(
        value,
        object_pairs_hook=unique_object,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite JSON")),
    )


def leaves(value, path=(), depth=0):
    """Keep a decode marker for every serialization layer, including encoded
    scalars. Each leaf says whether it is opaque: text inside data that looks
    like JSON but does not decode, which the app never edits."""
    if depth > 24:
        raise ValueError(
            "A setting is nested more than 24 levels deep, so it cannot be checked."
        )
    if isinstance(value, str):
        try:
            inner = decode(value)
        except ValueError, TypeError:
            # A script such as `[{}];` also looks like JSON; it stays one leaf
            # the app protects, so the rest of the file is still checked.
            yield list(path), value, bool(re.match(OPAQUE, value))
        else:
            if isinstance(inner, (dict, list, str)):
                yield from leaves(inner, (*path, "$decode"), depth + 1)
            else:
                yield list(path), value, False
    elif isinstance(value, dict):
        for key, inner in value.items():
            yield from leaves(inner, (*path, key), depth + 1)
    elif isinstance(value, list):
        for index, inner in enumerate(value):
            yield from leaves(inner, (*path, index), depth + 1)


def reason(issue):
    """A parser's complaint about a file, in words for the person reading it.
    Validation keeps the parser's own message for the assistant's repairs."""
    line = re.search(r"\((\d+):\d+\)$", issue)
    if line:
        return f"Its JavaScript has a syntax error on line {line[1]}."
    if issue.startswith("JSON syntax: "):
        line = re.search(r"line (\d+)", issue)
        return "Its JSON has a syntax error" + (f" on line {line[1]}." if line else ".")
    return issue


def replace_leaf(value, path, target):
    if not path:
        if not isinstance(value, str):
            raise ValueError("Only existing string leaves can change.")
        return target
    key, *rest = path
    if key == "$decode":
        if not isinstance(value, str):
            raise ValueError("Serialization layers changed.")
        decoded = decode(value)
        changed = replace_leaf(decoded, rest, target)
        return json.dumps(changed, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, dict) and key in value:
        value = dict(value)
        value[key] = replace_leaf(value[key], rest, target)
        return value
    if isinstance(value, list) and type(key) is int and 0 <= key < len(value):
        value = list(value)
        value[key] = replace_leaf(value[key], rest, target)
        return value
    raise ValueError("The decoded parameter path changed.")


def same_tree(before, after, changes, path=(), depth=0):
    """Validate keys, order, types, serialization and only approved decoded leaves."""
    if depth > 24 or type(before) is not type(after):
        raise ValueError("Parameter types or serialization layers changed.")
    if isinstance(before, str):
        try:
            left = decode(before)
        except ValueError:
            left = None
        if isinstance(left, (dict, list, str)):
            try:
                right = decode(after)
            except ValueError as exc:
                raise ValueError("An encoded parameter no longer decodes.") from exc
            same_tree(left, right, changes, (*path, "$decode"), depth + 1)
        elif tuple(path) in changes:
            if after != changes[tuple(path)]:
                raise ValueError(
                    "A decoded replacement differs from its reported target."
                )
        elif before != after:
            raise ValueError("An unapproved decoded parameter leaf changed.")
    elif isinstance(before, dict):
        if list(before) != list(after):
            raise ValueError("Parameter keys or ordering changed.")
        for key in before:
            same_tree(before[key], after[key], changes, (*path, key), depth + 1)
    elif isinstance(before, list):
        if len(before) != len(after):
            raise ValueError("Parameter list length changed.")
        for index, left in enumerate(before):
            same_tree(left, after[index], changes, (*path, index), depth + 1)
    elif before != after:
        raise ValueError("A non-text parameter value changed.")


class Documents:
    def parse(self, files):
        js = [row for row in files if row["kind"] != "json"]
        result = {}
        if js:
            node = shutil.which("node")
            if not node:
                raise ValueError(
                    "Install the application's supported Node runtime to validate JavaScript without executing it."
                )
            response = subprocess.run(
                [node, str(Path(__file__).with_name("syntax.cjs"))],
                input=json.dumps({"files": js}, ensure_ascii=False).encode(),
                capture_output=True,
                timeout=max(10, len(js) * 6),
                check=False,
            )
            if response.returncode:
                raise ValueError(
                    "The local syntax parser is unavailable. Check the application dependencies."
                )
            result.update((row["path"], row) for row in decode(response.stdout))
        for row in files:
            if row["kind"] == "json":
                try:
                    result[row["path"]] = json_document(row["path"], row["source"])
                except ValueError as exc:
                    result[row["path"]] = {
                        "path": row["path"],
                        "issues": ["JSON syntax: " + str(exc)],
                        "literals": [],
                        "plugins": [],
                    }
        return result


def json_document(path, source):
    value = decode(source)
    literals, cursor = [], 0
    decoder = json.JSONDecoder(object_pairs_hook=unique_object)

    def space():
        nonlocal cursor
        while cursor < len(source) and source[cursor].isspace():
            cursor += 1

    def walk(logical):
        nonlocal cursor
        space()
        start = cursor
        if source[cursor] == "{":
            cursor += 1
            space()
            if source[cursor] != "}":
                while True:
                    space()
                    key, end = decoder.raw_decode(source, cursor)
                    cursor = end
                    space()
                    cursor += 1
                    walk([*logical, key])
                    space()
                    if source[cursor] == "}":
                        break
                    cursor += 1
            cursor += 1
        elif source[cursor] == "[":
            cursor += 1
            space()
            index = 0
            if source[cursor] != "]":
                while True:
                    walk([*logical, index])
                    index += 1
                    space()
                    if source[cursor] == "]":
                        break
                    cursor += 1
            cursor += 1
        else:
            item, end = decoder.raw_decode(source, cursor)
            cursor = end
            if isinstance(item, str):
                literals.append(
                    {
                        "start": len(source[:start].encode()),
                        "end": len(source[:end].encode()),
                        "raw": source[start:end],
                        "value": item,
                        "path": logical,
                        "kind": "literal",
                        "protected": False,
                        "expressions": [],
                        "line": source[:start].count("\n") + 1,
                    }
                )

    walk([])
    return {
        "path": path,
        "issues": [],
        "literals": literals,
        "plugins": [],
        "value": value,
    }


def occurrences(path, raw, parsed):
    fingerprint = digest(raw)
    rows = []
    for index, literal in enumerate(parsed["literals"]):
        values = leaves(literal["value"])
        for logical, value, opaque in values:
            if not JAPANESE.search(value):
                continue
            identity = digest(
                {
                    "path": path,
                    "hash": fingerprint,
                    "span": [literal["start"], literal["end"]],
                    "logical": logical,
                }
            )[:24]
            rows.append(
                {
                    "id": identity,
                    "file": path,
                    "token": index,
                    "logical": logical,
                    "value": value,
                    "line": literal["line"],
                    "start": literal["start"],
                    "end": literal["end"],
                    "protected": literal["protected"] or opaque,
                    "kind": literal["kind"],
                }
            )
    return rows


def validate(raw, candidate, original, current, approved, targets):
    if current["issues"]:
        raise ValueError("Syntax check failed: " + current["issues"][0])
    left, right = original["literals"], current["literals"]
    if len(left) != len(right):
        raise ValueError(
            "Literal inventory changed; unrelated code or new literals are not allowed."
        )
    by_token = {}
    for row in approved:
        if row["id"] not in targets:
            continue
        target = targets[row["id"]]
        if not isinstance(target, str) or len(target) > 100_000:
            raise ValueError("Provide a bounded decoded target string.")
        if TOKENS.findall(row["value"]) != TOKENS.findall(target) or any(
            row["value"].count(char) != target.count(char) for char in "\n\t\r"
        ):
            raise ValueError(
                "Control codes, interpolation or placeholders changed: " + row["id"]
            )
        if JAPANESE.search(target):
            raise ValueError(
                "Approved occurrence still contains Japanese; revise it or explicitly retain/exclude it."
            )
        by_token.setdefault(row["token"], {})[tuple(row["logical"])] = target
    before, after, bpos, apos = [], [], 0, 0
    for index, (a, b) in enumerate(zip(left, right)):
        if (
            a["kind"] != b["kind"]
            or a.get("expressions") != b.get("expressions")
            or a["protected"] != b["protected"]
        ):
            raise ValueError("Literal kind, embedded code or semantic context changed.")
        before.append(raw[bpos : a["start"]])
        after.append(candidate[apos : b["start"]])
        if index in by_token:
            if a["protected"]:
                raise ValueError("A protected code literal cannot be translated.")
            if a["kind"] == "default":
                if "\n" in b["value"]:
                    raise ValueError(
                        "Metadata defaults must remain on their original line."
                    )
                same_tree(a["value"], b["value"], by_token[index])
            else:
                if a["raw"][0] != b["raw"][0] or a["raw"][-1] != b["raw"][-1]:
                    raise ValueError("Literal quote style changed.")
                same_tree(a["value"], b["value"], by_token[index])
            before.append(b"<approved-text>")
            after.append(b"<approved-text>")
        else:
            before.append(raw[a["start"] : a["end"]])
            after.append(candidate[b["start"] : b["end"]])
        bpos, apos = a["end"], b["end"]
    before.append(raw[bpos:])
    after.append(candidate[apos:])
    if b"".join(before) != b"".join(after):
        raise ValueError(
            "Bytes outside approved literal spans changed. Restore unrelated code and formatting."
        )
    return {
        "boundaries": True,
        "protectedLookups": True,
        "structure": True,
        "syntax": True,
        "decodedTargets": True,
        "controlTokens": True,
        "residual": True,
    }
