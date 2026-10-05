"""Manage phased working copies without replacing saved work on selection changes."""

import uuid
from pathlib import Path

from dazedtl.storage import write_bytes, write_json

from .files import decode_json, digest, project_path, read_json


def original_bindings(record):
    result = {}
    for row in record["inputs"].values():
        identity = row["identity"]
        if "original" in identity:
            result[row["relative"]] = identity["original"]
        elif "native_original" in identity:
            native = identity["native_original"]
            result[native["path"]] = native["blob"]
    return result


class GuidedInputs:
    def __init__(
        self, folder, source, data, bindings, original_bytes, *, native_exports=False
    ):
        self.folder, self.source, self.data = Path(folder), Path(source), Path(data)
        self.bindings, self.original_bytes = bindings, original_bytes
        self.native_exports = native_exports
        self.index = self.folder / "source-inputs.json"

    def path(self, group, name):
        if (
            not isinstance(name, str)
            or Path(name).name != name
            or not name.endswith(".json")
        ):
            raise ValueError("Choose a supported game JSON file.")
        path = self.folder / group / name
        for parent in (self.folder, path.parent, path):
            if parent.is_symlink():
                raise ValueError("Working copies cannot follow symbolic links.")
        if path.exists() and not path.is_file():
            raise ValueError("A working copy must be a regular file.")
        return path

    def record(self):
        value = (
            read_json(self.index)
            if self.index.exists()
            else {"version": 1, "inputs": {}}
        )
        if value.get("version") != 1 or not isinstance(value.get("inputs"), dict):
            raise ValueError(
                "The working-source index needs recovery before preparing new work."
            )
        return value

    def settle(self, phase, versions, checked):
        """Record files a finished estimate found without text to translate."""
        if not versions:
            return
        record = self.record()
        settled = record.get("no_requests", {})
        rows = {
            name: {"version": version, "checked": checked}
            for name, version in versions.items()
        }
        write_json(
            self.index,
            {
                **record,
                "no_requests": {**settled, phase: {**settled.get(phase, {}), **rows}},
            },
        )

    def no_requests(self):
        """Settled files by phase, until a resync gives them a new version."""
        record = self.record()
        versions = record.get("file_versions", {})
        return {
            phase: {
                name: row["checked"]
                for name, row in rows.items()
                if row["version"] == versions.get(name, "")
            }
            for phase, rows in record.get("no_requests", {}).items()
        }

    def sources(self, names, previous, fingerprint=None, *, fresh=False):
        fingerprint = fingerprint or (lambda path: digest(path.read_bytes()))
        paths = {
            name: (self.data / name).relative_to(self.source).as_posix()
            for name in names
        }
        native_paths = (
            {name: "Data/" + Path(name).stem + ".rvdata2" for name in names}
            if self.native_exports
            else {}
        )
        originals = self.bindings(
            self.source, [*paths.values(), *native_paths.values()]
        )
        result = {}
        for name, relative in paths.items():
            if (
                not fresh
                and name in previous
                and (
                    self.path("files", name).is_file()
                    or self.path("translated", name).is_file()
                )
            ):
                result[name] = previous[name]
                continue
            path = project_path(self.source, relative)
            if relative in originals:
                identity = {"original": originals[relative]}
            elif native_paths.get(name) in originals:
                identity = {
                    "native_original": {
                        "path": native_paths[name],
                        "blob": originals[native_paths[name]],
                    }
                }
            else:
                identity = {"sha256": fingerprint(path)}
                # Ace exports are runtime inputs too. Applying our exact saved
                # output must not look like a different untranslated source.
                output = self.path("translated", name)
                saved = previous.get(name)
                if (
                    saved
                    and output.is_file()
                    and fingerprint(output) == identity["sha256"]
                ):
                    identity = saved["identity"]
            result[name] = {"relative": relative, "identity": identity}
        return result

    def status(self, names, fingerprint=None):
        previous = self.record()["inputs"]
        current = self.sources(names, previous, fingerprint)
        return {
            "ready": [name for name in names if self.path("files", name).is_file()],
            "changed": [
                name
                for name in names
                if name in previous and previous[name] != current[name]
            ],
        }

    def prepare(
        self,
        names,
        *,
        refresh=False,
        expected=None,
        retired=(),
        progress=lambda _message: None,
    ):
        record = self.record()
        indexed = self.index.exists()
        previous = record["inputs"]
        current = self.sources(names, previous, fresh=refresh)
        if expected is not None and current != expected:
            raise ValueError(
                "The original source version changed. Review the file resync again."
            )
        changed = [
            name
            for name in names
            if name in previous and previous[name] != current[name]
        ]
        if changed and not refresh:
            raise ValueError(
                "Source changed for "
                + ", ".join(changed)
                + ". Review source changes and resync these working copies first."
            )
        replacements = {}
        for name in names:
            if refresh or not self.path("files", name).is_file():
                row = current[name]
                retained = self.path("translated", name)
                replacements[name] = (
                    retained.read_bytes()
                    if not refresh and retained.is_file()
                    else project_path(self.source, row["relative"]).read_bytes()
                )
                # A reload is an explicit choice of current game bytes, never a
                # silent restoration from the original-version backup.
                if not isinstance(decode_json(replacements[name]), (dict, list)):
                    raise ValueError("Working copies must contain valid game JSON.")
        if self.sources(names, previous, fresh=refresh) != current:
            raise ValueError(
                "The source changed while preparing working copies. Try again after reviewing the source."
            )

        old = {}
        for name in replacements:
            for group in ("files", "translated") if refresh else ("files",):
                path = self.path(group, name)
                old[(group, name)] = path.read_bytes() if path.is_file() else None
        archive = None
        cache = self.folder / "log/var_translation_map.json"
        cache_bytes = None
        if refresh:
            if (
                cache.is_symlink()
                or cache.parent.is_symlink()
                or (self.folder / "source-history").is_symlink()
            ):
                raise ValueError("The phase cache cannot be a symbolic link.")
            cache_bytes = cache.read_bytes() if cache.is_file() else None
            archive = self.folder / "source-history" / uuid.uuid4().hex
            write_json(archive / "source-inputs.json", record)
            for (group, name), raw in old.items():
                if raw is not None:
                    write_bytes(archive / group / name, raw)
            if cache_bytes is not None:
                write_bytes(archive / "log/var_translation_map.json", cache_bytes)
            progress(
                "Previous working copies and outputs archived before resyncing files."
            )
        try:
            if refresh:
                # Retire these file versions before replacing any bytes. If
                # the process is interrupted, late outputs cannot restore an
                # earlier pass over a partially reloaded selection.
                write_json(
                    self.index,
                    {
                        **record,
                        "inputs": {**previous, **current},
                        "last_refresh": archive.name,
                        "retired_runs": list(
                            dict.fromkeys([*record.get("retired_runs", []), *retired])
                        ),
                        "file_versions": {
                            **record.get("file_versions", {}),
                            **dict.fromkeys(names, archive.name),
                        },
                    },
                )
            for name, raw in replacements.items():
                progress("Preparing source copy: " + name)
                write_bytes(self.path("files", name), raw)
                if refresh:
                    self.path("translated", name).unlink(missing_ok=True)
            if refresh:
                cache.unlink(missing_ok=True)
            else:
                write_json(self.index, {**record, "inputs": {**previous, **current}})
        except Exception:
            for (group, name), raw in old.items():
                path = self.path(group, name)
                if raw is None:
                    path.unlink(missing_ok=True)
                else:
                    write_bytes(path, raw)
            if cache_bytes is not None:
                write_bytes(cache, cache_bytes)
            if refresh:
                if indexed:
                    write_json(self.index, record)
                else:
                    self.index.unlink(missing_ok=True)
            raise
        return {
            "files": len(replacements),
            "selection": names,
            "archive": str(archive) if archive else None,
        }
