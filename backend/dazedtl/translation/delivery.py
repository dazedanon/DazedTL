"""Bind reported QA to the exact runtime files a local patch will contain."""

from .files import (
    evidence,
    project_path,
    read_json,
    verify_evidence,
    write_project_json,
)
from .project import WORK

RELATIVE = WORK + "/runtime-evidence.json"


def record(source, manifest_path, runtime_paths):
    paths = list(dict.fromkeys([manifest_path, *runtime_paths]))
    hashes = evidence(source, paths)
    stats = {}
    for relative in paths:
        stat = project_path(source, relative).stat()
        stats[relative] = [stat.st_size, stat.st_mtime_ns]
    value = {"version": 1, "files": hashes, "stats": stats}
    write_project_json(source, RELATIVE, value)
    return RELATIVE


def verify(source, *, full=False):
    path = project_path(source, RELATIVE, exists=False)
    if not path.exists():
        raise ValueError(
            "Record QA through the project helper so its runtime outputs are bound to the patch."
        )
    value = read_json(path)
    if value.get("version") != 1:
        raise ValueError(
            "The saved runtime QA evidence needs a compatible app version."
        )
    if full:
        verify_evidence(source, value["files"])
    else:
        for relative, expected in value["stats"].items():
            stat = project_path(source, relative).stat()
            if [stat.st_size, stat.st_mtime_ns] != expected:
                raise ValueError(
                    "Runtime files changed after QA. Review affected checks before packaging."
                )
    return value
