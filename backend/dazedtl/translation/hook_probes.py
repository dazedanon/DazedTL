"""Proves a runtime hook shows English for every exported line before an
Assistant-led patch that carries one packages: DazedTL writes each line as the
game shows it, every placeholder the game fills filled with a value no line
holds (`hook-probes`); the game's own self-test looks each one up through the
hook's store and gate and writes what it would show; `hook-probes --check`
judges those answers and binds them to the export and the plugin's files; and
packaging refuses until every line comes back as clean English (`require`).

A whole-string key a game fills before showing it, as Labyrinth City Asylum
filled `報酬{0}ゴールドをもらった。` with string.Format, misses once filled
while its unfilled lookup hits; the filled probe is what tells them apart.

A project translated before this rule packages as before until its next new
translations (`required_from_now`), which reopen injection, QA and the patch.
"""

import json
import re
import unicodedata
from itertools import count
from pathlib import Path

from util.languages import UNTRANSLATED_TEXT

from dazedtl.storage import write_bytes, write_json

from .files import digest, project_path, read_evidence, read_json
from .project import WORK
from .results import EXPORT, exported_translations

# The probe list and the self-test's answers live in the game's own DazedTL
# work folder, which no patch carries and no player has, so the self-test
# runs only on the translator's computer. Each line is one flat JSON object,
# which a plugin reads with its translation files' reader.
PROBES = WORK + "/work/hook-probes.jsonl"
RESULTS = WORK + "/work/hook-results.jsonl"
# The project's records: the judged answers, and the mark that new
# translations reached the export since this rule began.
EVIDENCE = "hook-probes.json"
REQUIRED = "hook-probes-required.json"
# Raise when what makes an answer clean changes (problem), so answers judged
# by older rules are judged again.
VERSION = 1
# Where a patch's BepInEx plugins live; a patch carrying one looks the game's
# text up at run time.
PLUGINS = "bepinex/plugins/"
# How many unclean lines the helper names, and the evidence keeps.
NAMED = 20
KEPT = 50

# A .NET composite format item, {index[,alignment][:format]}, which the code
# fills before the text reaches the screen; doubled braces are literal ones.
FORMAT_ITEM = re.compile(r"(?<!\{)\{(\d+)(?:,(-?\d+))?(?::([^{}]*))?\}(?!\})")
# Markup a text component reads as it is, never a value the code fills in:
# a rich-text tag such as <color=red> and a backslash code such as \C[2].
MARKUP = re.compile(r"<[^<>]+>|\\.*", re.DOTALL)
UNTRANSLATED = re.compile(UNTRANSLATED_TEXT)
DIGITS = re.compile(r"\d+", re.ASCII)
# The first value a placeholder takes: three digits, so no value holds
# another and a thousands separator stays out of most formats.
FIRST_VALUE = 101

# Why the patch waits, as (the assistant's next step, the user's reason).
UNCHECKED = (
    (
        "Prove the plugin shows English for every line before packaging: run hook-probes, "
        "start the game once so the plugin's self-test answers each probe, then run hook-probes --check."
    ),
    "Your assistant checks in the game that every line shows English first.",
)
OUTDATED = (
    (
        "The text export or the plugin's files changed since hook-probes --check read the self-test's answers. "
        "Run hook-probes, start the game once so the self-test answers the current probes, then run hook-probes --check."
    ),
    "Your assistant checks again in the game that every line shows English, since the text or the plugin changed.",
)


def covered(paths):
    """Whether a patch of runtime *paths* looks the game's English up at run
    time, which the self-test must then prove: it carries a BepInEx plugin."""
    return any(
        path.casefold().startswith(PLUGINS) and path.casefold().endswith(".dll")
        for path in paths
    )


def required_from_now(workspace, project_id):
    """Marks that new translations reached the project's export, after which
    a covered patch waits for the self-test."""
    path = _record(workspace, project_id, REQUIRED)
    if not path.exists():
        write_json(path, {"version": 1})


def write(source, paths, held):
    """Writes the probe list of the game at *source* from its current export
    (one probe per translated unit); *held* gives the compiled requests of
    fingerprints, which hold each unit's protected tokens."""
    _covering(paths)
    _units, probed, content = _current(source, held)
    if not probed:
        raise ValueError(
            "Export the translated units first: the probes are the export's lines as the game shows them."
        )
    write_bytes(project_path(source, PROBES, exists=False), content)
    return {
        "probes": PROBES,
        "lines": len(probed),
        "results": RESULTS,
        "next": "Start the game once with the plugin installed: its self-test reads "
        + PROBES
        + " and writes what the game would show for each line to "
        + RESULTS
        + ". Then run hook-probes --check.",
    }


