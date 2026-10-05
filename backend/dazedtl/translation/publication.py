"""Frozen, reviewed text publication with durable backups and guarded recovery."""

import json
import time
import uuid
from pathlib import Path

from dazedtl.storage import write_bytes, write_json

from .files import digest, project_path, read_json


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


def receipt_hash(folder):
    path = Path(folder) / "applied-outputs.json"
    if path.is_symlink():
        raise ValueError("Applied output receipts cannot be symbolic links.")
    return digest(path.read_bytes()) if path.exists() else None


def json_hash(value):
    return digest((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


def freeze(
    folder, root, candidates, kind, *, outputs=None, restore=None, overwrite=False
):
    """Freeze both sides before the user reviews an exact destination batch."""
    if not candidates:
        raise ValueError("Select at least one file or correction to apply.")
    identity = uuid.uuid4().hex
    base = project_path(folder, "text-publications/" + identity, exists=False)
    prior = Path(folder) / "applied-outputs.json"
    previous = read_json(prior) if prior.exists() else {"version": 1, "files": {}}
    following = {**previous, "files": {**previous.get("files", {}), **(outputs or {})}}
    if restore:
        following = restore["prior_outputs"]
    rows = []
    for index, (name, raw) in enumerate(sorted(candidates.items())):
        target = project_path(root, name)
        before = target.read_bytes()
        write_bytes(base / f"{index}.before", before)
        write_bytes(base / f"{index}.after", raw)
        rows.append(
            {
                "path": name,
                "before": digest(before),
                "after": digest(raw),
                "index": index,
                "size": len(raw),
                "mode": target.stat().st_mode & 0o777,
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
    }
    index = Path(folder) / "source-inputs.json"
    record["source_inputs"] = digest(index.read_bytes()) if index.exists() else None
    write_json(base / "receipt.json", record)
    return {"id": identity, "sha256": digest(record), "files": rows}


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
        or time.time() - row["created"] > 1200
    ):
        raise ValueError("This publication review expired or was already used.")
    return base, row


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
    payloads = []
    for row in record["files"]:
        target = project_path(root, row["path"])
        before = project_path(base, f"{row['index']}.before").read_bytes()
        after = project_path(base, f"{row['index']}.after").read_bytes()
        if (
            digest(before) != row["before"]
            or digest(after) != row["after"]
            or (
                not record.get("overwrite")
                and digest(target.read_bytes()) != row["before"]
            )
        ):
            raise ValueError(
                "A source, destination or frozen candidate changed. Review again."
            )
        payloads.append((target, row, before, after))
    log("Publishing the reviewed batch; backups are retained.")
    record["state"] = "publishing"
    write_json(base / "receipt.json", record)
    attempted = []
    try:
        for target, row, before, after in payloads:
            if record.get("overwrite"):
                # Explicit full-file Apply backs up the bytes present at the
                # actual overwrite, including edits made after its preview.
                before = target.read_bytes()
                row["before"], row["mode"] = (
                    digest(before),
                    target.stat().st_mode & 0o777,
                )
                write_bytes(base / f"{row['index']}.before", before)
                write_json(base / "receipt.json", record)
            elif digest(target.read_bytes()) != row["before"]:
                raise ValueError("A runtime file changed during publication.")
            attempted.append((target, row, before, after))
            write_bytes(target, after)
            target.chmod(row["mode"])
            if digest(target.read_bytes()) != row["after"]:
                raise ValueError("Published bytes failed verification.")
        write_json(Path(folder) / "applied-outputs.json", record["next_outputs"])
        record["state"] = "complete"
        write_json(base / "receipt.json", record)
    except BaseException as failure:
        errors = []
        for target, row, before, after in reversed(attempted):
            try:
                current = digest(target.read_bytes())
                if current not in {row["before"], row["after"]}:
                    raise ValueError("newer runtime edit retained")
                if current != row["before"]:
                    write_bytes(target, before)
                    target.chmod(row["mode"])
                if digest(target.read_bytes()) != row["before"]:
                    raise ValueError("rollback verification failed")
            except BaseException as exc:
                errors.append(row["path"] + ": " + str(exc))
        try:
            if receipt_hash(folder) == json_hash(record["next_outputs"]):
                write_json(
                    Path(folder) / "applied-outputs.json", record["prior_outputs"]
                )
        except BaseException as exc:
            errors.append("output receipt: " + str(exc))
        record.update(
            state="recovery_needed" if errors else "rolled_back", recovery_errors=errors
        )
        write_json(base / "receipt.json", record)
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
    record = next((row for row in records(folder) if row["id"] == identity), None)
    if (
        not record
        or record["root"] != str(Path(root).resolve())
        or record["state"] not in {"complete", "publishing", "recovery_needed"}
    ):
        raise ValueError("Choose an applied or interrupted publication to restore.")
    if receipt_hash(folder) not in {
        record["outputs_hash"],
        json_hash(record["next_outputs"]),
    }:
        raise ValueError(
            "A later publication changed the output receipt. Restore the latest batch first."
        )
    candidates = {}
    for row in record["files"]:
        target = project_path(root, row["path"])
        if digest(target.read_bytes()) not in {row["before"], row["after"]}:
            raise ValueError(
                "Newer runtime edits conflict with restore: "
                + row["path"]
                + ". Keep those edits or review them separately."
            )
        raw = project_path(
            folder, "text-publications/" + identity + f"/{row['index']}.before"
        ).read_bytes()
        if digest(raw) != row["before"]:
            raise ValueError("The preserved restore bytes changed.")
        candidates[row["path"]] = raw
    return candidates, record
