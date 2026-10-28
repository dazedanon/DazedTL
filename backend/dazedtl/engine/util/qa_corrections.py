"""What Text QA corrected, as data for measuring translation quality.

Every line a finished Text QA task corrected becomes one correction: where it
is, its source, the text before and after, the reviewer's category and
reason, one coarse kind (KINDS) and, when the same fix repeats across a game,
a recurring group. A game whose task folders are gone keeps the deep reviews
its helpers saved as receipts (`.dazedtl/qa-receipts/<task>`); its text
before and after QA is read from the Git commit that applied them.

Corrections count per 1,000 translated lines. A line is a source text within
one data file, since a file's repeated labels and lines share one
translation, and the lines a game translates are those its inventories list.

Read-only: it reads task folders, receipts and the games' data, and writes
nothing but the export its caller names, which `export_lines` makes: a header
naming the inputs and VERSION, then one row per correction (EXPORT_FIELDS).
"""

from __future__ import annotations

import json
import re
import tempfile
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from util import system
from util.dazedwrap import cells
from util.project_scanner import find_data_folder
from util.qa.records import _changes, _record_maps
from util.qa.selection import _scene_records
from util.qa.storage import _read_json, answers, read_task
from util.rpgmaker_qa_manifest import file_inventory

# The export's form and the rules that label it: raise it when a field, the
# counting unit or a kind's rule changes, so a regression set built from an
# older export is known as one.
VERSION = 1
EXPORT_SCHEMA = "dazedtl-qa-corrections"
KINDS = ("fit/format", "glossary/name", "meaning", "fluency", "legacy output", "other")
# One row per correction of one line: where (file, pointer, identity, every
# place it changed, its scene and line index there), what (source, before,
# after), why (the reviewer's category, reason and evidence), its kind and
# recurring group, whether the game holds it (applied: true, false, or null
# when it holds neither text or only some places hold it) and whether it
# corrects an earlier QA's own correction (requa).
EXPORT_FIELDS = (
    "version", "game", "origin", "task", "focus", "finding", "finding_kind",
    "category", "severity", "family_key", "reason", "evidence", "editorial_basis",
    "editorial_note", "file", "pointer", "identity", "places", "scene",
    "line_index", "scene_lines", "source", "before", "after", "kind",
    "recurring", "applied", "requa",
)
# A recurring group is at least this many near-identical fixes of different lines.
RECURRING_MIN = 3
RECEIPTS = Path(".dazedtl") / "qa-receipts"
# Receipts name no focus; the release inventory reads every line.
RECEIPTS_FOCUS = "release"
DEEP_RESULT = "rpgmaker-qa-deep-result-v"
# Editorial verdicts whose finding stands; findings from before editorial
# review carry none.
KEPT_VERDICTS = frozenset({None, "accept", "revise"})
SOURCE_TREE = Path(__file__).resolve().parents[4]


@dataclass(frozen=True)
class Origin:
    """One set of QA records: a finished task folder, or a receipts run."""

    kind: str
    path: Path
    game: Path
    task: str
    created: str


@dataclass
class Corrections:
    """Each game's corrections and translated lines, with what was read and
    what was left out."""

    games: list[dict[str, Any]] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


# Origins


def _is_task(folder: Path) -> bool:
    return (folder / "task.json").is_file() and (folder / "findings.json").is_file()


def _tasks_below(folder: Path) -> list[Path]:
    return sorted(path.parent for path in folder.rglob("findings.json") if _is_task(path.parent))


def _task_origin(folder: Path) -> Origin | None:
    """A finished task, or None for one still in review."""
    root, task, checkpoint = read_task(folder)
    if checkpoint["stage"] != "complete":
        return None
    return Origin("task", root, Path(task["game_root"]).resolve(), root.name, task["created_at"])


def _receipts_origin(folder: Path) -> Origin:
    """A receipts run, made when its first receipt was written."""
    times = [path.stat().st_mtime for path in folder.glob("*.json") if path.is_file()]
    started = min(times, default=folder.stat().st_mtime)
    created = datetime.fromtimestamp(started, timezone.utc).isoformat()
    return Origin("receipts", folder, folder.parents[2], folder.name, created)


