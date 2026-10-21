"""Patterns an Other event text investigation writes for one game's text that
no built-in handler or registered entry captures.

A pattern is a regular expression searched in a command's original text; its
last capturing group is the text translated, and only a capture holding
Japanese is. A handler names an MZ plugin command and its plain-text
arguments. They are engine options, so each run and Batch profile keeps them.
"""

import json
import re
from functools import lru_cache
from re import _constants, _parser

from util.source_text import holds_source

# Event code -> the engine option holding its patterns.
CODE_KEYS = {355: "CUSTOM_355655", 655: "CUSTOM_355655", 356: "CUSTOM_356", 108: "CUSTOM_108"}
HANDLER_KEY = "CUSTOM_357"
LABELS = {
    "CUSTOM_355655": "Custom script text patterns",
    "CUSTOM_356": "Custom plugin command patterns",
    "CUSTOM_108": "Custom comment patterns",
    HANDLER_KEY: "Custom plugin command handlers",
}
KEYS = tuple(LABELS)
SPACING = ("space", "nbsp", "underscore")
QUOTES = "'\"`"
_REPEATS = (_constants.MAX_REPEAT, _constants.MIN_REPEAT, _constants.POSSESSIVE_REPEAT)


def _text(value, label, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{label} must be text of 1 to {limit} characters.")
    return value


def _parts(value):
    if isinstance(value, _parser.SubPattern):
        yield value
    elif isinstance(value, (tuple, list)):
        for item in value:
            yield from _parts(item)


def _nested(items, inside=False):
    """Whether an unbounded repeat sits inside another, as in (a+)+, which
    can take exponential time on a line it almost matches."""
    for op, value in items:
        if op in _REPEATS:
            _low, high, body = value
            unbounded = high == _constants.MAXREPEAT
            if (unbounded and inside) or _nested(body, inside or unbounded):
                return True
        elif any(_nested(part, inside) for part in _parts(value)):
            return True
    return False


@lru_cache(maxsize=512)
def compiled(regex):
    return re.compile(regex)


def _pattern(entry, key):
    script = key == "CUSTOM_355655"
    required = {"name", "regex"} if script else {"name", "regex", "spacing"}
    allowed = required | {"script"} if script else required
    if not isinstance(entry, dict) or not required <= set(entry) <= allowed:
        raise ValueError(
            f"{LABELS[key]} take name, regex and "
            + ("an optional script." if script else "spacing.")
        )
    name = _text(entry["name"], "A custom pattern's name", 80).strip()
    regex = _text(entry["regex"], f"Custom pattern {name}'s regex", 1000)
    try:
        pattern = compiled(regex)
        tree = _parser.parse(regex)
    except (re.error, RecursionError) as exc:
        raise ValueError(f"Custom pattern {name}'s regex is invalid: {exc}.") from None
    if not pattern.groups:
        raise ValueError(
            f"Custom pattern {name}'s regex needs a capturing group around the text."
        )
    if _nested(tree):
        raise ValueError(
            f"Custom pattern {name}'s regex repeats a repeated part, as in (a+)+; "
            "bound the outer repeat, as in (a+){1,5}, or write it without nesting."
        )
    value = {"name": name, "regex": regex}
    if "script" in entry:
        value["script"] = _text(entry["script"], f"Custom pattern {name}'s script", 1000)
    if "spacing" in entry:
        if entry["spacing"] not in SPACING:
            raise ValueError(
                f"Custom pattern {name}'s spacing must be space, nbsp or underscore."
            )
        value["spacing"] = entry["spacing"]
    return value


def _handler(entry):
    if not isinstance(entry, dict) or set(entry) != {"plugin", "command", "args"}:
        raise ValueError("Custom plugin command handlers take plugin, command and args.")
    plugin = _text(entry["plugin"], "A custom handler's plugin", 200)
    command = _text(entry["command"], f"Custom handler {plugin}'s command", 200)
    args = entry["args"]
    if not isinstance(args, list) or not 1 <= len(args) <= 20:
        raise ValueError(f"Custom handler {plugin} {command} needs 1 to 20 argument keys.")
    for arg in args:
        _text(arg, f"Custom handler {plugin} {command}'s argument key", 200)
    if len(set(args)) != len(args):
        raise ValueError(f"Custom handler {plugin} {command} repeats an argument key.")
    return {"plugin": plugin, "command": command, "args": sorted(args)}


def normalize(key, entries):
    """The validated entries of one custom option, in a stable order."""
    label = LABELS[key]
    if not isinstance(entries, list) or len(entries) > 100:
        raise ValueError(f"{label} must be a list of at most 100 entries.")
    if key == HANDLER_KEY:
        values = sorted(
            map(_handler, entries), key=lambda item: (item["plugin"], item["command"])
        )
        identities = [(item["plugin"], item["command"]) for item in values]
    else:
        values = sorted(
            (_pattern(entry, key) for entry in entries),
            key=lambda item: item["name"],
        )
        identities = [item["name"] for item in values]
    if len(set(identities)) != len(identities):
        raise ValueError(f"{label} must each have their own name.")
    return values


def captures(entries, text, header, wanted):
    """Each pattern's (entry, start, end) capture in `text` that `wanted`
    accepts. `header` is the first line of the script a 355/655 line belongs
    to, which a pattern's script must be in."""
    found = []
    if not isinstance(text, str):
        return found
    for entry in entries:
        if "script" in entry and entry["script"] not in header:
            continue
        pattern = compiled(entry["regex"])
        match = pattern.search(text)
        if match and match.start(pattern.groups) >= 0:
            start, end = match.span(pattern.groups)
            if start < end and wanted(text[start:end]):
                found.append((entry, start, end))
    return found


def capture(entries, text, header, wanted):
    """The first pattern capturing translatable text in `text`, or None."""
    found = captures(entries, text, header, wanted)
    return found[0] if found else None


def quote(text, start, end):
    """The JavaScript quote around a script capture, or ''."""
    if 0 < start and end < len(text) and text[start - 1] == text[end] in QUOTES:
        return text[end]
    return ""


def join_words(text, spacing):
    """Keeps a translation's words together the way its plugin reads them."""
    if spacing == "space":
        return text
    return text.replace(" ", "\u00a0" if spacing == "nbsp" else "_")


def structured(value):
    """Whether a plugin argument is a struct or list its plugin parses."""
    if not value.lstrip().startswith(("{", "[")):
        return False
    try:
        return isinstance(json.loads(value), (dict, list))
    except ValueError:
        return False


def problems(options, documents):
    """Why custom options would not translate the selected event files'
    original text as intended: a pattern capturing no Japanese, two patterns
    taking one command, a script capture holding its own quotes, or a handler
    argument holding structured data. Each document is one event file's
    commands in order."""
    patterns = {key: options.get(key) or [] for key in set(CODE_KEYS.values())}
    handlers = options.get(HANDLER_KEY) or []
    used = {(key, entry["name"]) for key, entries in patterns.items() for entry in entries}
    used |= {(HANDLER_KEY, item["plugin"] + " " + item["command"]) for item in handlers}
    found = set()
    for commands in documents:
        header = ""
        for command in commands:
            code, parameters = command.get("code"), command.get("parameters")
            if not isinstance(parameters, list) or not parameters:
                continue
            text = parameters[0]
            if code == 355:
                header = text if isinstance(text, str) else ""
            key = CODE_KEYS.get(code)
            matches = captures(patterns[key], text, header, holds_source) if key else []
            for entry, start, end in matches:
                used.discard((key, entry["name"]))
                inner = text[start:end]
                quoted = len(inner) > 1 and inner[0] == inner[-1] in QUOTES
                if key == "CUSTOM_355655" and quoted:
                    found.add(
                        f"Custom pattern {entry['name']} captures the quotes around "
                        f"{inner}; capture only the text inside them."
                    )
            if len(matches) > 1:
                found.add(
                    "Custom patterns "
                    + " and ".join(entry["name"] for entry, _start, _end in matches)
                    + f" both capture text in {text}; let one pattern take each command."
                )
            if code != 357 or len(parameters) < 4 or not isinstance(parameters[3], dict):
                continue
            for item in handlers:
                if parameters[:2] != [item["plugin"], item["command"]]:
                    continue
                identity = item["plugin"] + " " + item["command"]
                for arg in item["args"]:
                    value = parameters[3].get(arg)
                    if isinstance(value, str) and structured(value):
                        found.add(
                            f"Custom handler {identity}'s argument {arg} holds "
                            "structured data, which the engine cannot translate in place."
                        )
                    elif holds_source(value):
                        used.discard((HANDLER_KEY, identity))
    for key, identity in used:
        found.add(
            f"Custom handler {identity} translates no Japanese argument in the selected event files."
            if key == HANDLER_KEY
            else f"Custom pattern {identity} captures no Japanese text in the selected event files."
        )
    return sorted(found)