def check(workspace, project_id, source, paths, held):
    """Judges the self-test's answers to the current probe list and saves the
    judgement, bound to the export and the plugin's files, for `require`.
    Refuses answers to another probe list, or older than a plugin file."""
    _covering(paths)
    units, probed, content = _current(source, held)
    if not probed:
        raise ValueError(
            "Export the translated units first: the probes are the export's lines as the game shows them."
        )
    listed = project_path(source, PROBES, exists=False)
    if not listed.is_file() or listed.read_bytes() != content:
        raise ValueError(
            "The probe list is missing or was written for an earlier export. "
            "Run hook-probes, then start the game once so its self-test answers it."
        )
    path = project_path(source, RESULTS, exists=False)
    if not path.is_file():
        raise ValueError(
            "No self-test answers yet: start the game once with the plugin installed, so its self-test writes "
            + RESULTS
            + ", then run hook-probes --check."
        )
    written = path.stat()
    answered, answers = _answers(path.read_bytes())
    if answered != digest(content):
        raise ValueError(
            "The self-test answered an earlier probe list. Start the game again so it answers this one."
        )
    plugin = _plugin_files(source, paths)
    files = _bound(source, [*_export_files(source), *plugin])
    if any(files[relative][1] > written.st_mtime_ns for relative in plugin):
        raise ValueError(
            "The plugin's files changed after the self-test ran. Start the game again so it answers with them."
        )
    unclean = [
        {
            "unit": units[identity]["source_id"],
            "source": units[identity]["source"],
            "problem": reason,
        }
        for identity, probe in probed.items()
        if (
            reason := (
                problem(probe, answers[identity])
                if identity in answers
                else "the self-test gave no answer for it"
            )
        )
    ]
    write_json(
        _record(workspace, project_id, EVIDENCE),
        {
            "version": VERSION,
            "files": files,
            "lines": len(probed),
            "unclean": len(unclean),
            "problems": unclean[:KEPT],
        },
    )
    return {
        "lines": len(probed),
        "unclean": len(unclean),
        "problems": unclean[:NAMED],
        "next": (
            "Fix these lines in the plugin's store, start the game again so its self-test answers, then run hook-probes --check."
            if unclean
            else "Every line comes back as clean English; packaging no longer waits for the self-test."
        ),
    }


def require(workspace, project_id, source, paths):
    """Why a patch of runtime *paths* can't package yet, as (the assistant's
    next step, the user's reason), or None: it carries a BepInEx plugin, new
    translations reached the export since this rule began, and the saved
    judgement is missing, out of date, or found lines without clean English."""
    if not covered(paths) or not _record(workspace, project_id, REQUIRED).exists():
        return None
    try:
        evidence = read_json(_record(workspace, project_id, EVIDENCE))
    except OSError, ValueError:
        evidence = None
    if not isinstance(evidence, dict) or evidence.get("version") != VERSION:
        return UNCHECKED
    try:
        current = {*_export_files(source), *_plugin_files(source, paths)}
        if current != set(evidence["files"]) or not _unchanged(
            source, evidence["files"]
        ):
            return OUTDATED
    except OSError, ValueError:
        return OUTDATED
    if not evidence["unclean"]:
        return None
    total = evidence["unclean"]
    lines = "line" if total == 1 else "lines"
    named = "; ".join(
        f"{line['unit']} {_quoted(line['source'])}: {line['problem']}"
        for line in evidence["problems"][:5]
    )
    return (
        (
            f"The game's self-test found {total:,} {lines} without clean English: {named}. "
            "Fix them in the plugin's store, start the game again so its self-test answers, then run hook-probes --check."
        ),
        f"The game would show {total:,} {lines} without clean English, such as "
        f"{_quoted(evidence['problems'][0]['source'])}. Your assistant fixes "
        + ("it" if total == 1 else "them")
        + " first.",
    )


def probes(units):
    """One probe per unit, by unit ID: its speaker, the text the game shows
    (`text`), each placeholder filled, and the values the English must hold
    (`values`). *units* are the export's rows, each with its `id`, `source`,
    `speaker`, optional `translation` and protected `tokens`. A placeholder is
    a format item of the source, or a token that is no markup; repeated, it
    takes the same value, and no unit's source or translation holds one."""
    units = list(units)
    # A value is digits, so only a run of digits can hold one; full-width
    # digits read as the ASCII ones they show.
    runs = [
        run
        for unit in units
        for key in ("source", "translation")
        if isinstance(unit.get(key), str)
        for run in DIGITS.findall(unicodedata.normalize("NFKC", unit[key]))
    ]
    free = _Free(runs)
    return {
        unit["id"]: {"speaker": unit.get("speaker"), **_filled(unit, free)}
        for unit in units
    }


def problem(probe, shown):
    """Why the game's answer *shown* for *probe* is no clean English, in the
    assistant's terms, or None: no English (a miss), a carriage return, text
    still untranslated by the skill's class, or a filled value it drops. A
    line holding no untranslated text needs no English of its own."""
    if shown is None:
        if not UNTRANSLATED.search(probe["text"]):
            return None
        return "the game finds no English for it"
    if "\r" in shown:
        return "its English holds a carriage return"
    if marks := UNTRANSLATED.findall(shown):
        return "its English still shows " + "".join(dict.fromkeys(marks))
    if lost := [value for value in probe["values"] if value not in shown]:
        return "its English drops the value the game fills in (" + ", ".join(lost) + ")"
    return None


