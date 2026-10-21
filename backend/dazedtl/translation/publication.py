"""Frozen, reviewed text publication with durable backups and guarded recovery."""

import json
import time
import uuid
from pathlib import Path

from dazedtl import system
from dazedtl.compatibility.game_write import write_game
from dazedtl.storage import write_bytes, write_json

from .files import digest, project_path, read_json

# How long a frozen review can still be published.
REVIEW_SECONDS = 1200
# Batches whose text may be in the game, and so can be restored.
IN_EFFECT = {"complete", "publishing", "recovery_needed"}
# The applied-output receipt's entries per file: each Apply's output, and the
# output as fitted to the Line widths.
SECTIONS = ("files", "written")


def records(folder):
    base = project_path(folder, "text-publications", exists=False)
    rows = []
    for path in base.glob("*/receipt.json"):
        if path.is_symlink() or path.parent.is_symlink():
            raise ValueError("Publication records cannot be symbolic links.")
        row = read_json(path)
        rows.append(row)
    return sorted(rows, key=lambda row: row["created"], reverse=True)


def history(folder):
    """Project completed restore effects without changing preserved receipts."""
    rows = records(folder)
    restored = set()
    for row in rows:
        if (
            row["id"] not in restored
            and row["state"] == "complete"
            and row.get("restores")
        ):
            restored.add(row["restores"])
    return [
        {**row, "state": "restored"} if row["id"] in restored else row for row in rows
    ]


def applied_before(folder, run, outputs):
    """Whether an earlier Apply published this saved run's output, so applying
    it now, as History's Reapply does, applies it again; Translate's Apply
    names its run too. An Apply saved before Applies named their run counts
    when it published every one of `outputs`, the run's hash per file."""
    published = {}
    for row in records(folder):
        # A batch History restored later still published its outputs.
        if row["kind"] != "export_selected" or row["state"] != "complete":
            continue
        if row.get("run") == run:
            return True
        if "run" not in row:
            for name, sha in row["next_outputs"].get("files", {}).items():
                published.setdefault(name, set()).add(sha)
    return bool(outputs) and all(
        sha in published.get(name, ()) for name, sha in outputs.items()
    )


def blocker(rows, identity):
    """The newest later batch still in the game that changed one of this
    batch's files, whose text restoring this one would take out too; None
    when no later batch did, so the batch restores on its own. `rows` is
    history(), newest first. A restore leaves its files as the batch before
    it had them, so it never blocks."""
    index = next(index for index, row in enumerate(rows) if row["id"] == identity)
    paths = {item["path"] for item in rows[index]["files"]}
    for row in rows[:index]:
        shared = paths & {item["path"] for item in row["files"]}
        if shared and row["kind"] != "runtime_restore" and row["state"] in IN_EFFECT:
            return {"id": row["id"], "kind": row["kind"], "files": sorted(shared)}
    return None


def _changed(record):
    """The applied-output entries a batch changed, as (section, name)."""
    prior, following = record["prior_outputs"], record["next_outputs"]
    return {
        (section, name)
        for section in SECTIONS
        for name in {*prior.get(section, {}), *following.get(section, {})}
        if prior.get(section, {}).get(name) != following.get(section, {}).get(name)
    }


def _reverted(current, record):
    """The applied outputs with only a batch's own entries put back as they
    were before it, so a later batch's entries for other files stay."""
    prior = record["prior_outputs"]
    changes = _changed(record)
    result = {
        **current,
        **{section: dict(current.get(section, {})) for section, _ in changes},
    }
    for section, name in changes:
        if name in prior.get(section, {}):
            result[section][name] = prior[section][name]
        else:
            result[section].pop(name, None)
    return result


def receipt_hash(folder):
    path = Path(folder) / "applied-outputs.json"
    if path.is_symlink():
        raise ValueError("Applied output receipts cannot be symbolic links.")
    return digest(path.read_bytes()) if path.exists() else None


