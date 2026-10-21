"""The review ledger: what a task's reviews judged, kept for later tasks of
the same game, and the baselines earlier releases leave."""

from __future__ import annotations

import re
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from util import rpgmaker_qa_glossary as glossary_rules
from util import system
from util.paths import GAME_GLOSSARY_RELATIVE, GAME_QUIRKS_RELATIVE
from util.qa.fitting import _written
from util.qa.records import _changes, _record_maps, _result_declines
from util.qa.schema import (
    _JAPANESE_ANCHOR_RE,
    FINDINGS_SCHEMA,
    _canonical_bytes,
    _sha256,
)
from util.qa.selection import _glossary_entries, _scene_groups
from util.qa.storage import (
    _atomic_write_json,
    _read_json,
    _read_task,
    _task_lock,
    answers,
)
from util.rpgmaker_qa_manifest import build_manifest

# Earlier reviews. A finished task's reviews still stand for text that has not
# changed since, and a version the user says was checked before DazedTL counts
# as reviewed as it was then; a new task reads such lines only as context.
REVIEWED_SCHEMA = "rpgmaker-qa-reviewed-v1"
REVIEWED_FILE = "reviewed.json"
BASELINE_FOLDER = "baselines"
# A task's ledger is saved in its folder once derived; one an earlier version
# derived, which may keep lines this one leaves out or lack lines it keeps, is
# derived again. A baseline holds the game's text as Git had it, which no
# version reads differently.
TASK_LEDGER_VERSION = 3
# Deep reviews that judge a line's observation for good: the line is right, or
# no correction can fix it.
JUDGED_DISPOSITIONS = frozenset({"clean", "not-corrected"})


def _pair_key(source: Any, translation: Any) -> str:
    return _sha256(f"{source}\0{translation}")[:32]


def _guidance_lines(context: dict[str, Any]) -> dict[str, list[str]]:
    """Each glossary entry and translation quirk, with the Japanese terms it
    governs; a quirk without Japanese governs no line in particular."""
    lines = {
        line: terms
        for terms, _english, line in _glossary_entries(
            (context.get("glossary") or {}).get("text")
        )
    }
    for raw in str((context.get("quirks") or {}).get("text") or "").splitlines():
        line = raw.strip()
        if terms := _quirk_terms(line):
            lines[line] = terms
    return lines


_QUOTED_RE = re.compile(r"`([^`\n]+)`")
_NAMED_JAPANESE_RE = re.compile(r"[一-龠々〆〤ぁ-ゔァ-ヴー]*[一-龠々ァ-ヴ][一-龠々〆〤ぁ-ゔァ-ヴー]*")


def _quirk_terms(line: str) -> list[str]:
    """The Japanese a quirk governs: its quoted Japanese, each alternative
    apart, or else its words with kanji or katakana, never bare kana that
    common words share."""
    quoted = [
        part.strip()
        for span in _QUOTED_RE.findall(line)
        for part in span.split(" / ")
        if _JAPANESE_ANCHOR_RE.search(part)
    ]
    if quoted:
        return sorted(set(quoted))
    return sorted({
        word for word in _NAMED_JAPANESE_RE.findall(line) if len(word) >= 2
    })


def _task_ledger(root: Path) -> dict[str, Any] | None:
    """What a complete task reviewed and left standing, kept in its folder:
    lines screened or deep-reviewed, minus any whose finding still waits to be
    applied or whose review was declined, plus the corrections editorial
    confirmed and the lines the user kept when asked."""
    cached = root / REVIEWED_FILE
    try:
        ledger = _read_json(cached)
        if (
            ledger.get("schema") == REVIEWED_SCHEMA
            and ledger.get("version") == TASK_LEDGER_VERSION
        ):
            return ledger
    except (OSError, ValueError):
        pass
    try:
        # A follow-up round reopens the task and removes its ledger under the
        # task's lock, so the ledger is made and saved under it too.
        with _task_lock(root):
            _root, task, checkpoint = _read_task(root)
            if checkpoint["stage"] != "complete":
                return None
            ledger = _derive_ledger(root, task, checkpoint)
            try:
                _atomic_write_json(cached, ledger)
            except OSError:
                pass
    except (OSError, ValueError, KeyError, TypeError):
        # A task whose files moved or broke is no review to build on.
        return None
    return ledger


