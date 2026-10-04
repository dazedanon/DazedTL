"""Source-bound speaker findings from the Guided setup task, never inferred from prose."""

import json
import re
import uuid

from dazedtl.storage import write_json
from .files import digest, project_path, read_json

REPORT = ".dazedtl/guided/speaker-findings.json"
KEYS = ("NAMES", "FIRSTLINESPEAKERS", "INLINE401SPEAKERS", "FACENAME101", "AUTONAMEPOPUP101", "SPEAKERS408")


def overrides(native):
    receipt = native.get("guided_speakers", {})
    return sorted(set(receipt.get("overrides", [])) | {
        key for key, value in receipt.get("values", {}).items()
        if native["engine_options"].get(key, False) != value
    })


def request(path, project_id, native, schema):
    rules = {field["key"]: field["label"] for field in schema if field["key"] in KEYS and field["type"] == "boolean"}
    value = {"version": 1, "request_id": uuid.uuid4().hex, "project_id": project_id,
             "engine": native["engine"], "rules": rules,
             "baseline": {key: native["engine_options"].get(key, False) for key in rules},
             "baseline_report": native.get("guided_speakers", {}).get("reportId")}
    if path.exists():
        previous = read_json(path, limit=100_000)
        if isinstance(previous, dict) and {key: item for key, item in previous.items() if key != "request_id"} == {key: item for key, item in value.items() if key != "request_id"}:
            return previous  # Re-copying a pending task must not retire its eventual findings.
    write_json(path, value)
    return value


def instructions(value, command):
    example = {key: {"decision": "skip", "confidence": "low", "reason": "Replace with the investigation's conclusion.",
                     "evidence": [{"file": "data/Map001.json", "sha256": "SHA256_OF_FINAL_FILE_BYTES",
                                   "location": "event 4, page 1, commands 12–15"}]}
               for key in value["rules"]}
    report = {key: value[key] for key in ("version", "request_id", "project_id", "engine")}
    report["rules"] = example
    return f"""
## Combined speaker discovery and context task — follow this order

1. Identify how this game's speakers are represented: explicit code-101 names, name tags,
   first-line names, inline names, actor/variable references, face mappings, and relevant plugins.
   Check the source examples and exceptions. This is the format investigation, before the broader
   glossary/context investigation. Do not ask the user to guess speaker flags.
2. Save the evidence-backed rules below, then run the local speaker scanner. It applies those
   rules and collects original nameplates without translating them or making paid API calls.
3. Use the scanner's discovered names as additional evidence for the full glossary, character,
   terminology, voice, and context investigation described after this section. Verify names in
   their scenes; a detected name or variable placeholder is not an approved spelling or identity.

This sequence replaces the legacy manual Speaker settings/Collect names instructions below.
Existing glossary spellings remain provisional evidence. After identifying the formats, atomically
write `{REPORT}` inside the selected game using this schema:

```json
{json.dumps(report, ensure_ascii=False, indent=2)}
```

Keep the identity fields exactly as supplied. Include every listed rule, and no other settings.
Replace every example with actual format findings; do not publish a template or partial format check.
Each rule needs decision `enable` or `skip`, confidence `high`, `medium`, or `low`, a concise reason,
and 1–20 source references with game-relative file paths, SHA-256 of the final bytes, and precise
event/page/command or plugin line locators. Use inspected game JSON, JavaScript, or Ruby sources,
not generated reports as evidence. Include representative counterexamples and coverage in the reason.
High means the pattern and its exceptions have been checked across the relevant event corpus,
and the actual engine rule is supported by direct evidence. Medium means plausible but incomplete;
low means ambiguous or unsupported. Do not turn an uncertain guess into a high-confidence finding.
The app enables only `enable` + `high`; all other recommendations stay off. Existing manual
overrides are retained. Always-on speaker formats need no optional flag.
Face filenames alone are not proof. FACENAME101 additionally requires stable one-to-one mappings
that the existing engine actually supports; do not enable it for shared sheets, unknown mappings,
or isolated exceptions. AutoNamePopup requires an enabled plugin and verified face/index mapping.
Do not modify engine code, app profiles, or submit paid work. Report uncertainties explicitly.
Write findings after any speaker-format repairs, so their hashes describe the final evidence.

Start the app's local scan (this also applies the verified rules):
`{command} --scan`

Then poll its read-only status until `job.status` is `complete` and `current` is true:
`{command}`

Use the returned `names`, `actorNames`, `variableActorIds` and `.dazedtl/guided/speakers.json` for
step 3. `names` contains collected literal nameplates; the actor/variable tables are separate
source lookup data, not proof that every database actor speaks. Variable mappings are parser hints;
inspect assignments and runtime changes before treating them as identities. Resolve referenced IDs using
their actual game context. Check the entire discovery result, not only a sample. A failed or stale scan is not complete;
resolve its reported issue before continuing. If game data changes later in the investigation,
refresh affected format findings and scan again before finishing. The scan is a local tool action,
not the legacy paid name-translation run. No provider connection is needed.
The app must be running with this project initialized. If loopback access is blocked, use the
assistant's normal permission flow for this helper and verify its read-only status before retrying
a scan. Inspect saved status after a lost response; do not assume the scan failed to start.
After collecting names, continue the full investigation below in this same task. Do not stop at
the speaker report. Line widths and other settings retain their existing workflow.
"""


