"""Persist estimate identity and scope-specific state beside frozen native runs."""

from pathlib import Path
import re

from dazedtl.storage import write_json
from .files import digest, project_path, read_json

PHASES = ("database", "dialogue", "advanced", "variables")
JAPANESE = re.compile(r"[\u3000\u3002-\u3009\u300C-\u303F\u3040-\u309A\u309C-\u30FA\u31F0-\u31FF\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\uFF61-\uFF9F]+")


class GuidedRuns:
    def __init__(self, guided):
        self.guided = guided

    def records(self, project_id):
        path = self.guided.path(project_id, "runs")
        return read_json(path).get("runs", {}) if path.exists() else {}

    def files(self, native, phase):
        return sorted(set(self.guided.backend.phase_files(native, phase)).intersection(native["selected"]))

    def working_bytes(self, native, name, source):
        inputs = self.guided.inputs(native)
        for group in ("translated", "files"):
            path = inputs.path(group, name)
            if path.is_file():
                return path.read_bytes()
        identity = source["identity"]
        return (inputs.original_bytes(inputs.source, identity["original"]) if "original" in identity
                else project_path(inputs.source, source["relative"]).read_bytes())

    def inputs(self, project_id, native, phase, mode, *, guard=None):
        names = self.files(native, phase)
        inputs = self.guided.inputs(native)
        sources = inputs.sources(names, inputs.record()["inputs"], self.guided.observed_digest)
        guard = guard if guard is not None else self.guided.backend.guided_guard(native, inputs.folder)
        # Native guards include other phases' work. Their selections and outputs
        # are independent; only shared frozen context belongs in every quote.
        context = {key: value for key, value in guard.items()
                   if key not in {"data", "files", "translated", "variables"}}
        value = {"version": 1, "project": project_id, "phase": phase, "mode": mode,
                 "source": sources, "source_pass": inputs.record().get("last_refresh"), "files": names,
                 "working": {name: digest(self.working_bytes(native, name, sources[name])) for name in names},
                 "configuration": self.guided.settings.guided_configuration(mode),
                 "options": native["engine_options"], "layout": native["widths"],
                 "comments": native["phase1_comments"], "context": context,
                 "runtime_context": self.guided.backend.guided_run_context()}
        if phase == "variables":
            value["variables"] = self.cache(native)[1]
        return {"fingerprint": digest(value), "source": sources, "files": names, "phase": phase, "mode": mode}

    def cache(self, native):
        path = self.guided.backend.workflows.folder(native["id"]) / "log/var_translation_map.json"
        if path.is_symlink() or path.parent.is_symlink():
            raise ValueError("The saved variable mappings cannot be symbolic links.")
        if not path.is_file():
            return {}, None
        value = read_json(path, limit=10_000_000)
        if not isinstance(value, dict) or any(not isinstance(key, str) or not isinstance(text, str) for key, text in value.items()):
            raise ValueError("The saved variable mappings need recovery before updating comparisons.")
        return {key: text for key, text in value.items() if key and key != text}, self.guided.observed_digest(path)

    def comparisons(self, native):
        try:
            cache, _ = self.cache(native)
            names = self.files(native, "variables")
            inputs = self.guided.inputs(native)
            sources = inputs.sources(names, inputs.record()["inputs"], self.guided.observed_digest)
            matched, missing, files = 0, 0, []
            import json
            def commands(value):
                if isinstance(value, list):
                    for item in value:
                        yield from commands(item)
                elif isinstance(value, dict):
                    if value.get("code") == 111:
                        yield value
                    for key, item in value.items():
                        if key != "_original":
                            yield from commands(item)
            for name in names:
                count = 0
                for command in commands(json.loads(self.working_bytes(native, name, sources[name]).decode("utf-8-sig"))):
                    for parameter in command.get("parameters", []):
                        if not isinstance(parameter, str) or "$gameVariables" not in parameter:
                            continue
                        for literal in re.findall(r"['\"`](.*?)['\"`]", parameter):
                            if native["engine_options"].get("IGNORETLTEXT", True) and not JAPANESE.search(literal):
                                continue
                            if literal in cache:
                                matched += 1
                                count += 1
                            else:
                                missing += 1
                if count:
                    files.append(name)
            return {"matches": matched, "unmatched": missing, "files": files,
                    "message": "Saved assignment translations can update matching comparisons." if matched else "No usable saved mappings match this event selection. This step is not needed."}
        except (OSError, ValueError, UnicodeError) as exc:
            return {"matches": 0, "unmatched": 0, "files": [], "message": str(exc)}

    def remember(self, project_id, job, inputs, estimate=None):
        records = self.records(project_id)
        records[job["id"]] = {**inputs, "estimate": estimate}
        write_json(self.guided.path(project_id, "runs"), {"version": 1, "runs": records})

    def quote(self, project_id, native, phase, mode, *, guard=None):
        inputs = self.inputs(project_id, native, phase, mode, guard=guard)
        records = self.records(project_id)
        jobs = getattr(self.guided.backend, "manual", None)
        jobs = jobs.jobs if jobs else {}
        owned = set(self.guided.owned_runs(native))
        for identity, record in reversed(list(records.items())):
            job = jobs.get(identity)
            if identity in owned and job and job.get("mode") == "estimate" and record["phase"] == phase:
                current = job["status"] == "complete" and bool(job.get("estimate")) and identity not in self.guided.inputs(native).record().get("retired_runs", []) and record["fingerprint"] == inputs["fingerprint"]
                return {"job": self.guided.run_view(identity, compact=True), "current": current}, inputs
        return {"job": None, "current": False}, inputs

    def snapshot(self, project_id, native, source_status):
        estimates, phases = {}, {}
        guard = self.guided.backend.guided_guard(native, self.guided.inputs(native).folder)
        mode = self.guided.preferences(native)["values"]["mode"]
        owned = self.guided.owned_runs(native)
        records = self.records(project_id)
        retired = set(source_status.get("retired", []))
        jobs = getattr(self.guided.backend, "manual", None)
        jobs = jobs.jobs if jobs else {}
        for phase in PHASES:
            try:
                estimates[phase], current = self.quote(project_id, native, phase, mode, guard=guard)
            except (ValueError, OSError):
                estimates[phase] = {"job": None, "current": False}
                current = None
            names = self.files(native, phase)
            inputs = self.guided.inputs(native)
            sources = inputs.sources(names, inputs.record()["inputs"], self.guided.observed_digest)
            for identity in owned:
                if identity not in jobs or identity in retired or jobs[identity].get("mode") == "estimate":
                    continue
                job = self.guided.run_view(identity, compact=True)
                if job.get("logicalPhase") != phase or sorted(job.get("files", [])) != names:
                    continue
                record = records.get(identity)
                job["scopeComplete"] = bool(names and job["status"] == "complete" and job.get("outputsAvailable")
                    and set(names).issubset(job.get("outputs", {})) and not set(names).intersection(source_status["changed"])
                    and (not record or record["source"] == sources))
                phases[phase] = job
                break
        return {"estimates": estimates, "phase_runs": phases, "comparisons": self.comparisons(native)}