def _layout_key(layout: Any) -> str:
    return _sha256(_canonical_bytes(layout))[:32]


def _derive_ledger(
    root: Path, task: dict[str, Any], checkpoint: dict[str, Any]
) -> dict[str, Any]:
    report = _read_json(root / "findings.json")
    if (
        report.get("schema") != FINDINGS_SCHEMA
        or report.get("task_sha256") != checkpoint["task_sha256"]
        or checkpoint["task_sha256"] != _sha256(_canonical_bytes(task))
    ):
        raise ValueError(f"QA findings belong to another task: {root}")
    context = _read_json(root / "context.json")
    records, _clusters = _record_maps(_read_json(root / "inventory.json"))
    # Questions the user answered by keeping the line: it reads right as it is.
    answered = answers(root)
    kept = {
        row["id"] for row in report.get("uncertain_playtests") or []
        if answered.get(row["id"]) == "keep"
    }
    reviewed: set[str] = set()
    scenes: set[str] = set()
    variants: set[str] = set()
    rejected: set[str] = set()
    cleared: dict[str, set[str]] = defaultdict(set)
    # Each observation's verdict: the latest deep review of its line.
    verdicts: dict[str, str] = {}
    unsettled: set[str] = set()
    for row in checkpoint["screen"]["bundles"]:
        if row["status"] != "accepted" or row.get("check_of"):
            continue
        bundle = _read_json(Path(row["path"]))
        result = _read_json(Path(row["result_path"]))
        declined = _result_declines(result)
        motifs = {review["id"]: review for review in result.get("motif_reviews") or []}
        lints = {review["id"]: review for review in result.get("lint_reviews") or []}
        for item in bundle["items"]:
            if item["id"] in declined:
                continue
            kind = item.get("kind")
            if kind == "scene":
                scenes.add(item["id"])
                reviewed.update(
                    _pair_key(line["source"], line["translation"])
                    for line in item["lines"] if "id" in line
                )
            elif kind == "cluster":
                reviewed.add(_pair_key(item["source"], item["translation"]))
            elif kind == "motif-family" and (
                motifs.get(item["id"]) or {}
            ).get("disposition") == "preserved":
                variants.update(
                    _pair_key(item["id"], _pair_key(variant["source"], variant["translation"]))
                    for variant in item["variants"] if variant["id"] not in declined
                )
            elif kind == "lint-family" and item["id"] in lints:
                rejected.update(
                    _sha256(
                        f"{proposal['source']}\0{proposal['current']}\0{proposal['proposed']}"
                    )[:32]
                    for proposal in item["proposals"]
                    if proposal["id"] in set(lints[item["id"]]["rejected"]) - declined
                )
    for row in checkpoint["deep"]["bundles"]:
        if row["status"] != "accepted":
            continue
        items = {item["id"]: item for item in _read_json(Path(row["path"]))["items"]}
        for review in _read_json(Path(row["result_path"]))["reviews"]:
            item = items[review["id"]]
            pair = _pair_key(item["source"], item["translation"])
            disposition = (
                "clean"
                if review["disposition"] == "uncertain-playtest" and review["id"] in kept
                else review["disposition"]
            )
            if disposition == "declined":
                unsettled.add(pair)
                continue
            if disposition == "clean":
                reviewed.add(pair)
                cleared[pair].update(item.get("deep_reasons") or [])
            for evidence in item.get("screen_evidence") or []:
                if evidence.get("verdict") == "observation":
                    key = _sha256(f"{pair}\0{evidence['note']}")[:32]
                    verdicts[key] = disposition
    for finding in report.get("findings") or []:
        for change in _changes(finding):
            unsettled.add(_pair_key(change["source"], change["current"]))
            # Editorial confirmed the correction, which passed every check,
            # as the game holds it once applied.
            for written in {
                _written(records[identity], change["correction"], task.get("layout"))
                for identity in change["identities"]
            }:
                corrected = _pair_key(change["source"], written)
                reviewed.add(corrected)
                cleared[corrected].add("*")
    for row in [
        *(
            row for row in report.get("uncertain_playtests") or []
            if row["id"] not in kept
        ),
        *(report.get("not_corrected") or []),
        *(report.get("not_reviewed") or []),
    ]:
        unsettled.add(_pair_key(row.get("source"), row.get("current")))
    return {
        "schema": REVIEWED_SCHEMA,
        "version": TASK_LEDGER_VERSION,
        "origin": f"task {root.name}",
        "pairs": sorted(reviewed - unsettled),
        "scenes": sorted(scenes),
        "variants": sorted(variants),
        "lint_rejected": sorted(rejected),
        "cleared": {
            pair: sorted(reasons) for pair, reasons in sorted(cleared.items())
            if pair not in unsettled
        },
        # An observation is judged where the reviewer left the line as it is
        # on purpose; one they corrected is a problem still while the line
        # keeps that text, as when editorial left the correction unverified,
        # so the next playtest's report brings it back.
        "observed": sorted(
            key for key, verdict in verdicts.items() if verdict in JUDGED_DISPOSITIONS
        ),
        "corrected": sorted(
            key for key, verdict in verdicts.items() if verdict not in JUDGED_DISPOSITIONS
        ),
        "guidance": _guidance_lines(context),
        # Text fits its window only under the Line widths it was reviewed with.
        "layout": _layout_key(task.get("layout")),
    }


