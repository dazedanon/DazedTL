"""Retained investigation around the preserved event-text phases.

Saved findings apply their recommendations as the project's source choices.
"""

import json
import re
import uuid
from pathlib import Path
from typing import Any

from dazedtl.storage import write_json

from .files import digest, project_path, read_json
from .helper_command import git_note

CODES = (
    "CODE122",
    "CODE357",
    "CODE355655",
    "CODE356",
    "CODE657",
    "CODE320",
    "CODE324",
    "CODE325",
    "CODE108",
)
SELECTORS = {"CODE357": "ENABLED_PLUGINS_357", "CODE355655": "ENABLED_PATTERNS_355655"}
# Plugins split these codes' commands on spaces. Their findings say how each
# built-in handler joins a translation's words and which exact commands stay
# untranslated, kept in these options.
WORDED = {
    "CODE356": ("SPACES_356", "NBSP_356", "KEEP_356"),
    "CODE108": ("SPACES_108", "NBSP_108", "KEEP_108"),
}
SPACING = {"space", "nbsp", "underscore"}
FIELDS = (
    *CODES,
    "CODE122_VAR_RANGES",
    *SELECTORS.values(),
    *(key for keys in WORDED.values() for key in keys),
)
FINDING = {
    "decision",
    "confidence",
    "coverage",
    "reason",
    "targets",
    "observations",
    "exclusions",
    "evidence",
}
REPORT = ".dazedtl/guided/event-text-findings.json"
# The ways JSON without \u escapes can write a command code of 357, 355 or
# 655: that number, or any number with a fraction or exponent.
SELECTED_CODES = re.compile(rb'"code"\s*:\s*(?:(?:35[57]|655)(?![0-9])|-?[0-9]+[.eE])')
# The project record key naming the report whose recommendations were applied.
RECEIPT = "guided_event_text"
VIEWS = {"audit", "sources", "advanced-run", "variables"}


def commands(value):
    """Every event command in parsed RPG Maker JSON."""
    if isinstance(value, list):
        for item in value:
            yield from commands(item)
    elif isinstance(value, dict):
        if "code" in value and isinstance(value.get("parameters"), list):
            yield value
        for key, item in value.items():
            if key != "_original":
                yield from commands(item)