def find_origins(
    targets: Iterable[Path], workspace: Path | None = None
) -> tuple[list[Origin], list[str]]:
    """The QA records *targets* name, oldest first within each game, and
    what was left out and why.

    A target is a task folder; a receipts run; a game folder (one holding
    `.dazedtl`), whose receipts it reads and, given the app's *workspace*,
    the workspace's tasks of that game; or any other folder, searched for
    task folders. A game's receipts are read only when none of its tasks is,
    and none of the task they belong to, since a task's findings are its
    receipts after editorial review.
    """
    tasks: list[Path] = []
    runs: list[Path] = []
    games: set[Path] = set()
    for target in targets:
        folder = Path(target).expanduser().resolve()
        if not folder.is_dir():
            raise ValueError(f"Not a folder: {folder}")
        if _is_task(folder):
            tasks.append(folder)
        elif folder.parent.name == RECEIPTS.name and folder.parent.parent.name == RECEIPTS.parent.name:
            runs.append(folder)
        elif (folder / RECEIPTS.parent).is_dir():
            games.add(folder)
            if (folder / RECEIPTS).is_dir():
                runs += sorted(path for path in (folder / RECEIPTS).iterdir() if path.is_dir())
        else:
            tasks += _tasks_below(folder)
    candidates = [(folder, True) for folder in tasks]
    if workspace is not None:
        candidates += [
            (folder, False) for folder in _tasks_below(Path(workspace).expanduser().resolve())
        ]
    found: dict[Path, Origin] = {}
    skipped = []
    for folder, named in candidates:
        if folder in found:
            continue
        try:
            origin = _task_origin(folder)
        except (OSError, ValueError, KeyError) as exc:
            skipped.append(f"{folder}: not a readable QA task ({exc})")
            continue
        if not named and (origin is None or origin.game not in games):
            continue
        if origin is None:
            skipped.append(f"{folder}: still in review")
            continue
        found[folder] = origin
    with_tasks = {origin.game for origin in found.values()}
    read = {origin.task for origin in found.values()}
    for folder in dict.fromkeys(runs):
        origin = _receipts_origin(folder)
        if origin.game in with_tasks or origin.task in read:
            skipped.append(f"{folder}: receipts of a game whose tasks are read")
        else:
            found[folder] = origin
    ordered = sorted(found.values(), key=lambda origin: (str(origin.game), origin.created, origin.task))
    return ordered, skipped


# Reading


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False) if value else ""


def _spaced(text: str | None) -> str:
    return " ".join((text or "").split())


def _applied(live: str | None, before: str | None, after: str | None) -> bool | None:
    """Whether a line's text *live* is the correction, the text before it, or
    neither (None); fitting may move the correction's line breaks."""
    if live is None:
        return None
    for exact in (True, False):
        same = (lambda a, b: a == b) if exact else (lambda a, b: _spaced(a) == _spaced(b))
        if after is not None and same(live, after):
            return True
        if before is not None and same(live, before):
            return False
    return None


def _split_identity(identity: str) -> tuple[str, str]:
    body = identity.rpartition("@")[0]
    filename, _, pointer = body.partition("#")
    return filename, pointer


def _positions(records: Iterable[dict[str, Any]]) -> dict[str, tuple[str, int, int]]:
    """Each dialogue line's scene, its index there and the scene's length."""
    positions = {}
    for scene, ordered in _scene_records({"records": list(records)}).items():
        for index, record in enumerate(ordered):
            positions[record["identity"]] = (scene, index, len(ordered))
    return positions


def _place(
    origin: Origin,
    finding: dict[str, Any],
    finding_kind: str,
    identity: str,
    record: dict[str, Any] | None,
    positions: dict[str, tuple[str, int, int]],
    *,
    source: str | None,
    before: str | None,
    after: str,
    focus: str | None,
    finding_id: str,
    targets: int,
) -> dict[str, Any]:
    """One corrected place, with what its kind is judged by."""
    filename, pointer = _split_identity(identity)
    if record is not None:
        filename, pointer = record["file"], record["source_pointer"]
    scene, index, length = positions.get(identity, (None, None, None))
    editorial = finding.get("editorial") or {}
    return {
        "origin": origin.kind,
        "task": origin.task,
        "focus": focus,
        "created": origin.created,
        "finding": finding_id,
        "finding_kind": finding_kind,
        "category": finding.get("category") or "",
        "severity": finding.get("severity") or "",
        "family_key": finding.get("family_key") or "",
        "reason": _text(finding.get("summary")) or _text(finding.get("evidence")),
        "evidence": _text(finding.get("evidence")),
        "editorial_basis": _text(finding.get("editorial_basis")),
        "editorial_note": _text(editorial.get("note")),
        "file": filename,
        "pointer": pointer,
        "identity": identity,
        "scene": scene,
        "line_index": index,
        "scene_lines": length,
        "source": record["source"] if record is not None else source,
        "before": record["live"] if record is not None else before,
        "after": after,
        "applied": None,
        "lint_only": bool(finding.get("lint_only")),
        "lint_families": list(finding.get("lint_families") or []),
        "targets": targets,
    }