def _baseline_commit(game: Path, since: str) -> tuple[Path, str, str]:
    """The repository and commit whose translation a since-scope treats as
    reviewed: before the update that brought version *since*, or *since* as
    a Git revision; and how to name it."""
    from util.version_update.git_workflow import (
        _VERSION_LINE,
        GitWorkflowError,
        _run_git,
    )

    try:
        repo = Path(
            _run_git(game, "rev-parse", "--show-toplevel").stdout.strip()
        ).resolve()
        log = _run_git(
            repo, "log", "--first-parent", "--format=%H%x00%B%x1e", "HEAD"
        ).stdout
    except GitWorkflowError as exc:
        raise ValueError(
            "QA can take earlier text as checked only in a game saved in Git: "
            f"{exc}"
        ) from exc
    for entry in log.split("\x1e"):
        commit, _, message = entry.strip("\n").partition("\x00")
        version = _VERSION_LINE.search(message)
        if (
            message.strip().startswith("patch:")
            and version and version.group(1).strip() == since.strip()
        ):
            parent = _run_git(repo, "rev-parse", f"{commit}^").stdout.strip()
            return repo, parent, f"before the {since.strip()} update"
    resolved = _run_git(
        repo, "rev-parse", "--verify", "--quiet", f"{since}^{{commit}}", check=False
    )
    if resolved.returncode != 0 or not resolved.stdout.strip():
        raise ValueError(
            f"{since} is neither a version this game was updated to nor a Git revision"
        )
    commit = resolved.stdout.strip()
    return repo, commit, f"as of {commit[:12]}"


