"""Retained investigation around the preserved event-text phases.

Saved findings apply their recommendations as the project's source choices.
"""

import json
import uuid
from pathlib import Path
from typing import Any

from dazedtl.storage import write_json

from .files import digest, project_path, read_json

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
FIELDS = (*CODES, "CODE122_VAR_RANGES", *SELECTORS.values())
REPORT = ".dazedtl/guided/event-text-findings.json"
# The project record key naming the report whose recommendations were applied.
RECEIPT = "guided_event_text"
VIEWS = {"audit", "sources", "advanced-run", "variables"}


class EventText:
    def __init__(self, guided):
        self.guided = guided
        self.originals = {}
        self.hits = {}

    def catalog(self):
        return self.guided.backend.guided_event_text_catalog()

    def options(self, native):
        values = {
            key: native["engine_options"].get(
                key,
                False if key in CODES else "" if key == "CODE122_VAR_RANGES" else [],
            )
            for key in FIELDS
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
        for name, source in sources.items():
            identity, relative = source["identity"], source["relative"]
            path = project_path(native["source"], relative)
            if "original" in identity:
                original = (str(inputs.source), identity["original"])
                if original not in self.originals:
                    self.originals[original] = digest(
                        inputs.original_bytes(inputs.source, identity["original"])
                    )
                dependencies[relative] = self.originals[original]
                originals[relative] = identity["original"]
            else:
                dependencies[relative] = self.guided.observed_digest(path)
            if name in selected:
                event_inputs[name] = (dependencies[relative], identity, path)
        root = Path(native["source"])
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
            path = project_path(root, relative)
            runtime_dependencies[relative] = self.guided.observed_digest(path)
            if relative in bindings:
                original = (str(root), bindings[relative])
                if original not in self.originals:
                    self.originals[original] = digest(
                        self.guided.translation.engine.original_bytes(
                            root, bindings[relative]
                        )
                    )
                dependencies[relative] = self.originals[original]
                originals[relative] = bindings[relative]
            else:
                dependencies[relative] = self.guided.observed_digest(path)
        hits = {key: [] for key in SELECTORS}

        def commands(value):
            if isinstance(value, list):
                for item in value:
                    yield from commands(item)
            elif isinstance(value, dict):
                if "code" in value and isinstance(value.get("parameters"), list):
                    yield value
                for key, item in value.items():
                    if key != "_original":
                        yield from commands(item)

        for fingerprint, identity, path in event_inputs.values():
            signature = (fingerprint, catalog["fingerprint"])
            if signature not in self.hits:
                raw = (
                    inputs.original_bytes(inputs.source, identity["original"])
                    if "original" in identity
                    else path.read_bytes()
                )
                found = {key: [] for key in SELECTORS}
                for command in commands(json.loads(raw.decode("utf-8-sig"))):
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
                        control = next(
                            row for row in catalog["controls"] if row["key"] == key
                        )
                        found[key].extend(
                            marker
                            for marker in control["builtins"]
                            if marker in command["parameters"][0]
                        )
                self.hits[signature] = found
            for key in SELECTORS:
                hits[key].extend(self.hits[signature][key])
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
            }
            for key in CODES
        }
        return f"""Investigate Other event text for this selected game and event scope only.
Read this request first: `{command}`. It returns the exact event files, dependencies, original-source hashes/blobs, installed parser path, registry identifiers, fixed argument keys, patterns, and built-in coverage.
Read immutable original game bytes when an original blob is supplied (`git cat-file blob <blob>` in the game folder); ordinary translated runtime files are not untranslated evidence. Compare plugin/script runtime bytes against their runtime_dependencies hashes and original bindings; account for changes in effective logic without editing them.
Inspect all matching occurrences in selected event files. Read the wider event corpus, Actors/System, enabled plugins and their implementations as dependencies to check internal references. These reads do not expand the files selected for translation.
For 122, check the entire start/end assignment range, operation and expression, all variable uses, comparisons, internal keys, IDs, filenames, and plugin/script consumers. The parser checks only the starting ID and replaces the expression; keep mixed, unproven or internally used assignments off.
For 357, report actual installed plugin names, commands and argument keys. Registered selections use fixed keys and substring header matches, plus the built-ins listed in the request. For 355/655, report capture boundaries and multiline behavior, plus every built-in match. Its variable-writing patterns are not protected by 122 IDs.
For 356, one switch enables every built-in handler; found command names are evidence, not individual configurable filters. Check 657 message values, 108 supported notetags, and 320/324/325 display changes against actual actor context.
Only recommend enable/high/safe when every occurrence affected by the proposed supported settings is verified player-visible and safe, including built-ins and overlapping registry matches. Otherwise report review or skip with mixed/uncertain coverage. Explicitly list excluded internal/logic uses and unsupported finer filtering. Do not claim an exclusion is enforced when it shares enabled coverage. Keep uncertain sources off. Report missing glossary evidence for review; retain existing selective glossary/context behavior.
Do not modify engine code, settings files, game text, scripts, glossary, or profiles. Do not run translation, estimation, providers, or a paid service. Write only a complete evidence report `{REPORT}` inside this game, atomically, apply it as described below, then stop. The user controls translation and Apply in DazedTL.

Report schema (replace every example; do not publish a template):
```json
{json.dumps(report, ensure_ascii=False, indent=2)}
```
Preserve all identity fields exactly and cover every listed source, with no extra settings. decision is enable/skip/review; confidence high/medium/low; coverage safe/mixed/uncertain/none. targets is compact variable IDs/ranges for 122, exact registered IDs for 357 and 355/655, and [] for coarse switches. observations and exclusions are lists of concise strings describing actual IDs, plugins, commands, keys, captures and exclusions with locations. Each source requires a reason and 1-50 evidence references {{"file":"game-relative JSON/JS/Ruby source", "sha256":"hash from request dependencies", "location":"precise event/page/command or plugin line"}}. Cite inspected dependencies only. New handlers or regexes belong in exclusions as unsupported work, never in targets.
After saving, run `{command} --apply`. It validates the report and saves its recommendations as this game's source choices: sources reported enable/high/safe turn on with their targets, and every other source turns off. A stale, foreign or invalid report is rejected with the reason; fix the report and run the command again. If it reports a running action or unsaved guided options, ask the user to let the action finish or to save or discard the options in DazedTL, then run it again.
"""

    def inspect(self, project_id, native):
        catalog = self.catalog()
        context = self.context(project_id, native, catalog)
        defaults = {
            key: False if key in CODES else "" if key == "CODE122_VAR_RANGES" else []
            for key in FIELDS
        }
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
                    != {
                        "decision",
                        "confidence",
                        "coverage",
                        "reason",
                        "targets",
                        "observations",
                        "exclusions",
                        "evidence",
                    }
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
                    observations=finding["observations"],
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
                "recommended": {
                    key: False
                    if key in CODES
                    else ""
                    if key == "CODE122_VAR_RANGES"
                    else []
                    for key in FIELDS
                },
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
        updated = self.guided.backend.workflows.apply_investigation_settings(
            native["id"],
            revision,
            findings["recommended"],
            RECEIPT,
            {"reportId": report_id},
        )
        return self.guided.preferences(updated)

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