def _finding_kind(finding: dict[str, Any]) -> str:
    if finding.get("kind") == "scene":
        return "scene"
    if finding.get("lint_only"):
        return "lint"
    if finding.get("sweep_families"):
        return "sweep"
    return "review"


def _read_task(origin: Origin) -> tuple[list[dict[str, Any]], set[tuple[str, str]], dict[str, Any]]:
    """A finished task's corrected places, the lines its inventory lists and
    how it was read."""
    root, task, _checkpoint = read_task(origin.path)
    report = _read_json(root / "findings.json")
    manifest = _read_json(root / "inventory.json")
    records, clusters = _record_maps(manifest)
    positions = _positions(manifest["records"])
    focus = task.get("focus")
    places = []
    for finding in report.get("findings") or []:
        if (finding.get("editorial") or {}).get("verdict") not in KEPT_VERDICTS:
            continue
        if finding.get("kind") == "show-text":
            # A header's name or face: the line it heads is where it shows.
            identity = finding["line_identity"]
            places.append(_place(
                origin, finding, "show-text", identity, None, positions,
                source=(records.get(identity) or {}).get("source"),
                before=finding.get("current"), after=finding["correction"],
                focus=focus, finding_id=finding["id"], targets=1,
            ))
            continue
        changes = _changes(finding)
        targets = sum(len(change["identities"]) for change in changes)
        for change in changes:
            for identity in change["identities"]:
                places.append(_place(
                    origin, finding, _finding_kind(finding), identity, records.get(identity),
                    positions, source=change.get("source"), before=change.get("current"),
                    after=change["correction"], focus=focus, finding_id=finding["id"],
                    targets=targets,
                ))
    # A proposal the user chose applies like a finding, to its cluster's
    # lines a reviewer read (as util.qa.apply.correction_map applies it).
    chosen = answers(root)
    unread = {row["identity"] for row in report.get("not_reviewed") or []}
    for question in report.get("uncertain_playtests") or []:
        cluster = clusters.get(question["id"])
        if chosen.get(question["id"]) != "use" or not question.get("correction") or not cluster:
            continue
        identities = [identity for identity in cluster["identities"] if identity not in unread]
        for identity in identities:
            places.append(_place(
                origin, question, "question", identity, records.get(identity), positions,
                source=question.get("source"), before=question.get("current"),
                after=question["correction"], focus=focus, finding_id=question["id"],
                targets=len(identities),
            ))
    # Whether the game holds each correction now.
    data = Path(task["data_root"])
    held: dict[str, dict[str, dict[str, Any]]] = {}
    for filename in sorted({place["file"] for place in places}):
        path = data / filename
        held[filename] = (
            {row["identity"]: row for row in file_inventory(path, filename, focus)[1]}
            if path.is_file() else {}
        )
    for place in places:
        if place["finding_kind"] != "show-text":
            live = held[place["file"]].get(place["identity"])
            place["applied"] = _applied(live and live["live"], place["before"], place["after"])
    lines = {(record["file"], record["source"]) for record in manifest["records"]}
    return places, lines, {"read": "game now"}