class EventText:
    @staticmethod
    def unset():
        """Every event-text option with nothing chosen."""
        return {
            key: False if key in CODES else "" if key == "CODE122_VAR_RANGES" else []
            for key in FIELDS
        }

    def __init__(self, guided):
        self.guided = guided
        self.originals = {}
        self.hits = {}

    def catalog(self):
        return self.guided.backend.guided_event_text_catalog()

    def options(self, native):
        values = {
            key: native["engine_options"].get(key, value)
            for key, value in self.unset().items()
        }
        return self.guided.backend.guided_event_text_options(values)

    def context(self, project_id, native, catalog):
        inputs = self.guided.inputs(native)
        names = sorted(self.guided.supported_files(native))
        sources = inputs.sources(
            names, inputs.record()["inputs"], self.guided.observed_digest
        )
        dependencies, originals, event_inputs, runtime_dependencies = {}, {}, {}, {}
        selected = self.guided.runs.files(native, "advanced")
        root = Path(native["source"])
        for name, source in sources.items():
            identity, relative = source["identity"], source["relative"]
            path = self.guided.observed_path(root, relative)
            if "original" in identity:
                originals[relative] = identity["original"]
                dependencies[relative] = None
            else:
                dependencies[relative] = self.guided.observed_digest(path)
            if name in selected:
                event_inputs[relative] = (identity, path)
        extra = [
            path
            for directory, pattern in (
                (root / "js/plugins", "*.js"),
                (root / "Scripts", "*.rb"),
            )
            if directory.is_dir()
            for path in directory.rglob(pattern)
        ]
        if (root / "js/plugins.js").is_file():
            extra.append(root / "js/plugins.js")
        paths = sorted({path.relative_to(root).as_posix() for path in extra})
        bindings = (
            self.guided.translation.engine.source_bindings(root, paths) if paths else {}
        )
        for relative in paths:
            path = self.guided.observed_path(root, relative)
            runtime_dependencies[relative] = self.guided.observed_digest(path)
            if relative in bindings:
                originals[relative] = bindings[relative]
                dependencies[relative] = None
            else:
                dependencies[relative] = self.guided.observed_digest(path)
        # Git reads each original blob once for the life of the app, all
        # through one process; the selected event files' built-in matches
        # come from the same bytes.
        unread = dict.fromkeys(
            blob for blob in originals.values() if blob not in self.originals
        )
        unmatched = {
            identity["original"]
            for identity, _path in event_inputs.values()
            if "original" in identity
            and (
                identity["original"] in unread
                or (self.originals[identity["original"]], catalog["fingerprint"])
                not in self.hits
            )
        }
        for blob, raw in self.guided.translation.engine.original_blobs(
            root, [*unread, *sorted(unmatched.difference(unread))]
        ):
            self.originals[blob] = digest(raw)
            if blob in unmatched:
                self.match(lambda raw=raw: raw, self.originals[blob], catalog)
        for relative, blob in originals.items():
            dependencies[relative] = self.originals[blob]
        hits = {key: [] for key in SELECTORS}
        for relative, (identity, path) in event_inputs.items():
            if "original" not in identity:
                self.match(path.read_bytes, dependencies[relative], catalog)
            for key in SELECTORS:
                hits[key].extend(
                    self.hits[(dependencies[relative], catalog["fingerprint"])][key]
                )
        value = {
            "version": 1,
            "project_id": project_id,
            "engine": native["engine"],
            "files": selected,
            "dependencies": dependencies,
            "original_blobs": originals,
            "runtime_dependencies": runtime_dependencies,
            "definitions": catalog["fingerprint"],
            "builtins": {key: sorted(set(value)) for key, value in hits.items()},
        }
        return {**value, "fingerprint": digest(value)}

    def match(self, read, fingerprint, catalog):
        """Records the registered built-ins one event file's commands use, once
        per file content and parser definitions; `read` returns its bytes."""
        signature = (fingerprint, catalog["fingerprint"])
        if signature in self.hits:
            return
        raw = read()
        found = {key: [] for key in SELECTORS}
        # Only commands coded 357, 355 or 655 hold built-ins; a file whose
        # text has none of these codes skips the parse.
        parsed = (
            json.loads(raw.decode("utf-8-sig"))
            if b"\\u" in raw or SELECTED_CODES.search(raw)
            else []
        )
        for command in commands(parsed):
            key = (
                "CODE357"
                if command["code"] == 357
                else "CODE355655"
                if command["code"] in (355, 655)
                else None
            )
            if (
                key
                and command["parameters"]
                and isinstance(command["parameters"][0], str)
            ):
                control = next(row for row in catalog["controls"] if row["key"] == key)
                found[key].extend(
                    marker
                    for marker in control["builtins"]
                    if marker in command["parameters"][0]
                )
        self.hits[signature] = found

    def request(self, project_id, native):
        catalog = self.catalog()
        context = self.context(project_id, native, catalog)
        if not context["files"]:
            raise ValueError(
                "Choose event files before requesting their investigation."
            )
        path = self.guided.path(project_id, "event-text-request")
        previous = read_json(path) if path.exists() else None
        if previous and previous.get("fingerprint") == context["fingerprint"]:
            return previous
        value = {
            **context,
            "request_id": uuid.uuid4().hex,
            "controls": catalog["controls"],
            "parser_source": catalog["source"],
        }
        write_json(path, value)
        return value

    def instructions(self, request, command):
        report = {
            key: request[key]
            for key in ("version", "request_id", "project_id", "engine", "fingerprint")
        }
        report["sources"] = {
            key: {
                "decision": "skip",
                "confidence": "low",
                "coverage": "uncertain",
                "reason": "Replace with inspected findings.",
                "targets": "" if key == "CODE122" else [],
                "observations": [],
                "exclusions": [],
                "evidence": [],
                **({"spacing": {}, "keep": []} if key in WORDED else {}),
            }
            for key in CODES
        }
        return f"""Investigate Other event text for this selected game and event scope only.
Read this request first: `{command}`. It returns the exact event files, dependencies, original-source hashes/blobs, installed parser path, registry identifiers, fixed argument keys, patterns, and built-in coverage.
Read immutable original game bytes when an original blob is supplied (`git cat-file blob <blob>` in the game folder); ordinary translated runtime files are not untranslated evidence. Compare plugin/script runtime bytes against their runtime_dependencies hashes and original bindings; account for changes in effective logic without editing them.
{git_note()}Inspect all matching occurrences in selected event files. Read the wider event corpus, Actors/System, enabled plugins and their implementations as dependencies to check internal references. These reads do not expand the files selected for translation.
For 122, check the entire start/end assignment range, operation and expression, all variable uses, comparisons, internal keys, IDs, filenames, and plugin/script consumers. The parser checks only the starting ID and replaces the expression; keep mixed, unproven or internally used assignments off.
For 357, report actual installed plugin names, commands and argument keys. Registered selections use fixed keys and substring header matches, plus the built-ins listed in the request. For 355/655, report capture boundaries and multiline behavior, plus every built-in match. Its variable-writing patterns are not protected by 122 IDs.
For 356, one switch enables every built-in handler; found command names are evidence, not individual configurable filters. Check 657 message values, 108 supported notetags, and 320/324/325 display changes against actual actor context.
356 and 108 translations join their words with "_" by default, since plugins split commands on spaces. For each built-in handler or marker found, read how its plugin parses and draws the text, and set its spacing: "space" when the plugin reads the rest of the text or joins the words back, and a space cannot change how it reads its other arguments (such as a trailing number read as a size); "nbsp" (U+00A0, drawn as a space) when it splits only on the plain space, as MV's command356 split(" ") does, and uses one argument whole; "underscore" only when it splits on any whitespace, such as a \\s pattern, which U+00A0 also matches. Underscores a plugin draws as they are do not hold a source off; note them in observations.
keep lists the exact original parameters[0] of each 356 command or 108 comment holding an internal value, such as a placeholder, key or file name; the engine leaves those untranslated.
Only recommend enable/high/safe when translating every remaining occurrence affected by the proposed settings is safe: text players see, or text they cannot reach, such as labels on unused test maps. Internal values must be left out by targets or keep, including built-ins and overlapping registry matches. Otherwise report review or skip with mixed/uncertain coverage. Explicitly list excluded internal/logic uses and unsupported finer filtering. Do not claim an exclusion is enforced unless targets or keep enforce it. Keep uncertain sources off. Report missing glossary evidence for review; retain existing selective glossary/context behavior.
Do not modify engine code, settings files, game text, scripts, glossary, or profiles. Do not run translation, estimation, providers, or a paid service. Write only a complete evidence report `{REPORT}` inside this game, atomically, apply it as described below, then stop. The user controls translation and Apply in DazedTL.

Report schema (replace every example; do not publish a template):
```json
{json.dumps(report, ensure_ascii=False, indent=2)}
```
Preserve all identity fields exactly and cover every listed source, with no extra settings. decision is enable/skip/review; confidence high/medium/low; coverage safe/mixed/uncertain/none. targets is compact variable IDs/ranges for 122, exact registered IDs for 357 and 355/655, and [] for coarse switches. observations and exclusions are lists of concise strings describing actual IDs, plugins, commands, keys, captures and exclusions with locations. Each source requires a reason and 1-50 evidence references {{"file":"game-relative JSON/JS/Ruby source", "sha256":"hash from request dependencies", "location":"precise event/page/command or plugin line"}}. Cite inspected dependencies only. New handlers or regexes belong in exclusions as unsupported work, never in targets. CODE356 and CODE108 also take spacing, which maps built-in handlers or markers listed for that code in the request to space, nbsp or underscore (unlisted ones use underscore), and keep, a list of exact original parameters[0] strings from the selected event files.
After saving, run `{command} --apply`. It validates the report and saves its recommendations as this game's source choices: sources reported enable/high/safe turn on with their targets, and every other source turns off. A stale, foreign or invalid report is rejected with the reason; fix the report and run the command again. If it reports a running action or unsaved guided options, ask the user to let the action finish or to save or discard the options in DazedTL, then run it again.
"""

    def inspect(self, project_id, native):
        catalog = self.catalog()
        context = self.context(project_id, native, catalog)
        defaults = self.unset()
        rows: list[dict[str, Any]] = [
            dict(
                row,
                decision="review",
                confidence="low",
                reason="Awaiting investigation.",
                coverageStatus="uncertain",
                targets="" if row["key"] == "CODE122" else [],
                observations=[],
                exclusions=[],
                evidence=[],
            )
            for row in catalog["controls"]
        ]
        result = {
            "status": "missing",
            "message": "Investigate the selected event text, or choose sources manually.",
            "reportId": None,
            "fingerprint": context["fingerprint"],
            "recommended": defaults,
            "rows": rows,
            "builtinHits": context["builtins"],
            "requestId": None,
        }
        path = self.guided.path(project_id, "event-text-request")
        if not path.exists():
            return result
        try:
            request = read_json(path, limit=4_000_000)
            result["requestId"] = request["request_id"]
            report_path = project_path(native["source"], REPORT, exists=False)
            report = (
                read_json(report_path, limit=4_000_000)
                if report_path.exists()
                else None
            )
            # Applied findings keep describing the files they covered, since
            # later edits to the game and its plugins are expected. Selecting
            # files they did not cover, or a change to the installed parser
            # definitions, still needs a new investigation.
            basis = (
                request
                if report is not None
                and native.get(RECEIPT, {}).get("reportId") == digest(report)
                and set(context["files"]) <= set(request["files"])
                and context["definitions"] == request["definitions"]
                else context
            )
            if request.get("fingerprint") != basis["fingerprint"]:
                return {
                    **result,
                    "status": "stale",
                    "message": "The event scope, source dependencies or installed handlers changed. Copy a refreshed investigation task.",
                }
            if report is None:
                return {
                    **result,
                    "status": "waiting",
                    "message": "Waiting for this investigation's saved findings.",
                }
            identity = {
                key: request[key]
                for key in (
                    "version",
                    "request_id",
                    "project_id",
                    "engine",
                    "fingerprint",
                )
            }
            if not isinstance(report, dict) or set(report) != {*identity, "sources"}:
                raise ValueError(
                    "Findings must contain the complete request identity and sources."
                )
            if any(
                report[key] != value or type(report[key]) is not type(value)
                for key, value in identity.items()
            ):
                # Findings for this project's earlier request wait for the
                # current one's, as after copying a refreshed task.
                if report["request_id"] != request["request_id"] and all(
                    report[key] == identity[key]
                    for key in ("version", "project_id", "engine")
                ):
                    return {
                        **result,
                        "status": "waiting",
                        "message": "Waiting for this investigation's saved findings.",
                    }
                return {
                    **result,
                    "status": "stale",
                    "message": "Findings belong to another project or investigation request.",
                }
            if not isinstance(report["sources"], dict) or set(report["sources"]) != set(
                CODES
            ):
                raise ValueError(
                    "Findings must cover every requested code family and no additional settings."
                )
            for row in rows:
                key, finding = row["key"], report["sources"][row["key"]]
                if (
                    not isinstance(finding, dict)
                    or set(finding)
                    != (FINDING | {"spacing", "keep"} if key in WORDED else FINDING)
                    or finding["decision"] not in {"enable", "skip", "review"}
                    or finding["confidence"] not in {"high", "medium", "low"}
                    or finding["coverage"] not in {"safe", "mixed", "uncertain", "none"}
                    or not isinstance(finding["reason"], str)
                    or not 1 <= len(finding["reason"].strip()) <= 4000
                ):
                    raise ValueError(
                        "Each source needs a supported decision, confidence, coverage and reason."
                    )
                for field in ("observations", "exclusions"):
                    if (
                        not isinstance(finding[field], list)
                        or len(finding[field]) > 500
                        or any(
                            not isinstance(value, str)
                            or not 1 <= len(value.strip()) <= 4000
                            for value in finding[field]
                        )
                    ):
                        raise ValueError(
                            "Observations and exclusions must be bounded text lists."
                        )
                proposed = {key: finding["decision"] == "enable"}
                if key == "CODE122":
                    proposed["CODE122_VAR_RANGES"] = finding["targets"]
                elif key in SELECTORS:
                    proposed[SELECTORS[key]] = finding["targets"]
                elif finding["targets"] != []:
                    raise ValueError(
                        "Coarse code switches cannot select individual commands or occurrences."
                    )
                notes = []
                if key in WORDED:
                    spacing, keep = finding["spacing"], finding["keep"]
                    if (
                        not isinstance(spacing, dict)
                        or set(spacing) - set(row["builtins"])
                        or set(spacing.values()) - SPACING
                    ):
                        raise ValueError(
                            "Spacing must map this code's built-in handlers to space, nbsp or underscore."
                        )
                    if (
                        not isinstance(keep, list)
                        or len(keep) > 500
                        or any(
                            not isinstance(value, str) or not 1 <= len(value) <= 4000
                            for value in keep
                        )
                    ):
                        raise ValueError(
                            "Commands to keep must be a bounded list of exact command texts."
                        )
                    spaces, nbsp, kept = WORDED[key]
                    for mode, option, label in (
                        ("space", spaces, "Keeps spaces"),
                        ("nbsp", nbsp, "Joins words with no-break spaces"),
                    ):
                        proposed[option] = sorted(
                            name for name, value in spacing.items() if value == mode
                        )
                        if proposed[option]:
                            notes.append(
                                f"{label}: {', '.join(name.strip() for name in proposed[option])}."
                            )
                    proposed[kept] = keep
                    notes.extend("Left untranslated: " + value for value in keep)
                proposed = self.guided.backend.guided_event_text_options(proposed)
                refs = finding["evidence"]
                if not isinstance(refs, list) or not 1 <= len(refs) <= 50:
                    raise ValueError("Each source needs inspected dependency evidence.")
                for ref in refs:
                    if (
                        not isinstance(ref, dict)
                        or set(ref) != {"file", "sha256", "location"}
                        or ref["file"] not in basis["dependencies"]
                        or ref["sha256"] != basis["dependencies"][ref["file"]]
                        or not isinstance(ref["location"], str)
                        or not 1 <= len(ref["location"].strip()) <= 1000
                    ):
                        raise ValueError(
                            "Evidence must match inspected request dependencies and include a precise location."
                        )
                row.update(
                    decision=finding["decision"],
                    confidence=finding["confidence"],
                    coverageStatus=finding["coverage"],
                    reason=finding["reason"],
                    targets=proposed.get(SELECTORS.get(key, "CODE122_VAR_RANGES"), []),
                    observations=[*notes, *finding["observations"]],
                    exclusions=finding["exclusions"],
                    evidence=refs,
                )
                if (
                    finding["decision"] == "enable"
                    and finding["confidence"] == "high"
                    and finding["coverage"] == "safe"
                ):
                    defaults.update(proposed)
            errors = self.structural(defaults, catalog, basis)
            if errors:
                raise ValueError("Unsupported recommendation: " + " ".join(errors))
            return {
                **result,
                "status": "ready",
                "message": "Investigation findings are saved.",
                "reportId": digest(report),
            }
        except (OSError, ValueError, UnicodeError, KeyError, TypeError) as exc:
            return {
                **result,
                "status": "invalid",
                "recommended": self.unset(),
                "message": "Findings could not be used. " + str(exc),
            }

    @staticmethod
    def structural(options, catalog, context):
        errors = []
        if options["CODE122"] and not options["CODE122_VAR_RANGES"].strip():
            errors.append("Enter explicit variable IDs for 122.")
        for code, selector in SELECTORS.items():
            if (
                options[code]
                and not options[selector]
                and not context["builtins"].get(code)
            ):
                errors.append(
                    "Select at least one registered "
                    + ("plugin handler" if code == "CODE357" else "script pattern")
                    + "; no built-in matches were found in this event scope."
                )
        return errors

    def status(self, project_id, native):
        # A poll reads it for the task and again for the advanced phase's quote.
        return self.guided.observations.once(
            ("event text", project_id), lambda: self._status(project_id, native)
        )

    def _status(self, project_id, native):
        try:
            findings = self.inspect(project_id, native)
        except (OSError, ValueError, UnicodeError, KeyError, TypeError) as exc:
            findings = {
                "status": "invalid",
                "message": "Event-text evidence needs recovery. " + str(exc),
                "reportId": None,
                "fingerprint": None,
                "recommended": {},
                "rows": [],
                "builtinHits": {},
                "requestId": None,
            }
        try:
            options = self.options(native)
            errors = self.structural(
                options, self.catalog(), {"builtins": findings["builtinHits"]}
            )
        except (ValueError, TypeError) as exc:
            options, errors = {}, [str(exc)]
        picker_path = self.guided.path(project_id, "event-text-picker")
        view_path = self.guided.path(project_id, "event-text-view")
        position_path = self.guided.path(project_id, "position")
        legacy = (
            read_json(position_path).get("task") if position_path.exists() else None
        )
        view = (
            legacy
            if legacy in VIEWS
            else read_json(view_path).get("view", "audit")
            if view_path.exists()
            else "audit"
        )
        return {
            **findings,
            "applied": findings["status"] == "ready"
            and native.get(RECEIPT, {}).get("reportId") == findings["reportId"],
            "errors": errors,
            "enabled": [key for key in CODES if options.get(key)],
            "view": view,
            "picker": read_json(picker_path) if picker_path.exists() else None,
        }

    def apply(self, project_id, revision, report_id):
        """Save current findings' recommendations as the source choices."""
        self.guided.idle()
        self.guided.clean_options(project_id)
        _, native = self.guided.record(project_id)
        if type(revision) is not int or native["revision"] != revision:
            raise ValueError(
                "The guided project changed. Reload before applying event text findings."
            )
        findings = self.inspect(project_id, native)
        if findings["status"] != "ready":
            raise ValueError(findings["message"])
        if findings["reportId"] != report_id:
            raise ValueError("The findings changed. Reload them before applying.")
        missing = self.unmatched(native, findings["recommended"])
        if missing:
            raise ValueError(
                "These commands to keep are not in the selected event files' original text: "
                + "; ".join(missing)
            )
        updated = self.guided.backend.workflows.apply_investigation_settings(
            native["id"],
            revision,
            findings["recommended"],
            RECEIPT,
            {"reportId": report_id},
        )
        return self.guided.preferences(updated)

    def unmatched(self, native, options):
        """Commands to keep that match no selected event file's original 356
        command or 108 comment, which would leave their internal values to
        translation."""
        wanted = {
            code: set(options[keys[2]])
            for code, keys in (("356", WORDED["CODE356"]), ("108", WORDED["CODE108"]))
            if options[keys[2]]
        }
        if not wanted:
            return []
        inputs = self.guided.inputs(native)
        sources = inputs.sources(
            sorted(self.guided.supported_files(native)),
            inputs.record()["inputs"],
            self.guided.observed_digest,
        )
        selected = self.guided.runs.files(native, "advanced")
        root = Path(native["source"])
        blobs, documents = [], []
        for name, source in sources.items():
            if name in selected:
                if "original" in source["identity"]:
                    blobs.append(source["identity"]["original"])
                else:
                    path = self.guided.observed_path(root, source["relative"])
                    documents.append(path.read_bytes())
        documents.extend(
            raw
            for _blob, raw in self.guided.translation.engine.original_blobs(root, blobs)
        )
        for raw in documents:
            for command in commands(json.loads(raw.decode("utf-8-sig"))):
                values = wanted.get(str(command["code"]))
                if values and command["parameters"]:
                    text = command["parameters"][0]
                    values.discard(text if isinstance(text, str) else None)
        return sorted(value for values in wanted.values() for value in values)

    def require(self, project_id, native):
        current = self.status(project_id, native)
        if current["errors"] or not current["enabled"]:
            raise ValueError(
                " ".join(current["errors"])
                or "Enable an event text source before translating event codes."
            )
        return {
            "reportId": current["reportId"],
            "fingerprint": current["fingerprint"],
            "settings": self.options(native),
        }

    def view(self, project_id, view):
        self.guided.record(project_id)
        if view not in VIEWS:
            raise ValueError("Choose an Other event text step.")
        write_json(self.guided.path(project_id, "event-text-view"), {"view": view})
        return {"saved": True}

    def picker(self, project_id, value):
        self.guided.idle()
        self.guided.record(project_id)
        if value is not None:
            if (
                not isinstance(value, dict)
                or set(value) != {"key", "selected", "baseline", "query", "filter"}
                or value["key"] not in SELECTORS.values()
                or value["filter"] not in {"all", "selected", "recommended"}
                or not isinstance(value["query"], str)
                or len(value["query"]) > 200
            ):
                raise ValueError("Invalid source-selection draft.")
            for field in ("selected", "baseline"):
                if (
                    not isinstance(value[field], list)
                    or len(value[field]) > 2000
                    or any(not isinstance(item, str) for item in value[field])
                    or len(set(value[field])) != len(value[field])
                ):
                    raise ValueError("Choose unique registry identifiers.")
        write_json(self.guided.path(project_id, "event-text-picker"), value)
        return {"saved": True}
