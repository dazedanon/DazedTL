"""Run the preserved Image Text module through its normal isolated job owner."""

from pathlib import Path

from dazedtl.storage import write_bytes
from dazedtl.translation.files import digest, read_json


def input_folder(backend, project_id):
    path = backend.workspace / "asset-projects" / project_id / "translation-input"
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError("Native image translation storage cannot follow symbolic links.")
    return path


def stage(backend, project_id, raw):
    path = input_folder(backend, project_id)
    path.mkdir(parents=True, exist_ok=True)
    target = path / "image_text.json"
    if target.is_symlink():
        raise ValueError("Image text input must be a regular file.")
    write_bytes(target, raw)
    return backend.manual.inspect(str(path), "Image Text", managed=True)


def create(backend, inventory, root, mode):
    job = backend.manual.start(inventory["source"], "Image Text", ["image_text.json"], inventory["revision"],
                               mode, context_source=str(root), managed=True, launch=False)
    # Ownership is recorded by the caller before any worker can execute.
    backend.manual.save(backend.manual.jobs[job["id"]])
    return job


def output(backend, run_id):
    job = backend.manual.jobs[run_id]
    if job["status"] != "complete" or job["mode"] == "estimate":
        raise ValueError("Complete this image translation run before importing its targets.")
    path = backend.manual.folder(run_id) / "translated/image_text.json"
    payload = read_json(path, limit=8_000_000)
    if digest(path.read_bytes()) != job.get("outputs", {}).get("image_text.json"):
        raise ValueError("The saved image translation output changed after completion.")
    return payload
