"""Project-owned estimates and paid approvals for the optional native image editor."""

from datetime import datetime, timezone
from pathlib import Path
import uuid

from dazedtl.api.views import job as public_job
from dazedtl.compatibility import image_translation as native
from dazedtl.storage import write_json
from dazedtl.translation.files import digest, read_json, project_path


class ImageNativeTranslation:
    def __init__(self, core, editor):
        self.core, self.editor = core, editor
        self.backend, self.settings = core.backend, core.settings
        self.previews = {}

    def _path(self, project_id):
        return self.core.workspace(project_id) / "native-editor/native-runs.json"

    def _records(self, project_id):
        self.core.record(project_id)
        path = self._path(project_id)
        value = (
            read_json(path, limit=8_000_000)
            if path.exists()
            else {"version": 1, "runs": {}}
        )
        if value.get("version") != 1 or not isinstance(value.get("runs"), dict):
            raise ValueError("The saved native image runs need recovery.")
        return value["runs"]

    def _write(self, project_id, records):
        write_json(self._path(project_id), {"version": 1, "runs": records})

    def _idle(self, project_id):
        if hasattr(self.core, "_idle"):
            self.core._idle(project_id)
        if self.backend.running() or self.core.translation.jobs.running():
            raise ValueError(
                "Finish or stop the active run before starting image translation."
            )

    def _inputs(self, project_id):
        _project, root = self.core.record(project_id)
        work = self.core.workspace(project_id) / "native-editor"
        binding_path, exchange_path = (
            work / "exchange-request.json",
            work / "image_text.json",
        )
        if not binding_path.is_file() or not exchange_path.is_file():
            raise ValueError(
                "Export confirmed image text to prepare the native translator."
            )
        binding = read_json(binding_path, limit=8_000_000)
        payload = read_json(exchange_path, limit=8_000_000)
        if binding.get("projectId") != project_id or payload != binding.get("payload"):
            raise ValueError(
                "Export confirmed image text again before estimating a new translation run."
            )
        ids = binding.get("assetIds")
        rows = self.core.resolve_assets(project_id, ids)
        if binding.get("sources") != {row["id"]: row.get("sourceHash") for row in rows}:
            raise ValueError(
                "Image sources changed after export. Review and export current text."
            )
        editor_state = self.editor.state(project_id, ids)
        current = {item["assetId"]: item for item in editor_state["images"]}
        paths = {
            Path(row["editablePath"])
            .relative_to(root / ".dazedtl/images")
            .as_posix(): row["id"]
            for row in rows
        }
        for image in payload.get("images", []):
            state = current.get(paths.get(image.get("image")))
            if state is None or state["status"] not in {
                "confirmed",
                "translated",
                "rendered",
            }:
                raise ValueError(
                    "Confirm corrected image source text before translation."
                )
            blocks = {block["id"]: block for block in state["blocks"]}
            for region in image.get("regions", []):
                block = blocks.get(region["id"])
                if (
                    not block
                    or block.get("source") != region.get("source")
                    or block.get("box") != region.get("box")
                    or block.get("target") != region.get("target")
                    or block.get("skip")
                ):
                    raise ValueError(
                        "Image editor text changed after export. Export a current exchange."
                    )
        configuration = self.settings.guided_configuration("translate")
        if payload.get("language") != configuration["language"]:
            raise ValueError(
                "The target language changed. Export current image text before estimating."
            )
        context = self.backend.guided_run_context()
        candidates = [
            root / ".dazedtl/glossary.txt",
            root / "glossary.txt",
            root / "translation_quirks.txt",
        ]
        for folder in (root / ".dazedtl/skills", root / "skills"):
            if folder.is_symlink():
                raise ValueError("Image guidance cannot follow symbolic links.")
            candidates.extend(sorted(folder.glob("*.md")))
        for path in candidates:
            if path.exists():
                safe = project_path(root, path.relative_to(root).as_posix())
                if safe.stat().st_size > 1_000_000:
                    raise ValueError("Image guidance must be below 1 MB per document.")
                context[path.relative_to(root).as_posix()] = digest(safe.read_bytes())
        value = {
            "projectId": project_id,
            "binding": digest(binding),
            "exchange": digest(exchange_path.read_bytes()),
            "configuration": configuration,
            "context": context,
            "editorRevision": editor_state["revision"],
        }
        return root, binding, exchange_path.read_bytes(), value, digest(value)

    def _owned(self, project_id, identity):
        record = self._records(project_id).get(identity)
        job = self.backend.manual.jobs.get(identity)
        if (
            not record
            or not job
            or job.get("engine") != "Image Text"
            or job.get("source") != str(native.input_folder(self.backend, project_id))
        ):
            raise ValueError("This native image run belongs to another project.")
        plan = self.backend.saved_run_configuration(identity)
        if plan.get("engine") != "Image Text" or plan.get("selected") != [
            "image_text.json"
        ]:
            raise ValueError("The saved native image run scope is invalid.")
        return record, job, plan

    def state(self, project_id):
        records = self._records(project_id)
        jobs = []
        for identity in reversed(list(records)):
            try:
                record, job, _plan = self._owned(project_id, identity)
                view = {**public_job(job), "imported": record.get("imported", False)}
                if job["mode"] != "estimate":
                    view["estimate"] = record.get("estimate")
                    configuration = record["inputs"]["configuration"]
                    view["imageConfiguration"] = {
                        key: configuration.get(key)
                        for key in (
                            "model",
                            "language",
                            "endpoint",
                            "entries_per_request",
                        )
                    }
                jobs.append(view)
            except (ValueError, OSError):
                continue
            if len(jobs) == 20:
                break
        current, error = None, ""
        try:
            _root, binding, _raw, value, fingerprint = self._inputs(project_id)
            current = {
                "fingerprint": fingerprint,
                "count": sum(
                    len(image["regions"]) for image in binding["payload"]["images"]
                ),
                "configuration": {
                    key: value["configuration"].get(key)
                    for key in ("model", "language", "endpoint", "entries_per_request")
                },
            }
        except (ValueError, OSError) as exc:
            error = str(exc)
        quote = next((job for job in jobs if job["mode"] == "estimate"), None)
        quote_current = bool(
            quote
            and current
            and quote["status"] == "complete"
            and quote.get("estimate")
            and records[quote["id"]]["fingerprint"] == current["fingerprint"]
        )
        active = self.backend.manual.active if self.backend.manual.running() else None
        return {
            "jobs": jobs,
            "job": next(
                (job for job in jobs if job["id"] == active), jobs[0] if jobs else None
            ),
            "activeId": active if active in records else None,
            "quote": quote,
            "quoteCurrent": quote_current,
            "current": current,
            "error": error,
            "providerEnabled": self.backend.allow_providers,
            "batchSupported": self.settings.translation_defaults()["batch_supported"],
        }

    def preview(self, project_id, mode):
        if mode not in {"estimate", "translate", "batch"}:
            raise ValueError("Choose an estimate, live translation or provider batch.")
        self._idle(project_id)
        root, binding, _raw, value, fingerprint = self._inputs(project_id)
        state = self.state(project_id)
        if mode != "estimate" and (
            not self.backend.allow_providers or not state["quoteCurrent"]
        ):
            raise ValueError(
                "Complete a current estimate before reviewing paid image translation."
            )
        if mode == "batch" and not state["batchSupported"]:
            raise ValueError("The selected provider does not support Batch.")
        token = uuid.uuid4().hex
        self.previews = {
            key: item
            for key, item in self.previews.items()
            if item["projectId"] != project_id
        }
        self.previews[token] = {
            "projectId": project_id,
            "mode": mode,
            "fingerprint": fingerprint,
        }
        return {
            "token": token,
            "mode": mode,
            "count": state["current"]["count"],
            "assetIds": binding["assetIds"],
            "configuration": state["current"]["configuration"],
            "estimate": (state["quote"] or {}).get("estimate"),
            "confirmation": mode != "estimate",
        }

    def start(self, project_id, token, approved=False):
        preview = self.previews.pop(token, None)
        if not preview or preview["projectId"] != project_id:
            raise ValueError("This image translation review expired. Review again.")
        if type(approved) is not bool or preview["mode"] != "estimate" and not approved:
            raise ValueError(
                "Approve the reviewed cost and scope before paid translation."
            )
        self._idle(project_id)
        root, binding, raw, value, fingerprint = self._inputs(project_id)
        if fingerprint != preview["fingerprint"]:
            raise ValueError(
                "Image scope, text, guidance or settings changed after review. Review again."
            )
        if preview["mode"] != "estimate" and not self.state(project_id)["quoteCurrent"]:
            raise ValueError(
                "The matching image translation estimate is no longer current."
            )
        self.settings.prepare_engine(mode=preview["mode"])
        estimate = (self.state(project_id)["quote"] or {}).get("estimate")
        with self.backend.context():
            inventory = native.stage(self.backend, project_id, raw)
            job = native.create(self.backend, inventory, root, preview["mode"])
            records = self._records(project_id)
            records[job["id"]] = {
                "fingerprint": fingerprint,
                "binding": binding,
                "inputs": value,
                "approved": approved,
                "estimate": estimate,
                "mode": preview["mode"],
                "created": datetime.now(timezone.utc).isoformat(),
            }
            self._write(project_id, records)
            self.backend.manual.resume(job["id"])
        return self.state(project_id)

    def action(self, project_id, run_id, action, arguments=None):
        arguments = arguments or {}
        record, job, plan = self._owned(project_id, run_id)
        if action == "stop":
            self.backend.manual.stop(run_id)
        elif action == "answer":
            self.backend.manual.answer(
                run_id, arguments.get("token"), arguments.get("approved")
            )
        elif action == "resume":
            self._idle(project_id)
            if job["mode"] != "estimate" and arguments.get("approved") is not True:
                raise ValueError(
                    "Review the saved image run's model and cost before resuming paid work."
                )
            self.settings.prepare_engine(mode=job["mode"], resume=plan)
            self.backend.manual.resume(run_id)
        elif action == "export":
            result = self.backend.manual.export(run_id)
            return {"state": self.state(project_id), "result": result}
        elif action == "import":
            # The receipt binds this output to its exported source and scope;
            # changing the current exchange cannot redirect a historical run.
            work = self.core.workspace(project_id) / "native-editor"
            current_binding = read_json(work / "exchange-request.json", limit=8_000_000)
            if digest(current_binding) != digest(record["binding"]):
                raise ValueError(
                    "The current image exchange differs from this saved run. Its outputs remain retained."
                )
            payload = native.output(self.backend, run_id)
            editor_state = self.editor.state(project_id, record["binding"]["assetIds"])
            result = self.editor.action(
                project_id,
                editor_state["revision"],
                "import",
                record["binding"]["assetIds"],
                {"payload": payload},
            )
            records = self._records(project_id)
            records[run_id]["imported"] = True
            self._write(project_id, records)
            return {"state": self.state(project_id), "result": result}
        else:
            raise ValueError("Unknown native image translation action.")
        return {"state": self.state(project_id), "result": {}}
