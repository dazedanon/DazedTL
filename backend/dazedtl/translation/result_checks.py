"""Text QA's text-only rules over an Assistant-led game's translations, for
the engines Text QA can't read (qa --check).

Text QA reads RPG Maker MV/MZ and VX Ace data. Its mechanical flags
(util/qa/mechanical `evidence`), its glossary hint, its pronoun check
(util/qa/pronouns) and its reviewed lint families (util/rpgmaker_qa_lint)
need only a line's source, its translation and the game's glossary, so they
check a WOLF, Unity, TyranoScript or other game's text export too. Each hit is a line for the assistant to correct, or
to answer with why it is right, as Text QA's reviewers decline a reviewed
family's proposal; an answer stays while the line and what the rule found
in it stay the same.
"""

from collections import defaultdict

from dazedtl.freshness import Basis, compare
from dazedtl.storage import write_json

from .files import digest, project_path, read_json
from .project import WORK
from .results import exported_translations

CHECK_FILE = WORK + "/work/qa-check.json"
# The rules a report's hits are found by: 1, Text QA's mechanical flags, its
# glossary hint and its reviewed lint families; 2, with its censor-mask flag
# and pronoun check. Raise it when the same text would give other hits;
# answers carry over to hits that stay the same.
CHECK_VERSION = 2
# An answer is one line, as a declined line's reason is.
ANSWER_LIMIT = 300
# Text QA's hint for a line whose translation lacks a glossary term the
# family finds no rendering of to fix.
GLOSSARY_HINT = "glossary"
# What the assistant does about the hits, which the starting prompt's QA
# step also says.
CHECK_STEP = (
    "Run qa --check, which checks your exported translations with Text QA's "
    "text-only rules, such as glossary terms, numbers and codes kept, text "
    "left untranslated, censor masks, pronouns against the glossary's genders "
    f"and suspicious length, and lists each hit in {CHECK_FILE} "
    "with its units. Correct a wrong line with a correction receipt that "
    "carries its request's current result_sha256 as replaces_sha256, accept "
    "it and inject it again; answer a line that is right with qa --check "
    "--answers FILE, a JSON object of hit ID to a one-line reason. Run it "
    "again until no hit is open."
)


def hits(rows, glossary_text, target):
    """The hits of export *rows* (results `exported_translations`): one per
    rule and distinct line, with the units that hold it, in the export's
    order. Run within the game's `reading` of its language pair."""
    from util import rpgmaker_qa_glossary as glossary_rules
    from util import rpgmaker_qa_lint as lint
    from util.qa import mechanical, pronouns

    # What the families read from the whole game, as Text QA reads it from
    # an inventory: its distinct lines and every unit's.
    lines = list(dict.fromkeys((row["source"], row["translation"]) for row in rows))
    game = lint.game(
        {
            "clusters": [{"source": source, "live": live} for source, live in lines],
            "records": [
                {
                    "file": row["batch"],
                    "source": row["source"],
                    "live": row["translation"],
                }
                for row in rows
            ],
        },
        glossary_text,
        target,
    )
    units = defaultdict(list)
    for row in rows:
        units[(row["source"], row["translation"])].append(
            {
                "unit": row["source_id"],
                "batch": row["batch"],
                "request_sha256": row["request_sha256"],
            }
        )
    # A pronoun against a character's glossary gender, read as Text QA reads
    # a scene: each export batch is one document.
    characters = pronouns.cast(glossary_text, target)
    batches = defaultdict(list)
    for row in rows:
        batches[row["batch"]].append(row)
    slipped = defaultdict(list)
    for batch in batches.values():
        for slip in pronouns.slips((row["translation"] for row in batch), characters):
            row = batch[slip.index]
            named = slipped[(row["source"], row["translation"])]
            if [slip.name, slip.gender, slip.pronoun] not in named:
                named.append([slip.name, slip.gender, slip.pronoun])
    found = []
    for source, live in lines:
        # Each rule that finds something in the line, with what it found.
        line_hits = [
            (flag, {}) for flag in mechanical.evidence(source, live, None)["flags"]
        ]
        proposals = {
            family: proposed
            for family, proposed in lint.proposals(source, live, game).items()
            if family not in lint.AUTOMATIC
        }
        for family, proposed in proposals.items():
            note = lint.note(family, source, live, game)
            line_hits.append(
                (family, {"proposed": proposed, **({"note": note} if note else {})})
            )
        if "lint:glossary-term" not in proposals:
            missing = glossary_rules.missing(source, live, game.glossary)
            if missing:
                terms = [[term.source, term.english] for term, _s, _e in missing]
                line_hits.append((GLOSSARY_HINT, {"terms": terms}))
        if slipped[(source, live)]:
            line_hits.append((pronouns.CHECK, {"pronouns": slipped[(source, live)]}))
        found += [
            {
                # What the rule found is part of the hit, so an answer
                # never covers a fix, a term or a pronoun it was not given for.
                "id": digest(
                    [
                        rule,
                        source,
                        live,
                        details.get("proposed"),
                        details.get("terms") or details.get("pronouns"),
                    ]
                )[:16],
                "rule": rule,
                "source": source,
                "translation": live,
                **details,
                "units": units[(source, live)],
            }
            for rule, details in line_hits
        ]
    return found