class _Free:
    """The values no run of digits in *runs* holds, from FIRST_VALUE up,
    found as a probe first needs them."""

    def __init__(self, runs):
        self.runs = runs
        self.values = []
        self.candidates = map(str, count(FIRST_VALUE))

    def __getitem__(self, index):
        while len(self.values) <= index:
            value = next(self.candidates)
            if not any(value in run for run in self.runs if len(run) >= len(value)):
                self.values.append(value)
        return self.values[index]


def _filled(unit, free):
    values = {}
    shown = []

    def value(key):
        if key not in values:
            values[key] = free[len(values)]
        return values[key]

    def item(match):
        index, alignment, spec = match.groups()
        text = _formatted(value(("item", index)), spec)
        shown.append(text)
        width = int(alignment or 0)
        return text.rjust(width) if width > 0 else text.ljust(-width)

    text = FORMAT_ITEM.sub(item, unit["source"])
    for token in dict.fromkeys(unit.get("tokens") or ()):
        if FORMAT_ITEM.fullmatch(token) or MARKUP.fullmatch(token) or token not in text:
            continue
        shown.append(value(("token", token)))
        text = text.replace(token, shown[-1])
    return {"text": text, "values": list(dict.fromkeys(shown))}


def _formatted(value, spec):
    """*value*, a whole number's digits, as .NET shows it by a standard
    numeric format *spec* (D, F, N or X, with an optional precision); any
    other spec shows the digits as they are."""
    kind, digits = (spec[0].upper(), spec[1:]) if spec else ("", "")
    if not digits.isdigit() and digits:
        return value
    number = int(value)
    if kind == "D":
        return value.zfill(int(digits or 0))
    if kind == "F":
        return f"{number:.{int(digits or 2)}f}"
    if kind == "N":
        return f"{number:,.{int(digits or 2)}f}"
    if kind == "X":
        return format(number, spec[0]).zfill(int(digits or 0))
    return value


def _covering(paths):
    if not covered(paths):
        raise ValueError(
            "The patch carries no BepInEx plugin, so nothing looks its text up at run time and packaging needs no probes."
        )


def _current(source, held):
    """The export's translated rows and their probes, by row ID, and the
    probe list's bytes."""
    rows = exported_translations(source)
    requests = held({row["request_sha256"] for row in rows if "request_sha256" in row})
    units = {}
    for row in rows:
        request = requests.get(row.get("request_sha256")) or {}
        rule = request.get("constraints", {}).get(row["source_id"], {})
        units[row["id"]] = {**row, "tokens": rule.get("tokens", [])}
    probed = probes(units.values())
    lines = [
        json.dumps(
            {
                "id": identity,
                "unit": units[identity]["source_id"],
                **({"speaker": probe["speaker"]} if probe["speaker"] else {}),
                "text": probe["text"],
            },
            ensure_ascii=False,
        )
        for identity, probe in probed.items()
    ]
    return units, probed, "".join(line + "\n" for line in lines).encode("utf-8")


def _answers(content):
    """The probe list's SHA-256 the self-test answered and what it would
    show for each probe it answered, None for a miss."""
    try:
        lines = [
            json.loads(line)
            for line in content.decode("utf-8-sig").splitlines()
            if line.strip()
        ]
    except ValueError as error:
        raise ValueError(
            "The self-test's answers can't be read; start the game again so it writes them anew."
        ) from error
    if (
        not lines
        or not isinstance(lines[0], dict)
        or not isinstance(lines[0].get("probes"), str)
    ):
        raise ValueError(
            "The self-test's answers name no probe list; start the game again with a current plugin."
        )
    answers = {}
    for line in lines[1:]:
        if not isinstance(line, dict) or not isinstance(line.get("id"), str):
            continue
        shown = line.get("shown")
        answers[line["id"]] = shown if isinstance(shown, str) else None
    return lines[0]["probes"], answers


def _export_files(source):
    index = read_json(project_path(source, EXPORT))
    parts = index.get("parts") if isinstance(index, dict) else None
    return [EXPORT, *(parts if isinstance(parts, list) else ())]


def _plugin_files(source, paths):
    """The patch's files in its BepInEx plugins folder, which a lookup reads."""
    return [
        relative
        for relative in paths
        if relative.casefold().startswith(PLUGINS)
        and project_path(source, relative, exists=False).is_file()
    ]


def _bound(source, paths):
    files = {}
    for relative in dict.fromkeys(paths):
        stat, sha256 = read_evidence(project_path(source, relative))
        files[relative] = [stat.st_size, stat.st_mtime_ns, sha256]
    return files


def _unchanged(source, files):
    """Whether each bound file holds what it held: its size and time first,
    its content where those changed."""
    for relative, (size, mtime, sha256) in files.items():
        path = project_path(source, relative)
        stat = path.stat()
        if [stat.st_size, stat.st_mtime_ns] != [size, mtime] and read_evidence(path)[
            1
        ] != sha256:
            return False
    return True


def _record(workspace, project_id, name):
    return Path(workspace) / "translation/projects" / project_id / name


def _quoted(text):
    line = re.sub(r"\r\n|\r|\n", "⏎", text)
    return "「" + (line if len(line) <= 30 else line[:30] + "…") + "」"