def json_hash(value):
    return digest((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


def freeze(
    folder,
    root,
    candidates,
    kind,
    *,
    outputs=None,
    restore=None,
    overwrite=False,
    task=None,
    findings=None,
    sources=None,
    created=(),
    written=None,
    run=None,
):
    """Freeze both sides before the user reviews an exact destination batch.
    `task` names the QA task whose corrections the batch applies or undoes,
    and `findings` which of them. `sources` names saved files that hold
    candidates, such as a run's outputs, which publishing reads again and
    checks by hash instead of copies. `created` names files the batch may add
    to the game; a restore takes an added file out again, its candidate None,
    and puts back one a batch took out. `written` names the hashes of applied
    outputs that were fitted to the Line widths on the way, which the game
    then holds in place of the output's own. `run` names the saved run whose
    output an Apply publishes."""
    if not candidates:
        raise ValueError("Select at least one file or correction to apply.")
    _discard_unused(folder)
    identity = uuid.uuid4().hex
    base = project_path(folder, "text-publications/" + identity, exists=False)
    prior = Path(folder) / "applied-outputs.json"
    previous = read_json(prior) if prior.exists() else {"version": 1, "files": {}}
    following = {**previous, "files": {**previous.get("files", {}), **(outputs or {})}}
    if outputs or written:
        fitted = {
            name: value
            for name, value in previous.get("written", {}).items()
            if name not in (outputs or {})
        }
        following["written"] = {**fitted, **(written or {})}
    if restore:
        following = _reverted(previous, restore)
    rows = []
    for index, (name, raw) in enumerate(sorted(candidates.items())):
        target = project_path(root, name, exists=False)
        # A file a batch adds is absent before it, and after its restore.
        if not target.exists() and not (restore or name in created):
            raise ValueError("The game has no file " + name + ".")
        if raw is None and not restore:
            raise ValueError("Only a restore takes a file out of the game.")
        before = target.read_bytes() if target.exists() else None
        # A full overwrite backs up the bytes it replaces when it publishes.
        if not overwrite and before is not None:
            write_bytes(base / f"{index}.before", before)
        source = (sources or {}).get(name)
        if source is None and raw is not None:
            write_bytes(base / f"{index}.after", raw)
        rows.append(
            {
                "path": name,
                "before": _hash(before),
                "after": _hash(raw),
                "index": index,
                "size": len(raw or b""),
                "mode": target.stat().st_mode & 0o777 if before is not None else 0o644,
                **({"source": str(source)} if source is not None else {}),
            }
        )
    record = {
        "version": 1,
        "id": identity,
        "created": time.time(),
        "root": str(Path(root).resolve()),
        "kind": kind,
        "state": "reviewed",
        "files": rows,
        "overwrite": overwrite,
        "prior_outputs": previous,
        "next_outputs": following,
        "outputs_hash": receipt_hash(folder),
        "restores": restore["id"] if restore else None,
        "task": task,
        **({"findings": sorted(findings)} if findings else {}),
        **({"run": run} if run else {}),
    }
    index = Path(folder) / "source-inputs.json"
    record["source_inputs"] = digest(index.read_bytes()) if index.exists() else None
    write_json(base / "receipt.json", record)
    return {"id": identity, "sha256": digest(record), "files": rows}


def _hash(raw):
    """A file's digest, or None for a file that is not there."""
    return None if raw is None else digest(raw)


def _current(target):
    return target.read_bytes() if target.exists() else None


def _discard_unused(folder):
    """Removes reviews too old to publish and the copies finished batches
    froze of what they would write; each copy is as large as its files,
    gigabytes on a large game. Backups stay for restore."""
    base = project_path(folder, "text-publications", exists=False)
    for path in base.glob("*/receipt.json"):
        if path.is_symlink() or path.parent.is_symlink():
            continue
        try:
            row = read_json(path)
        except OSError, ValueError:
            continue
        if row.get("state") != "reviewed":
            # Batches number their files from 0; one still holding its
            # copies, such as one an earlier version finished, holds this.
            if (path.parent / "0.after").exists():
                _discard_candidates(path.parent)
        elif time.time() - row.get("created", 0) > REVIEW_SECONDS:
            system.remove_tree(path.parent, ignore_errors=True)


def _discard_candidates(base):
    """Removes a finished batch's frozen copies of what it wrote."""
    for path in base.glob("*.after"):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def load(folder, plan):
    identity = plan["id"]
    if (
        not isinstance(identity, str)
        or len(identity) != 32
        or any(c not in "0123456789abcdef" for c in identity)
    ):
        raise ValueError("Invalid publication identity.")
    base = project_path(folder, "text-publications/" + identity, exists=False)
    path = base / "receipt.json"
    if path.is_symlink() or base.is_symlink():
        raise ValueError("Unsafe publication record.")
    row = read_json(path)
    if (
        digest(row) != plan["sha256"]
        or row["state"] != "reviewed"
        or time.time() - row["created"] > REVIEW_SECONDS
    ):
        raise ValueError("This publication review expired or was already used.")
    return base, row


def _back_up(base, row, target):
    """Saves the bytes a full overwrite replaces, as the game holds them now."""
    before = target.read_bytes()
    row["before"], row["mode"] = digest(before), target.stat().st_mode & 0o777
    write_bytes(base / f"{row['index']}.before", before)
    return before


def publish(folder, root, plan, log=lambda _: None):
    base, record = load(folder, plan)
    index = Path(folder) / "source-inputs.json"
    if (digest(index.read_bytes()) if index.exists() else None) != record[
        "source_inputs"
    ]:
        raise ValueError("Original source bindings changed. Review again.")
    if (
        record["root"] != str(Path(root).resolve())
        or receipt_hash(folder) != record["outputs_hash"]
    ):
        raise ValueError(
            "Publication ownership or applied output state changed. Review again."
        )
    overwrite = record.get("overwrite")
    payloads = []
    for row in record["files"]:
        target = project_path(root, row["path"], exists=False)
        after = (
            None
            if row["after"] is None
            else (
                Path(row["source"])
                if "source" in row
                else project_path(base, f"{row['index']}.after")
            ).read_bytes()
        )
        before = (
            None
            if overwrite or row["before"] is None
            else project_path(base, f"{row['index']}.before").read_bytes()
        )
        if _hash(after) != row["after"] or (
            not overwrite
            and (
                _hash(before) != row["before"]
                or _hash(_current(target)) != row["before"]
            )
        ):
            raise ValueError(
                "A source, destination or frozen candidate changed. Review again."
            )
        payloads.append([target, row, before, after])
    with write_game(
        root, folder, log=log, paths=[row["path"] for row in record["files"]]
    ) as game:
        log("Publishing the reviewed batch; backups are retained.")
        if overwrite:
            # Explicit full-file Apply backs up the bytes present at the actual
            # overwrite, including edits made after its preview. Backing up every
            # file before the first write saves the receipt once: saved per file,
            # its writes grew with the square of the batch's files.
            for payload in payloads:
                payload[2] = _back_up(base, payload[1], payload[0])
        record["state"] = "publishing"
        write_json(base / "receipt.json", record)
        attempted = []
        try:
            for target, row, before, after in payloads:
                if _hash(_current(target)) != row["before"]:
                    if not overwrite:
                        raise ValueError("A runtime file changed during publication.")
                    # The game file changed since its backup moments ago.
                    before = _back_up(base, row, target)
                    write_json(base / "receipt.json", record)
                attempted.append((target, row, before, after))
                game.put(row["path"], after, row["mode"])
                if _hash(_current(target)) != row["after"]:
                    raise ValueError("Published bytes failed verification.")
            write_json(Path(folder) / "applied-outputs.json", record["next_outputs"])
            record["state"] = "complete"
            write_json(base / "receipt.json", record)
            _discard_candidates(base)
        except BaseException as failure:
            errors = []
            for target, row, before, after in reversed(attempted):
                try:
                    current = _hash(_current(target))
                    if current not in {row["before"], row["after"]}:
                        raise ValueError("newer runtime edit retained")
                    if current != row["before"]:
                        game.put(row["path"], before, row["mode"])
                    if _hash(_current(target)) != row["before"]:
                        raise ValueError("rollback verification failed")
                except BaseException as exc:  # noqa: BLE001
                    errors.append(row["path"] + ": " + str(exc))
            try:
                if receipt_hash(folder) == json_hash(record["next_outputs"]):
                    write_json(
                        Path(folder) / "applied-outputs.json", record["prior_outputs"]
                    )
            except BaseException as exc:  # noqa: BLE001
                errors.append("output receipt: " + str(exc))
            record.update(
                state="recovery_needed" if errors else "rolled_back",
                recovery_errors=errors,
            )
            write_json(base / "receipt.json", record)
            _discard_candidates(base)
            raise ValueError(
                "Publication failed. "
                + (
                    "Review restore; " + "; ".join(errors)
                    if errors
                    else "The attempted writes were rolled back."
                )
                + " "
                + str(failure)
            ) from failure
    return {
        "files": len(payloads),
        "publication": record["id"],
        "restored": record["restores"],
        "destination": str(root),
    }


def restore_candidates(folder, root, identity):
    rows = history(folder)
    record = next((row for row in rows if row["id"] == identity), None)
    if (
        not record
        or record["root"] != str(Path(root).resolve())
        or record["state"] not in IN_EFFECT
    ):
        raise ValueError("Choose an applied or interrupted publication to restore.")
    later = blocker(rows, identity)
    if later:
        raise ValueError(
            "A later batch also changed "
            + ", ".join(later["files"])
            + ". Restore that batch first, where History offers it."
        )
    path = Path(folder) / "applied-outputs.json"
    current = read_json(path) if path.exists() else {}
    replaced = sorted(
        name
        for section, name in _changed(record)
        if current.get(section, {}).get(name)
        not in {
            record["prior_outputs"].get(section, {}).get(name),
            record["next_outputs"].get(section, {}).get(name),
        }
    )
    if replaced:
        raise ValueError(
            "A later Apply replaced " + ", ".join(replaced) + ", so this batch "
            "can't be restored."
        )
    candidates = {}
    for row in record["files"]:
        target = project_path(root, row["path"], exists=False)
        if _hash(_current(target)) not in {row["before"], row["after"]}:
            raise ValueError(
                "Newer runtime edits conflict with restore: "
                + row["path"]
                + ". Keep those edits or review them separately."
            )
        # A file the batch added goes out again.
        raw = (
            None
            if row["before"] is None
            else project_path(
                folder, "text-publications/" + identity + f"/{row['index']}.before"
            ).read_bytes()
        )
        if _hash(raw) != row["before"]:
            raise ValueError("The preserved restore bytes changed.")
        candidates[row["path"]] = raw
    return candidates, record