class _History:
    """A game's data files as Git holds them at each commit, read without
    checking anything out."""

    def __init__(self, game: Path, staging: Path):
        self.repo = Path(self._git(game, "rev-parse", "--show-toplevel").decode().strip()).resolve()
        data, _engine = find_data_folder(game)
        if data is None:
            raise ValueError(f"no data folder in {game}")
        self.data = data.resolve().relative_to(self.repo).as_posix()
        self.staging = staging
        self._trees: dict[str, dict[str, str]] = {}
        self._records: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}

    @staticmethod
    def _git(folder: Path, *args: str) -> bytes:
        done = system.run(["git", "-C", str(folder), *args], capture_output=True)
        if done.returncode != 0:
            raise ValueError(
                f"git {args[0]} failed in {folder}: "
                + done.stderr.decode("utf-8", "replace").strip()
            )
        return done.stdout

    def git(self, *args: str) -> bytes:
        return self._git(self.repo, *args)

    def files(self, commit: str) -> dict[str, str]:
        """Each data file at *commit*, by its name in the data folder, and its blob."""
        if commit not in self._trees:
            listing = self.git("ls-tree", "-r", "-z", commit, "--", self.data + "/")
            tree = {}
            for entry in listing.split(b"\0"):
                if not entry:
                    continue
                meta, _, path = entry.partition(b"\t")
                name = path.decode("utf-8", "surrogateescape")
                if name.endswith(".json") and meta.split()[1] == b"blob":
                    tree[name[len(self.data) + 1:]] = meta.split()[2].decode()
            self._trees[commit] = tree
        return self._trees[commit]

    def _blobs(self, blobs: Iterable[str]) -> dict[str, bytes]:
        """Blobs' bytes, read through one Git process, which Windows starts
        far faster than one per file."""
        blobs = list(dict.fromkeys(blobs))
        if not blobs:
            return {}
        done = system.run(
            ["git", "-C", str(self.repo), "cat-file", "--batch"],
            input="".join(blob + "\n" for blob in blobs).encode("ascii"),
            capture_output=True,
        )
        if done.returncode != 0:
            raise ValueError("git cat-file failed: " + done.stderr.decode("utf-8", "replace").strip())
        found, at = {}, 0
        for blob in blobs:
            newline = done.stdout.index(b"\n", at)
            header = done.stdout[at:newline].split()
            if len(header) != 3 or header[1] != b"blob":
                raise ValueError(f"Git holds no file {blob}")
            size = int(header[2])
            found[blob] = done.stdout[newline + 1:newline + 1 + size]
            at = newline + 2 + size
        return found

    def read(self, commit: str, filenames: Iterable[str]) -> None:
        """Reads the inventories of data files at *commit* not read yet."""
        files = self.files(commit)
        wanted = {
            name: files[name] for name in filenames
            if name in files and (files[name], name) not in self._records
        }
        raw = self._blobs(wanted.values())
        for name, blob in wanted.items():
            path = self.staging / name
            path.parent.mkdir(parents=True, exist_ok=True)
            system.write_bytes(path, raw[blob])
            try:
                found = file_inventory(path, name, RECEIPTS_FOCUS)[1]
            finally:
                system.unlink(path, missing_ok=True)
            self._records[(blob, name)] = {record["identity"]: record for record in found}

    def records(self, commit: str, filename: str) -> dict[str, dict[str, Any]]:
        """A data file's inventory records at *commit*, by identity."""
        blob = self.files(commit).get(filename)
        if blob is None:
            return {}
        self.read(commit, [filename])
        return self._records[(blob, filename)]

    def changed(self, commit: str) -> list[str]:
        """The data files *commit* changed from its first parent."""
        listing = self.git(
            "diff-tree", "--no-commit-id", "--name-only", "-r", "-z", commit + "^", commit,
            "--", self.data + "/",
        )
        prefix = self.data + "/"
        return [
            name[len(prefix):]
            for name in listing.decode("utf-8", "surrogateescape").split("\0")
            if name.startswith(prefix) and name.endswith(".json")
        ]

    def commits(self, since: str | None) -> list[str]:
        """The first-parent commits that changed the data, oldest first, since
        *since* or all of them."""
        listing = self.git(
            "log", "--first-parent", "--reverse", "--format=%H",
            *([f"--since={since}"] if since else []), "HEAD", "--", self.data + "/",
        )
        return listing.decode().split()


def _receipt_reviews(folder: Path) -> tuple[list[tuple[str, int, dict[str, Any]]], int]:
    """A run's deep reviews that corrected a line's text, by receipt and
    position, the latest of each line's, as a later review saw everything an
    earlier one did; and how many corrections of other kinds, a header's
    speaker or a scene's lines, were left out."""
    latest: dict[str, tuple[str, int, dict[str, Any]]] = {}
    other = 0
    paths = sorted(
        (path for path in folder.glob("*.json") if path.is_file()),
        key=lambda path: (path.stat().st_mtime, path.name),
    )
    for path in paths:
        try:
            document = _read_json(path)
        except (OSError, ValueError):
            continue
        if not str(document.get("schema") or "").startswith(DEEP_RESULT):
            continue
        for index, review in enumerate(document.get("reviews") or []):
            if review.get("disposition") not in (None, "declined"):
                latest[review["id"]] = (path.name, index, review)
    corrected = []
    for name, index, review in latest.values():
        if review["disposition"] != "actionable":
            continue
        if review.get("scene_correction") or review.get("source_fix"):
            other += 1
        elif review.get("correction") is not None:
            corrected.append((name, index, review))
    return corrected, other


