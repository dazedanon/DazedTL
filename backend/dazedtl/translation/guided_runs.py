"""Persist estimate identity and scope-specific state beside frozen native runs."""

from pathlib import Path
from contextlib import closing
import json
import re

from dazedtl.storage import write_json
from .files import digest, project_path, read_json

PHASES = ("database", "dialogue", "advanced", "variables")
JAPANESE = re.compile(r"[\u3000\u3002-\u3009\u300C-\u303F\u3040-\u309A\u309C-\u30FA\u31F0-\u31FF\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\uFF61-\uFF9F]+")


class GuidedRuns:
    def __init__(self, guided):
        self.guided = guided
        self.comparison_files = {}

    def records(self, project_id):
        path = self.guided.path(project_id, "runs")
        return read_json(path).get("runs", {}) if path.exists() else {}

    @staticmethod
    def current(runs, phase):
        """Newest attempt owns a task; dismissing it never revives an older one."""
        own = [job for job in runs if job.get('logicalPhase') == phase]
        active = next((job for job in own if job.get('mode') != 'estimate'
                       and job.get('status') in {'ready', 'running', 'waiting'}), None)
        latest = active or (own[0] if own else None)
        return latest if latest and latest.get('mode') != 'estimate' and (active or not latest.get('keptForHistory')) else None

    def files(self, native, phase):
        return sorted(set(self.guided.backend.phase_files(native, phase)).intersection(native["selected"]))

    def working_path(self, native, name, source):
        inputs = self.guided.inputs(native)
        for group in ("translated", "files"):
            path = inputs.path(group, name)
            if path.is_file():
                return path
        return project_path(inputs.source, source["relative"])

    def working_bytes(self, native, name, source):
        return self.working_path(native, name, source).read_bytes()

    def comparison_literals(self, path):
        fingerprint = self.guided.observed_digest(path)
        cached = self.comparison_files.get(path)
        if cached and cached[0] == fingerprint:
            return cached

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

        # Retain only parsed comparison literals, never whole game documents.
        # Selection, mappings, IGNORETLTEXT and review are checked on every read.
        raw = path.read_bytes()
        literals = []
        for index, command in enumerate(commands(json.loads(raw.decode("utf-8-sig")))):
            for parameter in command.get("parameters", []):
                if isinstance(parameter, str) and "$gameVariables" in parameter:
                    variables = sorted(set(re.findall(r"\$gameVariables\.value\(\s*(\d+)\s*\)", parameter)))
                    literals.extend((index, literal, variables) for literal in re.findall(r"['\"`](.*?)['\"`]", parameter))
        if len(self.comparison_files) >= 1024:
            self.comparison_files.clear()
        # Bind to the bytes actually parsed if a writer changed the file after
        # observed_digest; the next observation will invalidate this entry.
        result = (digest(raw), literals)
        self.comparison_files[path] = result
        return result

    def inputs(self, project_id, native, phase, mode, *, guard=None):
        names = self.files(native, phase)
        inputs = self.guided.inputs(native)
        sources = inputs.sources(names, inputs.record()["inputs"], self.guided.observed_digest)
        guard = guard if guard is not None else self.guided.backend.guided_guard(native, inputs.folder)
        # Native guards include other phases' work. Their selections and outputs
        # are independent; only shared frozen context belongs in every quote.
        context = {key: value for key, value in guard.items()
                   if key not in {"data", "files", "translated", "variables"}}
        versions = {name: inputs.record().get("file_versions", {}).get(name, "") for name in names}
        value = {"file_versions": versions, "version": 1, "project": project_id, "phase": phase, "mode": mode,
                 "source": sources, "source_pass": inputs.record().get("last_refresh"), "files": names,
                 "working": {name: digest(self.working_bytes(native, name, sources[name])) for name in names},
                 "configuration": self.guided.settings.guided_configuration(mode),
                 "options": native["engine_options"], "layout": native["widths"],
                 "comments": native["phase1_comments"], "context": context,
                 "runtime_context": self.guided.backend.guided_run_context()}
        review = None
        if phase == "advanced":
            review = self.guided.event_text.require(project_id, native)
            value["event_text_review"] = review
        if phase == "variables":
            value["variables"] = self.cache(native)[1]
            comparisons = self.comparisons(native)
            value["comparison_review"] = comparisons["status"]
            review = {"fingerprint": comparisons["fingerprint"], "status": comparisons["status"], "literalBased": True}
        return {"fingerprint": digest(value), "source": sources, "files": names, "phase": phase, "mode": mode, "review": review, "file_versions": versions}

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
            matched, missing, files, rows, working = 0, 0, [], [], {}
            for name in names:
                count = 0
                working[name], literals = self.comparison_literals(self.working_path(native, name, sources[name]))
                for command_index, literal, variables in literals:
                    if native["engine_options"].get("IGNORETLTEXT", True) and not JAPANESE.search(literal):
                        continue
                    if literal in cache:
                        matched += 1
                        count += 1
                        rows.append({"file": name, "location": "code 111 occurrence " + str(command_index + 1),
                                     "literal": literal, "translation": cache[literal], "variables": variables})
                    else:
                        missing += 1
                if count:
                    files.append(name)
            fingerprint = digest({"cache": cache, "working": working, "ignore": native["engine_options"].get("IGNORETLTEXT", True)})
            owner = next((item for item in self.guided.projects.data["projects"] if item.get("backend_id") == native["id"]), None)
            receipt_path = self.guided.path(owner["id"], "comparisons-review") if owner else None
            receipt = read_json(receipt_path) if receipt_path and receipt_path.exists() else {}
            reviewed = receipt.get("fingerprint") == fingerprint and receipt.get("accepted") is True
            return {"matches": matched, "unmatched": missing, "files": files, "rows": rows, "fingerprint": fingerprint,
                    "status": "not_needed" if not matched else "ready" if reviewed else "review_needed",
                    "message": "Literal mappings match selected comparisons. Review all affected variable uses; mappings are not restricted by variable ID." if matched else "No usable saved mappings match this event selection. Comparison update is not needed."}
        except (OSError, ValueError, UnicodeError) as exc:
            return {"matches": 0, "unmatched": 0, "files": [], "rows": [], "fingerprint": None, "status": "recovery_needed", "message": str(exc)}

    def remember(self, project_id, job, inputs, estimate=None, preparation_mode=None):
        records = self.records(project_id)
        records[job["id"]] = {**inputs, "estimate": estimate, "preparation_mode": preparation_mode}
        write_json(self.guided.path(project_id, "runs"), {"version": 1, "runs": records})

    def preparation_mode(self, project_id, identity):
        records = self.records(project_id)
        mode = records.get(identity, {}).get("preparation_mode")
        # A later run consuming this estimate owns the next stage, including
        # failed/canceled runs. Reopening an estimate must never start it again.
        if any((row.get("estimate") or {}).get("jobId") == identity for row in records.values()):
            return None
        return mode

    def continuation(self, project_id, native, inputs):
        from dazedtl.compatibility.process_view import ledger
        result = {}
        for identity, record in self.records(project_id).items():
            if (record['phase'] != inputs['phase'] or record['source'] != inputs['source']
                    or any(record.get('file_versions', {}).get(name, '') != inputs.get('file_versions', {}).get(name, '') for name in inputs['files'])):
                continue
            if identity not in self.guided.backend.manual.jobs:
                continue
            connection = ledger(self.guided.backend.manual.folder(identity))
            if connection is None:
                continue
            with closing(connection):
                if not connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='validated_items'").fetchone():
                    continue
                for key, source, response in connection.execute('SELECT identity,source,response FROM validated_items'):
                    row = {'source': source, 'response': json.loads(response)}
                    if key in result and row != result[key]:
                        raise ValueError('Saved validated responses conflict. Review this source in History.')
                    result[key] = row
        return result

    def quote(self, project_id, native, phase, mode, *, guard=None, run_view=None):
        inputs = self.inputs(project_id, native, phase, mode, guard=guard)
        records = self.records(project_id)
        jobs = getattr(self.guided.backend, "manual", None)
        jobs = jobs.jobs if jobs else {}
        owned = set(self.guided.owned_runs(native))
        for identity, record in reversed(list(records.items())):
            job = jobs.get(identity)
            if identity in owned and job and job.get("mode") == "estimate" and record["phase"] == phase:
                current = job["status"] == "complete" and bool(job.get("estimate")) and identity not in self.guided.inputs(native).record().get("retired_runs", []) and record["fingerprint"] == inputs["fingerprint"]
                return {"job": (run_view or self.guided.run_view)(identity, compact=True), "current": current}, inputs
        return {"job": None, "current": False}, inputs

    def snapshot(self, project_id, native, source_status, *, run_view=None):
        estimates, phases = {}, {}
        run_view = run_view or self.guided.run_view
        guard = self.guided.backend.guided_guard(native, self.guided.inputs(native).folder)
        mode = self.guided.preferences(native)["values"]["mode"]
        owned = self.guided.owned_runs(native)
        records = self.records(project_id)
        retired = set(source_status.get("retired", []))
        jobs = getattr(self.guided.backend, "manual", None)
        jobs = jobs.jobs if jobs else {}
        views = [run_view(identity, compact=True) for identity in owned if identity in jobs]
        for phase in PHASES:
            try:
                estimates[phase], current = self.quote(project_id, native, phase, mode, guard=guard, run_view=run_view)
            except (ValueError, OSError):
                estimates[phase] = {"job": None, "current": False}
                current = None
            names = self.files(native, phase)
            inputs = self.guided.inputs(native)
            sources = inputs.sources(names, inputs.record()["inputs"], self.guided.observed_digest)
            job = self.current(views, phase)
            if job and job['id'] not in retired and sorted(job.get('files', [])) == names:
                identity = job['id']
                record = records.get(identity)
                job["scopeComplete"] = bool(names and job["status"] == "complete" and job.get("outputsAvailable")
                    and not set(names).intersection([*job.get("retiredFiles", []), *job.get("partialOutputs", [])])
                    and set(names).issubset(job.get("outputs", {})) and not set(names).intersection(source_status["changed"])
                    and (not record or record["source"] == sources))
                phases[phase] = job
        return {"estimates": estimates, "phase_runs": phases, "comparisons": self.comparisons(native)}