def inspect(request_path, native, project_id, observed_digest):
    empty = {"status": "missing", "message": "Investigate the game first. Speaker rules will be configured from its findings.",
             "reportId": None, "rules": [], "overrides": overrides(native)}
    if not request_path.exists():
        return empty
    try:
        expected = read_json(request_path, limit=100_000)
        path = project_path(native["source"], REPORT, exists=False)
        if not path.exists():
            return {**empty, "status": "waiting", "message": "Waiting for the setup task’s saved speaker findings."}
        report = read_json(path, limit=200_000)
        if not isinstance(report, dict) or set(report) != {"version", "request_id", "project_id", "engine", "rules"}:
            raise ValueError("Speaker findings are incomplete. Ask the setup assistant to finish the structured report.")
        report_id = digest(report)
        applied = native.get("guided_speakers", {}).get("reportId") == report_id
        if (report["project_id"] != project_id or report["engine"] != native["engine"] or type(report["version"]) is not int or report["version"] != 1
                or report["request_id"] != expected["request_id"] and not applied):
            return {**empty, "status": "waiting", "message": "Waiting for findings from this game’s latest setup task."}
        if not isinstance(report["rules"], dict) or set(report["rules"]) != set(expected["rules"]):
            raise ValueError("Speaker findings must cover every requested rule and no additional settings.")
        rows = []
        changed = False
        for key, label in expected["rules"].items():
            rule = report["rules"][key]
            if (not isinstance(rule, dict) or set(rule) != {"decision", "confidence", "reason", "evidence"}
                    or rule["decision"] not in ("enable", "skip") or rule["confidence"] not in ("high", "medium", "low")
                    or not isinstance(rule["reason"], str) or not 1 <= len(rule["reason"].strip()) <= 4000
                    or not isinstance(rule["evidence"], list) or not 1 <= len(rule["evidence"]) <= 20):
                raise ValueError("Each speaker rule needs a decision, confidence, reason, and source evidence.")
            for ref in rule["evidence"]:
                if (not isinstance(ref, dict) or set(ref) != {"file", "sha256", "location"}
                        or not isinstance(ref["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", ref["sha256"])
                        or not isinstance(ref["location"], str) or not 1 <= len(ref["location"].strip()) <= 1000
                        or not isinstance(ref["file"], str) or len(ref["file"]) > 2000
                        or any(part.startswith(".") for part in ref["file"].split("/"))):
                    raise ValueError("Speaker evidence needs a game source path, SHA-256, and a precise location.")
                source = project_path(native["source"], ref["file"], exists=not applied)
                if source.suffix.lower() not in {".json", ".js", ".rb"}:
                    raise ValueError("Cite inspected game JSON, JavaScript, or Ruby sources for speaker rules.")
                # Applied settings remain a record of the investigated source;
                # ordinary translation must not invalidate that historic result.
                if not applied and observed_digest(source) != ref["sha256"]:
                    changed = True
            rows.append({"key": key, "label": label, **rule})
        if changed:
            return {"status": "stale", "message": "Speaker findings are saved. Refresh the investigation before applying rules to changed source files.",
                    "reportId": report_id, "rules": rows, "overrides": overrides(native)}
        return {"status": "applied" if applied else "ready", "message": "Speaker findings applied." if applied else "Speaker findings are ready to apply.",
                "reportId": report_id, "rules": rows, "overrides": overrides(native)}
    except (OSError, ValueError, UnicodeError, KeyError, TypeError) as exc:
        return {**empty, "status": "invalid", "message": "Speaker findings could not be used. " + (str(exc) if isinstance(exc, ValueError) else "Ask the setup assistant to check its saved report.")}


def configured(request_path, native, findings, *, reset=False):
    expected = read_json(request_path, limit=100_000)
    keep = set() if reset else set(overrides(native))
    if not reset and native.get("guided_speakers", {}).get("reportId") == expected["baseline_report"]:
        keep.update(key for key, value in expected["baseline"].items() if native["engine_options"].get(key, False) != value)
    desired = {rule["key"]: rule["decision"] == "enable" and rule["confidence"] == "high" for rule in findings["rules"]}
    options = {**native["engine_options"], **{key: value for key, value in desired.items() if key not in keep}}
    receipt = {"reportId": findings["reportId"], "values": desired, "overrides": sorted(keep)}
    return options, receipt
