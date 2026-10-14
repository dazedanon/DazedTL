"""Persist estimate identity and scope-specific state beside frozen native runs."""

import json
import re
from contextlib import closing

from dazedtl.storage import write_json

from . import repricing
from .files import digest, read_json

PHASES = ("database", "dialogue", "advanced", "variables")
JAPANESE = re.compile(
    r"[\u3000\u3002-\u3009\u300C-\u303F\u3040-\u309A\u309C-\u30FA\u31F0-\u31FF\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\uFF61-\uFF9F]+"
)


class GuidedRuns:
    def __init__(self, guided):
        self.guided = guided
        self.comparison_files = {}
        # The game glossary revision a name publish last failed on.
        self.name_failures = {}

    def records(self, project_id):
        return self.guided.observations.once(
            ("records", project_id), lambda: self._records(project_id)
        )

    def _records(self, project_id):
        path = self.guided.path(project_id, "runs")
        records = read_json(path).get("runs", {}) if path.exists() else {}
        jobs = getattr(getattr(self.guided.backend, "manual", None), "jobs", {})
        return {
            identity: record
            for identity, record in records.items()
            if not record.get("temporary") or identity in jobs
        }

    @staticmethod
    def current(runs, phase):
        """Newest attempt owns a task; stale pointers never revive an older one."""
        own = [job for job in runs if job.get("logicalPhase") == phase]
        active = next(
            (
                job
                for job in own
                if job.get("mode") != "estimate"
                and job.get("status") in {"ready", "running", "waiting"}
            ),
            None,
        )
        latest = active or (own[0] if own else None)
        return latest if latest and latest.get("mode") != "estimate" else None

    def files(self, native, phase):
        return sorted(
            set(self.guided.backend.phase_files(native, phase)).intersection(
                native["selected"]
            )
        )

    def working_path(self, native, name, source):
        inputs = self.guided.inputs(native)
        for group in ("translated", "files"):
            if inputs.saved(group, name):
                return inputs.path(group, name)
        return inputs.game_path(source["relative"])

    def working_digest(self, native, name, source):
        # A poll's phases share each file's digest, reused while the file is
        # unchanged; execution reads it afresh.
        if self.guided.observations.files() is None:
            return digest(self.working_path(native, name, source).read_bytes())
        return self.guided.observations.once(
            ("working digest", native["id"], name, source["relative"]),
            lambda: self.guided.observed_digest(
                self.working_path(native, name, source)
            ),
        )

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
        # Most files never name a variable; JSON without \u escapes spells it
        # only one way, so they skip the parse.
        parsed = (
            json.loads(raw.decode("utf-8-sig"))
            if b"$gameVariables" in raw or b"\\u" in raw
            else []
        )
        for index, command in enumerate(commands(parsed)):
            for parameter in command.get("parameters", []):
                if isinstance(parameter, str) and "$gameVariables" in parameter:
                    variables = sorted(
                        set(
                            re.findall(
                                r"\$gameVariables\.value\(\s*(\d+)\s*\)", parameter
                            )
                        )
                    )
                    literals.extend(
                        (index, literal, variables)
                        for literal in re.findall(r"['\"`](.*?)['\"`]", parameter)
                    )
        if len(self.comparison_files) >= 1024:
            self.comparison_files.clear()
        # Bind to the bytes actually parsed if a writer changed the file after
        # observed_digest; the next observation will invalidate this entry.
        result = (digest(raw), literals)
        self.comparison_files[path] = result
        return result

    def inputs(
        self,
        project_id,
        native,
        phase,
        mode,
        *,
        guard=None,
        cached_only=False,
        names=None,
    ):
        """What a phase's estimate binds to; names defaults to its selection."""
        names = self.files(native, phase) if names is None else names
        inputs = self.guided.inputs(native)
        record = inputs.record()
        sources = inputs.sources(names, record["inputs"], self.guided.observed_digest)
        guard = (
            guard
            if guard is not None
            else self.guided.backend.guided_guard(native, inputs.folder)
        )
        # Native guards include other phases' work. Their selections and outputs
        # are independent; only shared frozen context belongs in every quote.
        context = {
            key: value
            for key, value in guard.items()
            if key not in {"data", "files", "translated", "variables"}
        }
        versions = {
            name: record.get("file_versions", {}).get(name, "") for name in names
        }
        # A snapshot reads cached prices only, which may not be known yet.
        configuration = self.guided.observations.once(
            ("configuration", mode, cached_only),
            lambda: self.guided.settings.guided_configuration(
                mode, cached_only=cached_only, unpriced=cached_only
            ),
        )
        reused_names = self.name_reuse(native, configuration.get("language"))
        value = {
            "file_versions": versions,
            "version": 1,
            "project": project_id,
            "phase": phase,
            "mode": mode,
            "source": sources,
            "source_pass": record.get("last_refresh"),
            "files": names,
            "working": {
                name: self.working_digest(native, name, sources[name]) for name in names
            },
            "configuration": configuration,
            "reused_names": reused_names,
            "options": native["engine_options"],
            "layout": native["widths"],
            "comments": native["phase1_comments"],
            "context": context,
            "runtime_context": self.guided.backend.guided_run_context(),
        }
        review = None
        if phase == "advanced":
            review = self.guided.event_text.require(project_id, native)
            value["event_text_review"] = review
        if phase == "variables":
            value["variables"] = self.cache(native)[1]
            comparisons = self.comparisons(native)
            value["comparison_review"] = comparisons["status"]
            review = {
                "fingerprint": comparisons["fingerprint"],
                "status": comparisons["status"],
                "literalBased": True,
            }
        return {
            "fingerprint": digest(value),
            # What the estimate's requests depend on, which a switch that only
            # prices them (repricing) leaves alone.
            "shape": digest(
                {**value, "configuration": repricing.unpriced(configuration)}
            ),
            "configuration": configuration,
            "source": sources,
            "files": names,
            "phase": phase,
            "mode": mode,
            "review": review,
            "file_versions": versions,
            "reused_names": reused_names,
        }

    def repriced(self, project_id, native, identity, inputs):
        """A finished estimate's figures at the prices of ``inputs`` when
        they only price its requests differently, else None."""
        from dazedtl.compatibility.estimate_prices import reprice

        record = self.records(project_id).get(identity, {})
        estimate = self.guided.backend.manual.jobs.get(identity, {}).get("estimate")
        if (
            not estimate
            or record.get("shape") != inputs["shape"]
            or identity in self.guided.inputs(native).record().get("retired_runs", [])
            or not repricing.priced(inputs["configuration"])
            or not repricing.same_requests(
                record["configuration"], inputs["configuration"]
            )
        ):
            return None
        return reprice(estimate, inputs["configuration"])

    def publish_names(self, project_id, native):
        """Adds paid names the game glossary lacks once no run can collect it.

        Collecting a completed run copies its glossary, names included, over
        the game's and refuses one changed since the run began. A Batch
        declined or stopped before its own approval, with nothing sent, can
        never complete, so the names it paid for are added here, once per run."""
        from dazedtl.compatibility.batch_continuation import APPROVAL
        from dazedtl.compatibility.process_view import evidence_root, saved
        from dazedtl.compatibility.speaker_results import merge_missing

        jobs = getattr(getattr(self.guided.backend, "manual", None), "jobs", {})
        latest = jobs.get(native.get("manual_job") or "")
        if (
            not latest
            or latest.get("mode") != "batch"
            or latest.get(APPROVAL)
            or latest.get("status") in {"ready", "running", "waiting"}
            or self.guided.backend.running()
            or self.guided.translation.jobs.running()
        ):
            return
        path = self.guided.path(project_id, "published-names")
        published = set(read_json(path).get("runs", [])) if path.exists() else set()
        root = self.guided.backend.manual.folder(latest["id"])
        if (
            latest["id"] in published
            # Approving the names records submission intent too; only a sent
            # Batch can still be continued without the Batch's own approval.
            or saved(evidence_root(root), "batch_history.json").get("batches")
            or "glossary"
            in self.guided.backend.workflows.state(native["id"])
            .get("draft", {})
            .get("documents", {})
        ):
            return
        # Only the language: every snapshot runs this, and a connection
        # without cached prices must not make the project unavailable.
        rows = [
            row
            for row in self.name_reuse(native, self.guided.settings.language())
            if row["runId"] not in published
        ]
        if not rows:
            return
        try:
            glossary = self.guided.backend.workflows.documents(native["id"])["glossary"]
        except OSError, ValueError:
            return
        if self.name_failures.get(project_id) == glossary["revision"]:
            return
        from util.translation import (
            parseVocabWithCategories,
            speaker_source_lookup_keys,
            split_vocab_source_aliases,
        )

        text, added = merge_missing(
            glossary["text"],
            rows,
            parseVocabWithCategories,
            split_vocab_source_aliases,
            speaker_source_lookup_keys,
        )
        try:
            if added:
                self.guided.backend.workflows.document_save(
                    native["id"], "glossary", glossary["revision"], text
                )
            write_json(
                path,
                {
                    "version": 1,
                    "runs": sorted(published | {row["runId"] for row in rows}),
                },
            )
        except OSError, ValueError:
            # The names stay reusable from their runs; try again once the
            # glossary changes.
            self.name_failures[project_id] = glossary["revision"]

    def name_reuse(self, native, language):
        return self.guided.observations.once(
            ("names", native["id"], language),
            lambda: self._name_reuse(native, language),
        )

    def _name_reuse(self, native, language):
        from dazedtl.compatibility.preparations import temporary
        from dazedtl.compatibility.speaker_results import RECEIPT, reusable

        if not language:
            return []
        inputs = self.guided.inputs(native).record()
        versions, retired = (
            inputs.get("file_versions", {}),
            set(inputs.get("retired_runs", [])),
        )
        candidates = []
        for identity in self.guided.owned_runs(native):
            job = self.guided.backend.manual.jobs.get(identity)
            if (
                not job
                or identity in retired
                or job.get("mode") == "estimate"
                or temporary(job)
            ):
                continue
            root = self.guided.backend.manual.folder(identity)
            if (
                not (job.get("estimate") or {}).get("speakers")
                and not (root / "log" / RECEIPT).is_file()
            ):
                continue
            try:
                plan = self.guided.run_configuration(identity)
                if (
                    (plan.get("workflow") or {}).get("id") != native["id"]
                    or (plan.get("settings") or {}).get("language") != language
                    or any(
                        versions.get(name, "")
                        != plan.get("dazedtl_source_versions", {}).get(name, "")
                        for name in job.get("files", [])
                    )
                ):
                    continue
                candidates.append((root, job))
            except OSError, ValueError, KeyError:
                continue
        return reusable(candidates)

    def cache(self, native):
        path = (
            self.guided.backend.workflows.folder(native["id"])
            / "log/var_translation_map.json"
        )
        if path.is_symlink() or path.parent.is_symlink():
            raise ValueError("The saved variable mappings cannot be symbolic links.")
        if not path.is_file():
            return {}, None
        value = read_json(path, limit=10_000_000)
        if not isinstance(value, dict) or any(
            not isinstance(key, str) or not isinstance(text, str)
            for key, text in value.items()
        ):
            raise ValueError(
                "The saved variable mappings need recovery before updating comparisons."
            )
        return {
            key: text for key, text in value.items() if key and key != text
        }, self.guided.observed_digest(path)

    def comparisons(self, native):
        return self.guided.observations.once(
            ("comparisons", native["id"]), lambda: self._comparisons(native)
        )

    def _comparisons(self, native):
        try:
            cache, _ = self.cache(native)
            names = self.files(native, "variables")
            inputs = self.guided.inputs(native)
            sources = inputs.sources(
                names, inputs.record()["inputs"], self.guided.observed_digest
            )
            matched, missing, files, rows, working = 0, 0, [], [], {}
            for name in names:
                count = 0
                working[name], literals = self.comparison_literals(
                    self.working_path(native, name, sources[name])
                )
                for command_index, literal, variables in literals:
                    if native["engine_options"].get(
                        "IGNORETLTEXT", True
                    ) and not JAPANESE.search(literal):
                        continue
                    if literal in cache:
                        matched += 1
                        count += 1
                        rows.append(
                            {
                                "file": name,
                                "location": "code 111 occurrence "
                                + str(command_index + 1),
                                "literal": literal,
                                "translation": cache[literal],
                                "variables": variables,
                            }
                        )
                    else:
                        missing += 1
                if count:
                    files.append(name)
            fingerprint = digest(
                {
                    "cache": cache,
                    "working": working,
                    "ignore": native["engine_options"].get("IGNORETLTEXT", True),
                }
            )
            owner = next(
                (
                    item
                    for item in self.guided.projects.data["projects"]
                    if item.get("backend_id") == native["id"]
                ),
                None,
            )
            receipt_path = (
                self.guided.path(owner["id"], "comparisons-review") if owner else None
            )
            receipt = (
                read_json(receipt_path)
                if receipt_path and receipt_path.exists()
                else {}
            )
            reviewed = (
                receipt.get("fingerprint") == fingerprint
                and receipt.get("accepted") is True
            )
            return {
                "matches": matched,
                "unmatched": missing,
                "files": files,
                "rows": rows,
                "fingerprint": fingerprint,
                "status": "not_needed"
                if not matched
                else "ready"
                if reviewed
                else "review_needed",
                "message": "Literal mappings match selected comparisons. Review all affected variable uses; mappings are not restricted by variable ID."
                if matched
                else "No usable saved mappings match this event selection. Comparison update is not needed.",
            }
        except (OSError, ValueError, UnicodeError) as exc:
            return {
                "matches": 0,
                "unmatched": 0,
                "files": [],
                "rows": [],
                "fingerprint": None,
                "status": "recovery_needed",
                "message": str(exc),
            }

    def remember(self, project_id, job, inputs, estimate=None, preparation_mode=None):
        records = self.records(project_id)
        records[job["id"]] = {
            **inputs,
            "estimate": estimate,
            "preparation_mode": preparation_mode,
            "temporary": bool(job.get("dazedtl_preapproval")),
        }
        write_json(
            self.guided.path(project_id, "runs"), {"version": 1, "runs": records}
        )

    def preparation_mode(self, project_id, identity):
        records = self.records(project_id)
        mode = records.get(identity, {}).get("preparation_mode")
        # A later run consuming this estimate owns the next stage, including
        # failed/canceled runs. Reopening an estimate must never start it again.
        if any(
            (row.get("estimate") or {}).get("jobId") == identity
            for row in records.values()
        ):
            return None
        return mode

    def continuation(self, project_id, native, inputs):
        from dazedtl.compatibility.process_view import ledger
        from dazedtl.translation.refusals import text_refusal

        result = {}
        jobs = self.guided.backend.manual.jobs
        # Newer compatible attempts own reusable wording. Historical variants
        # are normal, and must not prevent even estimating the remaining text.
        # Creation time (not later polling/resume updates) determines precedence;
        # the ID breaks ties independently of registry serialization order.
        records = sorted(
            self.records(project_id).items(),
            key=lambda item: (jobs.get(item[0], {}).get("created", ""), item[0]),
            reverse=True,
        )
        for identity, record in records:
            if record["phase"] != inputs["phase"]:
                continue
            shared = set(record["files"]).intersection(inputs["files"])
            eligible = {
                name
                for name in shared
                if record["source"].get(name) == inputs["source"].get(name)
                and record.get("file_versions", {}).get(name, "")
                == inputs.get("file_versions", {}).get(name, "")
            }
            if not eligible:
                continue
            if identity not in self.guided.backend.manual.jobs:
                continue
            if (
                self.guided.backend.saved_run_configuration(identity).get("workflow")
                or {}
            ).get("id") != native["id"]:
                continue
            connection = ledger(self.guided.backend.manual.folder(identity))
            if connection is None:
                continue
            with closing(connection):
                if not connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='validated_items'"
                ).fetchone():
                    continue
                provenance = (
                    dict(
                        connection.execute(
                            "SELECT identity,filename FROM validated_provenance"
                        )
                    )
                    if connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name='validated_provenance'"
                    ).fetchone()
                    else {}
                )
                # Legacy identities already include the filename. If every
                # selected old file still matches, entries for unselected files
                # cannot match the new worker's file-bound keys. Otherwise only
                # explicitly file-scoped legacy entries may be reused.
                legacy_allowed = None
                if shared - eligible:
                    legacy_allowed = set()
                    columns = {
                        row[1]
                        for row in connection.execute("PRAGMA table_info(requests)")
                    }
                    if {"filename", "sources"}.issubset(columns):
                        for filename, sources in connection.execute(
                            "SELECT filename,sources FROM requests"
                        ):
                            if filename in eligible and sources:
                                legacy_allowed.update(json.loads(sources) or [])
                for key, source, response in connection.execute(
                    "SELECT identity,source,response FROM validated_items"
                ):
                    if key in provenance:
                        if provenance[key] not in eligible:
                            continue
                    elif legacy_allowed is not None and key not in legacy_allowed:
                        continue
                    value = json.loads(response)
                    if not text_refusal(value, (source,)):
                        result.setdefault(key, {"source": source, "response": value})
        return result

    def quote(
        self,
        project_id,
        native,
        phase,
        mode,
        *,
        guard=None,
        run_view=None,
        cached_only=False,
    ):
        inputs = self.inputs(
            project_id, native, phase, mode, guard=guard, cached_only=cached_only
        )
        records = self.records(project_id)
        jobs = getattr(self.guided.backend, "manual", None)
        jobs = jobs.jobs if jobs else {}
        owned = set(self.guided.owned_runs(native))
        for identity, record in reversed(list(records.items())):
            job = jobs.get(identity)
            if (
                identity in owned
                and job
                and job.get("mode") == "estimate"
                and record["phase"] == phase
            ):
                current = (
                    job["status"] == "complete"
                    and bool(job.get("estimate"))
                    and identity
                    not in self.guided.inputs(native).record().get("retired_runs", [])
                    and (
                        record["fingerprint"] == inputs["fingerprint"]
                        or record.get("shape") == inputs["shape"]
                        and repricing.unknown_prices(
                            record["configuration"], inputs["configuration"]
                        )
                    )
                )
                view = (run_view or self.guided.run_view)(identity, compact=True)
                # A model switch that keeps its requests prices it again.
                repriced = (
                    None
                    if current or job["status"] != "complete"
                    else self.repriced(project_id, native, identity, inputs)
                )
                if repriced:
                    view, current = {**view, "estimate": repriced}, True
                return {"job": view, "current": current}, inputs
        return {"job": None, "current": False}, inputs

    def poll_guard(self, native):
        """The guard a quote binds to. Quotes read only its shared parts, so a
        poll hashes no game data or working copies for it."""
        observed = self.guided.observations.files()
        if observed is None:
            return self.guided.backend.guided_guard(
                native, self.guided.inputs(native).folder
            )
        return self.guided.observations.once(
            ("guard context", native["id"]),
            lambda: self.guided.backend.guided_guard_context(native, observed),
        )

    def snapshot(self, project_id, native, source_status, *, run_view=None):
        estimates, phases = {}, {}
        run_view = run_view or self.guided.run_view
        guard = self.poll_guard(native)
        mode = self.guided.preferences(native)["values"]["mode"]
        owned = self.guided.owned_runs(native)
        records = self.records(project_id)
        retired = set(source_status.get("retired", []))
        jobs = getattr(self.guided.backend, "manual", None)
        jobs = jobs.jobs if jobs else {}
        views = [
            run_view(identity, compact=True) for identity in owned if identity in jobs
        ]
        for phase in PHASES:
            # Cached prices only, so a snapshot never waits on a pricing
            # lookup; preparing, reviewing and starting a run check fully.
            try:
                estimates[phase], _ = self.quote(
                    project_id,
                    native,
                    phase,
                    mode,
                    guard=guard,
                    run_view=run_view,
                    cached_only=True,
                )
            except ValueError, OSError:
                estimates[phase] = {"job": None, "current": False}
            names = self.files(native, phase)
            inputs = self.guided.inputs(native)
            sources = inputs.sources(
                names, inputs.record()["inputs"], self.guided.observed_digest
            )
            job = self.current(views, phase)
            if (
                job
                and job["id"] not in retired
                and sorted(job.get("files", [])) == names
            ):
                identity = job["id"]
                record = records.get(identity)
                job["scopeComplete"] = bool(
                    names
                    and job["status"] == "complete"
                    and job.get("outputsAvailable")
                    and not set(names).intersection(
                        [*job.get("retiredFiles", []), *job.get("partialOutputs", [])]
                    )
                    and set(names).issubset(job.get("outputs", {}))
                    and not set(names).intersection(source_status["changed"])
                    and (not record or record["source"] == sources)
                )
                phases[phase] = job
        return {
            "estimates": estimates,
            "phase_runs": phases,
            "comparisons": self.comparisons(native),
        }