def _qa_commit(history: _History, targets: list[tuple[str, str, str]], created: str) -> str:
    """The commit that applied a run's corrections: the first since the run
    began that brought at least half of them into the game, else the one
    that brought the most. A checkout or clone that rewrote the receipts
    after QA leaves them newer than it, so the whole history is searched
    when nothing since brought one."""
    for since in (created, None):
        best, most = "", 0
        for commit in history.commits(since):
            try:
                changed = set(history.changed(commit))
            except ValueError:
                continue  # the repository's first commit
            touched = {filename for _identity, filename, _after in targets} & changed
            history.read(commit, touched)
            history.read(commit + "^", touched)
            brought = 0
            for identity, filename, after in targets:
                if filename not in touched:
                    continue
                now = history.records(commit, filename).get(identity)
                then = history.records(commit + "^", filename).get(identity)
                if (
                    now and _applied(now["live"], None, after)
                    and not (then and _applied(then["live"], None, after))
                ):
                    brought += 1
            if 2 * brought >= len(targets):
                return commit
            if brought > most:
                best, most = commit, brought
        if best:
            return best
    raise ValueError("no commit brings the receipts' corrections into the game")


def _read_receipts(
    origin: Origin, staging: Path
) -> tuple[list[dict[str, Any]], set[tuple[str, str]], dict[str, Any]]:
    """A receipts run's corrected places, with the text before them from the
    parent of the commit that applied them, and the lines the game held then."""
    reviews, other = _receipt_reviews(origin.path)
    if not reviews:
        return [], set(), {"read": "no corrections"}
    history = _History(origin.game, staging)
    # The lines a review names find the commit. It changed those it names,
    # else every line of its line's cluster, as findings take them.
    targets = [
        (identity, _split_identity(identity)[0], review["correction"])
        for _name, _index, review in reviews
        for identity in review.get("apply_identities") or [review["id"]]
    ]
    commit = _qa_commit(history, targets, origin.created)
    parent = commit + "^"
    history.read(parent, history.files(parent))
    history.read(commit, {filename for _identity, filename, _after in targets})
    before = {
        identity: record
        for name in sorted(history.files(parent))
        for identity, record in history.records(parent, name).items()
    }
    clusters: dict[tuple[str, str], list[str]] = defaultdict(list)
    for identity, record in sorted(before.items()):
        clusters[(record["source"], record["live"])].append(identity)
    positions = _positions(before.values())
    places = []
    for name, index, review in reviews:
        record = before.get(review["id"])
        identities = list(dict.fromkeys(review.get("apply_identities") or (
            clusters[(record["source"], record["live"])] if record else [review["id"]]
        )))
        for identity in identities:
            filename = _split_identity(identity)[0]
            place = _place(
                origin, review, "review", identity, before.get(identity),
                positions, source=None, before=None, after=review["correction"],
                focus=None, finding_id=f"{name}#{index}", targets=len(identities),
            )
            now = history.records(commit, filename).get(identity)
            place["applied"] = _applied(now and now["live"], place["before"], place["after"])
            places.append(place)
    lines = {(record["file"], record["source"]) for record in before.values()}
    how: dict[str, Any] = {"read": "git", "commit": commit}
    if other:
        how["left_out"] = f"{other} header or scene corrections"
    return places, lines, how


# Labels

_FIT = re.compile(
    r"\b(wrap|wraps|wrapped|rows?\b|fit|fits|overflow|cut off|clipp|width|line ?break|box|help window|"
    r"window|shorten|truncat|spacing|space after|title case|capitali[sz]ation of (the )?(label|header)|"
    r"ellipsis|punctuation|bullet|merged list|layout)",
    re.IGNORECASE,
)
_LEGACY = re.compile(
    r"doubled|duplicat\w* (speaker|name|label)|speaker (label|name|prefix) (twice|repeated)|"
    r"repeated (speaker|name)|name (appears|shown) twice|stray (speaker|bracket)|leftover|"
    r"__PROTECTED|residue|japanese (left|remaining)|untranslated",
    re.IGNORECASE,
)
_MEANING = re.compile(
    r"negat|flips?|invert|revers|opposite|omit|omission|drops?\b|dropped|missing|invent|adds? "
    r"(a|an|the)|misread|mistranslat|wrong (subject|object|referent|person|number|speaker)|"
    r"subject|referent|who (is|does)|quantity|number|count|condition|modality|tense",
    re.IGNORECASE,
)
_NAMES = re.compile(
    r"glossary|canonical|term\b|terminology|name\b|names\b|romani[sz]|transliterat|capitali[sz]",
    re.IGNORECASE,
)
_FIT_CATEGORIES = frozenset({"formatting", "runtime"})
_FIT_FAMILIES = ("format", "fit", "lint:", "punctuation", "layout")
_MEANING_CATEGORIES = frozenset({"meaning", "reference", "gameplay"})
_FLUENCY_CATEGORIES = frozenset({"fluency", "voice", "emotion", "humor", "wordplay", "ui"})
_STOP = frozenset(
    "a an the of to in on at for and or but is are was were be been it its this that these those "
    "he she him her his they them their you your i me my we us our not no so as by with from up out"
    .split()
)