def _answers(given, current):
    """The assistant's answers by hit ID, refusing any that names no current
    hit or gives no one-line reason."""
    if not isinstance(given, dict):
        raise ValueError("Give answers as a JSON object of hit ID to reason.")
    for identity, reason in given.items():
        if identity not in current:
            raise ValueError(f"No current hit is {identity}; run qa --check again.")
        if (
            not isinstance(reason, str)
            or len(reason.strip().splitlines()) != 1
            or len(reason.strip()) > ANSWER_LIMIT
        ):
            raise ValueError(
                f"Answer {identity} with one line of at most {ANSWER_LIMIT} characters."
            )
    return {identity: reason.strip() for identity, reason in given.items()}


def check(root, source_language, target, answers=None):
    """Checks the game at *root*'s exported translations, saving the hits
    with the answers given now and before at CHECK_FILE, and gives the
    counts and the next step."""
    from util.paths import GAME_GLOSSARY_RELATIVE

    from dazedtl.languages import reading

    rows = exported_translations(root)
    glossary = project_path(root, GAME_GLOSSARY_RELATIVE.as_posix(), exists=False)
    glossary_text = (
        glossary.read_text(encoding="utf-8-sig") if glossary.is_file() else ""
    )
    basis = Basis(
        CHECK_VERSION,
        {
            "translations": digest(
                [
                    [row[key] for key in ("source_id", "batch", "request_sha256")]
                    + [row["source"], row["translation"]]
                    for row in rows
                ]
            ),
            "glossary": digest(glossary_text.encode("utf-8")),
            "languages": [source_language, target],
        },
    )
    path = project_path(root, CHECK_FILE, exists=False)
    saved = read_json(path) if path.is_file() else {}
    earlier = {
        row["id"]: row["answer"] for row in saved.get("hits", []) if "answer" in row
    }
    if compare(Basis.read(saved.get("basis")), basis) is None:
        found = [
            {key: value for key, value in row.items() if key != "answer"}
            for row in saved["hits"]
        ]
    else:
        with reading(source_language, target):
            found = hits(rows, glossary_text, target)
    given = _answers(answers or {}, {row["id"] for row in found})
    for row in found:
        answer = given.get(row["id"]) or earlier.get(row["id"])
        if answer:
            row["answer"] = answer
    report = {"basis": basis.record(), "lines": len(rows), "hits": found}
    if report != saved:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, report)
    rules = defaultdict(int)
    for row in found:
        if "answer" not in row:
            rules[row["rule"]] += 1
    waiting = sum(rules.values())
    if not rows:
        following = (
            "No translation is exported yet; accept translations, then run qa --check."
        )
    elif waiting:
        following = CHECK_STEP
    else:
        following = "No hit is open; go on with the qa step."
    return {
        "report": CHECK_FILE,
        "lines": len(rows),
        "hits": len(found),
        "open": waiting,
        "answered": len(found) - waiting,
        "rules": dict(sorted(rules.items())),
        "next": following,
    }