def _baseline_ledger(
    storage: Path, game: Path, data: Path, focus: str, since: str
) -> dict[str, Any]:
    """Every line of the game as it was translated at the baseline, which the
    user says was reviewed before, as a ledger kept with the game's tasks."""
    import io
    import tarfile

    from util.version_update.git_workflow import _run_git

    repo, commit, label = _baseline_commit(game, since)
    path = storage / BASELINE_FOLDER / f"{commit}.json"
    try:
        ledger = _read_json(path)
        if ledger.get("schema") == REVIEWED_SCHEMA:
            return ledger
    except (OSError, ValueError):
        pass
    relative = data.relative_to(repo).as_posix()
    archive = system.run(
        ["git", "-C", str(repo), "archive", "--format=tar", commit, "--", relative],
        capture_output=True, check=False,
    )
    if archive.returncode != 0:
        raise ValueError(
            f"Git could not read the game's data at {commit[:12]}: "
            + archive.stderr.decode("utf-8", "replace").strip()
        )
    with system.staging_folder(tempfile.gettempdir(), "dazedtl-qa-baseline-") as temporary:
        with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
            tar.extractall(temporary, filter="data")
        manifest = build_manifest(Path(temporary) / relative, focus)
    guidance = {}
    for name, relative_path in (
        ("glossary", GAME_GLOSSARY_RELATIVE), ("quirks", GAME_QUIRKS_RELATIVE),
    ):
        pointer = (game / relative_path).relative_to(repo).as_posix()
        shown = _run_git(repo, "show", f"{commit}:{pointer}", check=False)
        guidance[name] = {"text": shown.stdout if shown.returncode == 0 else ""}
    groups, _cluster_ids = _scene_groups(manifest)
    ledger = {
        "schema": REVIEWED_SCHEMA,
        "origin": f"since {since.strip()}",
        "commit": commit,
        "label": label,
        "everything": True,
        "pairs": sorted({
            _pair_key(cluster["source"], cluster["live"])
            for cluster in manifest["clusters"]
        }),
        "scenes": sorted("scene-" + group["signature"][:20] for group in groups),
        "guidance": _guidance_lines(guidance),
    }
    _atomic_write_json(path, ledger)
    return ledger


_KANA_RE = re.compile(r"[ぁ-ゔァ-ヴー]+")
_HIRAGANA_RE = re.compile(r"[ぁ-ゔー]+")
_LINE_PUNCTUATION_RE = re.compile(r"[\s。、！？!?…‥―〜~・「」『』【】]+")


class _Terms:
    """Changed guidance terms found in a line's Japanese. A hiragana word of
    two kana or fewer, such as a pun on なる, governs only a line that is
    that word, and a katakana one, such as the name ミナ, only where it is a
    word of its own, or each would reopen every line sharing common kana."""

    def __init__(self, terms: set[str]):
        short = {
            term: bare for term in terms
            if _KANA_RE.fullmatch(bare := _LINE_PUNCTUATION_RE.sub("", term))
            and len(bare) <= 2
        }
        self.whole = {bare for bare in short.values() if _HIRAGANA_RE.fullmatch(bare)}
        self.words = sorted(set(short.values()) - self.whole)
        inside = sorted(set(terms) - set(short), key=lambda term: (-len(term), term))
        self.inside = re.compile("|".join(map(re.escape, inside))) if inside else None

    def search(self, source: str) -> bool:
        return (
            bool(self.inside and self.inside.search(source))
            or any(glossary_rules.mentions(source, word) for word in self.words)
            or _LINE_PUNCTUATION_RE.sub("", source) in self.whole
        )


def _terms_pattern(terms: set[str]) -> _Terms | None:
    return _Terms(terms) if terms else None