def _letters(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def kind_of(place: dict[str, Any]) -> str:
    """A correction's one coarse kind (KINDS), by the reviewer's category and
    reason first, then by how the text changed.

    Legacy output is what older tools left in the text, such as doubled
    speaker names or Japanese never translated; fit/format changes only how
    text lays out or is punctuated; glossary/name follows a term or name,
    a glossary lint's included;
    meaning and fluency follow the reviewer's category. Lines judged for
    continuity or the listener take their category's kind, since those
    readings were too often wrong to report apart.
    """
    category = place["category"].lower()
    family = place["family_key"].lower()
    reason = " ".join(
        text for text in (place["reason"], place["evidence"], place["editorial_basis"],
                          place["editorial_note"]) if text
    )
    before, after = place["before"] or "", place["after"] or ""
    if _LEGACY.search(reason) or "__PROTECTED" in before:
        return "legacy output"
    if "lint:glossary-term" in place["lint_families"]:
        return "glossary/name"
    if _spaced(before) == _spaced(after) and category != "terminology":
        # Only spaces and line breaks moved.
        return "fit/format"
    layout_only = _letters(before) == _letters(after)
    case_only = before.lower() == after.lower() or _spaced(before).lower() == _spaced(after).lower()
    if (
        place["lint_only"] or category in _FIT_CATEGORIES or family.startswith(_FIT_FAMILIES)
        or (category == "ui" and _FIT.search(reason))
        or (layout_only and category != "terminology" and not case_only)
    ) and not (category == "terminology" and case_only):
        return "fit/format"
    if layout_only and case_only and category in {"formatting", "ui", "fluency", "other"}:
        return "fit/format"
    if category == "terminology" or (
        category == "wordplay" and family and _NAMES.search(family + " " + reason)
        and place["targets"] > 3
    ):
        return "glossary/name"
    if category == "speaker":
        return "other"
    if category in _MEANING_CATEGORIES:
        return "meaning"
    if category in _FLUENCY_CATEGORIES:
        return "fluency"
    if _MEANING.search(reason):
        return "meaning"
    return "other"


def _words(text: str | None) -> list[str]:
    return re.findall(r"[a-z][a-z'\-]*", (text or "").lower())


def _recurring(rows: list[dict[str, Any]]) -> None:
    """Marks a game's corrections that repeat one fix on RECURRING_MIN or more
    different source texts: the same finding family, or the same few words
    taken out and put in. One source text repeated across files shares one
    translation, so it is one error however many files hold it. Fit and
    format fixes repeat by nature and are left out. A correction in more
    than one group joins the largest."""

    def sources(members: Iterable[int]) -> int:
        return len({re.sub(r"\s+", "", rows[index]["source"] or "") for index in members})

    groups: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        if row["kind"] == "fit/format":
            continue
        family = row["family_key"].strip().lower()
        if family:
            groups["family:" + family].append(index)
        before, after = Counter(_words(row["before"])), Counter(_words(row["after"]))
        removed, added = sorted(before - after), sorted(after - before)
        if 0 < len(removed) + len(added) <= 6 and any(word not in _STOP for word in removed + added):
            groups["change:" + " ".join(removed) + " -> " + " ".join(added)].append(index)
    chosen: dict[int, str] = {}
    for key in sorted(groups):
        members = groups[key]
        if sources(members) < RECURRING_MIN:
            continue
        for index in members:
            if index not in chosen or len(groups[chosen[index]]) < len(members):
                chosen[index] = key
    joined: dict[str, list[int]] = defaultdict(list)
    for index, key in chosen.items():
        joined[key].append(index)
    for key, members in joined.items():
        if sources(members) >= RECURRING_MIN:
            for index in members:
                rows[index]["recurring"] = key


# Corrections


def _names(games: Iterable[Path]) -> dict[Path, str]:
    """Each game's name: its folder's, with the folder above when two share it."""
    games = list(games)
    shared = Counter(game.name for game in games)
    return {
        game: game.name if shared[game.name] == 1 else f"{game.parent.name}/{game.name}"
        for game in games
    }


def _correction_rows(game: str, places: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A game's places as corrections: a place corrected the same way again
    keeps the earliest record, and the places one finding corrected the same
    way on one line of a file are one row."""
    kept: dict[tuple[str, str], dict[str, Any]] = {}
    first_task: dict[str, str] = {}
    for place in places:
        key = (place["identity"], _spaced(place["after"]))
        if key in kept:
            continue
        earlier = first_task.setdefault(place["identity"], place["task"])
        place["requa"] = earlier != place["task"]
        kept[key] = place
    rows: dict[tuple[Any, ...], dict[str, Any]] = {}
    for place in kept.values():
        line = place["source"] if place["source"] is not None else place["identity"]
        key = (place["task"], place["finding"], place["file"], line, place["before"], place["after"])
        if key in rows:
            rows[key]["places"].append(place["identity"])
            if rows[key]["applied"] != place["applied"]:
                # Some places hold it and some not.
                rows[key]["applied"] = None
            continue
        rows[key] = {**place, "game": game, "places": [place["identity"]]}
    result = []
    for row in rows.values():
        row["kind"] = kind_of(row)
        row["recurring"] = None
        row["places"] = sorted(row["places"])
        result.append(row)
    _recurring(result)
    return result


def collect(origins: list[Origin], skipped: Iterable[str] = ()) -> Corrections:
    """The corrections *origins* hold, game by game."""
    by_game: dict[Path, list[Origin]] = defaultdict(list)
    for origin in origins:
        by_game[origin.game].append(origin)
    names = _names(by_game)
    corrections = Corrections(skipped=list(skipped))
    with system.staging_folder(tempfile.gettempdir(), "dazedtl-qa-corrections-") as staging:
        for game, game_origins in by_game.items():
            places: list[dict[str, Any]] = []
            lines: set[tuple[str, str]] = set()
            sources = []
            for origin in game_origins:
                try:
                    found, listed, how = (
                        _read_task(origin) if origin.kind == "task"
                        else _read_receipts(origin, staging)
                    )
                except (OSError, ValueError, KeyError) as exc:
                    corrections.skipped.append(f"{origin.path}: {exc}")
                    continue
                places += found
                lines |= listed
                sources.append({
                    "origin": origin.kind, "task": origin.task, "path": str(origin.path),
                    "created": origin.created, **how,
                })
            if not sources:
                continue
            corrections.rows += _correction_rows(names[game], places)
            corrections.games.append({
                "game": names[game], "game_root": str(game),
                "translated_lines": len(lines), "sources": sources,
            })
    return corrections


# Reports and exports


def _line(row: dict[str, Any]) -> tuple[str, str, str]:
    return row["game"], row["file"], row["source"] if row["source"] is not None else row["identity"]


def _per_1000(count: int, lines: int) -> float:
    return round(1000 * count / lines, 2) if lines else 0.0


def _tally(rows: list[dict[str, Any]], lines: int, top: int) -> dict[str, Any]:
    """Counts of corrected lines by kind, a line counting under the kind of
    its earliest correction."""
    first: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in sorted(rows, key=lambda row: (row["created"], row["finding"])):
        first.setdefault(_line(row), row)
    kinds = Counter(row["kind"] for row in first.values())
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["recurring"]:
            groups[(row["game"], row["recurring"])].append(row)
    ranked = sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
    return {
        "translated_lines": lines,
        "corrected_lines": len(first),
        "places": sum(len(row["places"]) for row in rows),
        "per_1000": _per_1000(len(first), lines),
        "kinds": {
            kind: {"lines": kinds[kind], "per_1000": _per_1000(kinds[kind], lines)} for kind in KINDS
        },
        "applied": dict(Counter(
            {True: "yes", False: "no", None: "unknown"}[row["applied"]] for row in rows
        )),
        "requa": sum(1 for row in rows if row["requa"]),
        "recurring": {
            "groups": len(groups),
            "lines": len({_line(row) for members in groups.values() for row in members}),
            "top": [
                {
                    "game": game, "key": key, "lines": len(members),
                    "kind": Counter(row["kind"] for row in members).most_common(1)[0][0],
                    "before": members[0]["before"], "after": members[0]["after"],
                }
                for (game, key), members in ranked[:top]
            ],
        },
    }


def summary(corrections: Corrections, top: int = 5) -> dict[str, Any]:
    """Each game's tally and the pooled one."""
    games = []
    for game in corrections.games:
        rows = [row for row in corrections.rows if row["game"] == game["game"]]
        games.append({"game": game["game"], **_tally(rows, game["translated_lines"], top)})
    pooled = _tally(
        corrections.rows, sum(game["translated_lines"] for game in corrections.games), top
    )
    return {"games": games, "pooled": pooled, "skipped": corrections.skipped}


def render(report: dict[str, Any]) -> str:
    """The report as text, a game's name padded by the cells it takes."""

    def padded(name: str) -> str:
        return name + " " * (width - sum(cells(character) for character in name))

    width = max([sum(map(cells, game["game"])) for game in report["games"]] + [6])
    header = (
        padded("game") + "  lines  fixed  /1000  "
        + "  ".join(kind.rjust(max(len(kind), 11)) for kind in KINDS)
    )
    out = [header, "-" * len(header)]

    def row(name: str, tally: dict[str, Any]) -> str:
        counts = [
            f"{tally['kinds'][kind]['lines']} ({tally['kinds'][kind]['per_1000']:.2f})"
            .rjust(max(len(kind), 11))
            for kind in KINDS
        ]
        return (
            f"{padded(name)}  {tally['translated_lines']:>5}  {tally['corrected_lines']:>5}  "
            f"{tally['per_1000']:>5.1f}  " + "  ".join(counts)
        )

    for game in report["games"]:
        out.append(row(game["game"], game))
    pooled = report["pooled"]
    out.append(row("POOLED", pooled))
    out.append("")
    out.append(
        f"Each kind: corrected lines (per 1,000 translated lines). {pooled['places']} places "
        f"changed; applied {pooled['applied']}; {pooled['requa']} re-correct an earlier QA."
    )
    recurring = pooled["recurring"]
    out.append(
        f"Recurring groups: {recurring['groups']}, holding {recurring['lines']} corrected lines."
    )
    for group in recurring["top"]:
        before = _spaced(group["before"])[:50]
        after = _spaced(group["after"])[:50]
        out.append(
            f"  {group['lines']:>4}  {group['game']}  {group['kind']}  {group['key'][:60]}"
            f"  | {before} -> {after}"
        )
    for reason in report["skipped"]:
        out.append(f"Skipped {reason}")
    return "\n".join(out) + "\n"


def export_lines(corrections: Corrections) -> Iterator[str]:
    """The export's JSON lines: a header with the schema, VERSION, kinds and
    each game's inputs and translated lines, then one row per correction."""
    yield json.dumps({
        "schema": EXPORT_SCHEMA,
        "version": VERSION,
        "kinds": list(KINDS),
        "fields": list(EXPORT_FIELDS),
        "games": corrections.games,
        "skipped": corrections.skipped,
    }, ensure_ascii=False)
    ordered = sorted(
        corrections.rows,
        key=lambda row: (row["game"], row["created"], row["task"], row["finding"], row["identity"]),
    )
    for row in ordered:
        yield json.dumps(
            {"version": VERSION, **{key: row[key] for key in EXPORT_FIELDS if key != "version"}},
            ensure_ascii=False,
        )


def check_destination(path: Path, origins: Iterable[Origin], workspace: Path | None = None) -> Path:
    """*path* resolved, refusing one inside the source tree, a game, a task
    or the workspace holding one, which the export never writes into."""
    target = Path(path).expanduser().resolve()
    guarded = [SOURCE_TREE]
    if workspace is not None:
        guarded.append(Path(workspace).expanduser().resolve())
    for origin in origins:
        guarded += [origin.game, origin.path]
        # A task sits in <workspace>/engine/workflows/<project>/text-qa/...
        guarded += [
            folder.parent.parent for folder in origin.path.parents
            if folder.name == "workflows" and folder.parent.name == "engine"
        ]
    for folder in guarded:
        if target == folder or folder in target.parents:
            raise ValueError(f"The export goes outside {folder}")
    return target


def export(corrections: Corrections, path: Path) -> int:
    """Writes the export to *path*, checked by check_destination; returns its rows."""
    lines = list(export_lines(corrections))
    system.write_text(path, "\n".join(lines) + "\n")
    return len(lines) - 1