class _Reviewed:
    """What earlier tasks and baselines reviewed that still stands for this
    task's guidance: a ledger's line no longer counts once a glossary entry
    or quirk whose Japanese it holds changed since that review."""

    def __init__(
        self,
        ledgers: list[dict[str, Any]],
        context: dict[str, Any],
        layout: dict[str, Any],
    ):
        guidance = _guidance_lines(context)
        self.layout = _layout_key(layout)
        self.ledgers = []
        for ledger in ledgers:
            before = ledger.get("guidance") or {}
            changed = {
                term for line in before.keys() ^ guidance.keys()
                for term in before.get(line) or guidance.get(line) or []
            }
            self.ledgers.append((
                ledger,
                {key: set(ledger.get(key) or []) for key in (
                    "pairs", "scenes", "variants", "lint_rejected", "observed",
                )},
                _terms_pattern(changed),
            ))
        self.origins = [ledger["origin"] for ledger in ledgers]

    def __bool__(self) -> bool:
        return bool(self.ledgers)

    def _standing(self, source: str) -> list[tuple[dict, dict[str, set[str]]]]:
        return [
            (ledger, sets) for ledger, sets, changed in self.ledgers
            if changed is None or not changed.search(source)
        ]

    def line(self, source: Any, translation: Any) -> bool:
        key = _pair_key(source, translation)
        return any(key in sets["pairs"] for _ledger, sets in self._standing(str(source)))

    def scene(self, scene_id: str, lines: Iterable[tuple[Any, Any]]) -> bool:
        """Whether a scene with this text was screened, or holds only text
        reviewed before, such as corrections editorial confirmed; changed
        guidance reopens the lines it governs, not the scene's other lines."""
        if any(scene_id in sets["scenes"] for _ledger, sets, _changed in self.ledgers):
            return True
        return all(
            any(_pair_key(source, translation) in sets["pairs"] for _l, sets, _c in self.ledgers)
            for source, translation in lines
        )

    def cleared(self, source: Any, translation: Any, reasons: Iterable[str]) -> bool:
        """Whether deep review already settled every one of these reasons for
        the line, so they send it to deep review no more. Squeezed text is
        always looked at again, since a capture can change what fits, and
        text too long for its window under other Line widths than it was
        reviewed with."""
        reasons = set(reasons)
        if not reasons or "interface-fit" in reasons:
            return False
        key = _pair_key(source, translation)
        settled: set[str] = set()
        for ledger, sets in self._standing(str(source)):
            found = set((ledger.get("cleared") or {}).get(key) or [])
            if "*" in found or ledger.get("everything") and key in sets["pairs"]:
                found = set(reasons)
            if ledger.get("layout") != self.layout:
                found.discard("text-fit")
            settled |= found
        return reasons <= settled

    def variant(self, family: str, source: Any, translation: Any) -> bool:
        pair = _pair_key(source, translation)
        key = _pair_key(family, pair)
        return any(
            key in sets["variants"] or ledger.get("everything") and pair in sets["pairs"]
            for ledger, sets in self._standing(str(source))
        )

    def lint_rejected(self, source: Any, current: Any, proposed: Any) -> bool:
        pair = _pair_key(source, current)
        key = _sha256(f"{source}\0{current}\0{proposed}")[:32]
        return any(
            key in sets["lint_rejected"]
            or ledger.get("everything") and pair in sets["pairs"]
            for ledger, sets in self._standing(str(source))
        )

    def observed(self, source: Any, translation: Any, note: str) -> bool:
        key = _sha256(f"{_pair_key(source, translation)}\0{note}")[:32]
        return any(key in sets["observed"] for _ledger, sets in self._standing(str(source)))

    def decisions(self) -> list[dict[str, Any]]:
        """The decisions earlier tasks recorded that still stand, the latest
        one per key: one no longer counts once a glossary entry or quirk for
        Japanese it names changed since, as its reviews would not."""
        latest: dict[str, dict[str, Any]] = {}
        for ledger, _sets, changed in self.ledgers:
            for entry in ledger.get("decisions") or []:
                named = f"{entry.get('source') or ''}\n{entry['choice']}"
                if changed is not None and changed.search(named):
                    continue
                if str(entry["at"]) >= str((latest.get(entry["key"]) or {}).get("at") or ""):
                    latest[entry["key"]] = {
                        **entry, "from": entry.get("from") or ledger["origin"],
                    }
        return sorted(latest.values(), key=lambda entry: entry["key"])
