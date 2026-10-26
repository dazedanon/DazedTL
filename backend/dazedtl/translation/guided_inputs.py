"""Manage phased working copies without replacing saved work on selection changes."""

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

from dazedtl import system
from dazedtl.storage import write_bytes, write_json

from .files import decode_json, digest, project_path, read_json
from .saved_refusals import restore

# Line counts per file version, by its path, digest, phase scope and original.
LINE_COUNTS: dict[tuple, dict] = {}
# The original game file's map display name, by its Git blob.
ORIGINAL_NAMES: dict[str, str | None] = {}
# Entries both keep beyond the files they hold now.
LINE_LIMIT = 50_000
_DISPLAY_NAME = re.compile(rb'"displayName"\s*:\s*("(?:[^"\\]|\\.)*")')


def display_name(raw, ace=False):
    """A map file's display name: a JSON map's, or a VX Ace map's own
    (rvdata2); None when it has none it can read."""
    try:
        if ace:
            from util.ace.ruby_marshal import load
            from util.ace.rv2json import text

            return text(load(raw).get("@display_name"))
        # The name comes before the events, so the map's tiles and events
        # need no parse.
        match = _DISPLAY_NAME.search(raw)
        events = raw.find(b'"events"')
        if match and (events < 0 or match.start() < events):
            return json.loads(match.group(1))
        return decode_json(raw).get("displayName")
    except AttributeError, TypeError, ValueError:
        return None  # A shape the reader does not know holds no name it reads.


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
        self,
        folder,
        source,
        data,
        bindings,
        original_bytes,
        *,
        original_blobs=None,
        native_exports=False,
        observations=None,
    ):
        self.folder, self.source, self.data = Path(folder), Path(source), Path(data)
        self.bindings, self.original_bytes = bindings, original_bytes
        # Many originals at once, through one Git process where it can.
        self.original_blobs = original_blobs or (
            lambda source, blobs: (
                (blob, original_bytes(source, blob)) for blob in blobs
            )
        )
        self.native_exports = native_exports
        self.index = self.folder / "source-inputs.json"
        self.observations = observations

    @property
    def observed(self):
        """A poll's shared look at these files; execution, outside any
        observation, reads them afresh."""
        return self.observations.files() if self.observations else None

    def once(self, key, read):
        return self.observations.once(key, read) if self.observations else read()

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

    def saved(self, group, name):
        """Whether a working copy exists; a poll answers from one listing of
        its folder, and anything else gets path()'s checks."""
        observed = self.observed
        if observed is not None and isinstance(name, str):
            entries = self.once(
                ("working copies", str(self.folder), group),
                lambda: (
                    None
                    if self.folder.is_symlink() or (self.folder / group).is_symlink()
                    else observed.listing(self.folder / group)
                ),
            )
            if (
                entries is not None
                and Path(name).name == name
                and name.endswith(".json")
            ):
                entry = entries.get(name)
                if entry is None:
                    return False
                if entry.is_file(follow_symlinks=False):
                    return True
        return self.path(group, name).is_file()

    def game_path(self, relative):
        if self.observed is not None:
            return self.observed.project_path(self.source, relative)
        return project_path(self.source, relative)

    def record(self):
        return self.once(("source inputs", str(self.index)), self._record)

    def _record(self):
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
        if self.observed is not None:
            fingerprint = self.observed.digest
        fingerprint = fingerprint or (lambda path: digest(path.read_bytes()))
        # The data folder's own path once, not each name's through pathlib.
        prefix = self.data.relative_to(self.source).as_posix() if names else ""
        paths = {
            name: (
                prefix + "/" + name
                if prefix != "."
                and name not in {"", "."}
                and os.path.basename(name) == name
                else (self.data / name).relative_to(self.source).as_posix()
            )
            for name in names
        }
        native_paths = (
            {name: "Data/" + Path(name).stem + ".rvdata2" for name in names}
            if self.native_exports
            else {}
        )
        # A poll's phases share each file's row and its original binding.
        rows = {} if fresh else self.once(("source rows", str(self.folder)), dict)
        originals = self.original_bindings([*paths.values(), *native_paths.values()])
        result = {}
        for name, relative in paths.items():
            if name in rows and rows[name][0] == previous.get(name):
                result[name] = rows[name][1]
                continue
            result[name] = self.source_row(
                name, relative, native_paths, originals, previous, fingerprint, fresh
            )
            if not fresh:
                rows[name] = (previous.get(name), result[name])
        return result

    def original_bindings(self, relatives):
        """Original blobs by path; a poll asks Git's cached listing once per path."""
        known = self.once(("original bindings", str(self.source)), dict)
        unknown = [relative for relative in relatives if relative not in known]
        if unknown:
            found = self.bindings(self.source, unknown)
            known.update({relative: found.get(relative) for relative in unknown})
        return {
            relative: known[relative]
            for relative in relatives
            if known.get(relative) is not None
        }

    def source_row(
        self, name, relative, native_paths, originals, previous, fingerprint, fresh
    ):
        bound = {}
        if relative in originals:
            bound["original"] = {"original": originals[relative]}
        native = native_paths.get(name)
        if native in originals:
            bound["native_original"] = {
                "native_original": {"path": native, "blob": originals[native]}
            }
        if (
            not fresh
            and name in previous
            and (self.saved("files", name) or self.saved("translated", name))
        ):
            # A working copy keeps its source while the game's own file
            # changes by Apply or by hand; only a new original of the kind it
            # was bound to, which a game update records, changes it.
            kept = previous[name]
            kind = next(iter(kept["identity"]), None)
            return {**kept, "identity": bound[kind]} if kind in bound else kept
        identity = bound.get("original") or bound.get("native_original")
        if identity is None:
            path = self.game_path(relative)
            identity = {"sha256": fingerprint(path)}
            # Ace exports are runtime inputs too. Applying our exact saved
            # output must not look like a different untranslated source.
            saved = previous.get(name)
            if (
                saved
                and self.saved("translated", name)
                and fingerprint(self.path("translated", name)) == identity["sha256"]
            ):
                identity = saved["identity"]
        return {"relative": relative, "identity": identity}

    def identities(self, names):
        """Each file's original identity: as its source pass recorded it,
        else as one would record it now, so a file no run has bound yet,
        such as in a game copied after translating, reads the same original."""
        recorded = self.record()["inputs"]
        unbound = [name for name in names if name not in recorded]
        current = self.sources(unbound, recorded) if unbound else {}
        return {
            name: (recorded.get(name) or current.get(name) or {}).get("identity", {})
            for name in names
        }

    def original_document(self, name):
        """The game file as the original version has it, when Git keeps one."""
        blob = self.identities([name])[name].get("original")
        if not blob:
            return None
        try:
            return decode_json(self.original_bytes(self.source, blob))
        except OSError, ValueError:
            return None

    def working_copy(self, name):
        """A file's newest saved working copy, translated or not."""
        group = next(
            (group for group in ("translated", "files") if self.saved(group, name)),
            None,
        )
        return None if group is None else self.path(group, name)

    def newest(self, name):
        """A file's newest copy: its translated working copy, else its working
        copy, else the game's own file."""
        return self.working_copy(name) or self.game_path(
            (self.data / name).relative_to(self.source).as_posix()
        )

    def line_counts(self, phases, markers):
        """Each file's line counts (file_lines.count) in its newest copy, by
        file to its phase ("database" or "dialogue"); choice help counts under
        *markers*. A file read once stays counted until its bytes change, and
        a file that cannot be read has none, all read in the game's source
        language."""
        from dazedtl.languages import read_source, reading

        language = read_source(self.source)
        with reading(language):
            return self._line_counts(phases, markers, language)

    def _line_counts(self, phases, markers, language):
        from util.source_text import holds_source

        from .file_lines import count

        identities = self.identities(list(phases))
        result, names, used = {}, {}, set()
        for name, phase in phases.items():
            try:
                path = self.newest(name)
                key = (
                    str(path),
                    self.observed.digest(path)
                    if self.observed is not None
                    else digest(path.read_bytes()),
                    phase,
                    markers if phase == "dialogue" else None,
                    identities[name].get("original"),
                    language,
                )
                if key not in LINE_COUNTS:
                    LINE_COUNTS[key] = count(
                        name,
                        decode_json(path.read_bytes()),
                        phase,
                        markers,
                        lambda name=name: self.original_document(name),
                    )
            except OSError, ValueError:
                continue
            except AttributeError, IndexError, KeyError, TypeError:
                # Data shaped unlike RPG Maker's, such as a comment whose
                # parameters are an object, has no lines to count.
                continue
            used.add(key)
            counts = dict(LINE_COUNTS[key])
            if "mapName" in counts:
                names[name] = counts.pop("mapName")
            result[name] = counts
        if len(LINE_COUNTS) > LINE_LIMIT:
            # Files change with every run; keep only their current versions.
            for key in set(LINE_COUNTS) - used:
                del LINE_COUNTS[key]
        # A translated map display name keeps no `_original`: it is a line
        # when the original game file's name holds Japanese.
        for name, original in self.original_names(names).items():
            if holds_source(original):
                result[name]["lines"] += 1
                result[name]["translated"] += 1
        return result

    def original_names(self, names):
        """The original game file's map display name for each named file,
        read once per original version; None where no original is known."""
        identities = self.identities(list(names))
        blobs = {}
        for name in names:
            identity = identities[name]
            native = identity.get("native_original") or {}
            blob = identity.get("original") or native.get("blob")
            if blob:
                blobs[name] = (blob, "native_original" in identity)
        unknown = [blob for blob, _ in blobs.values() if blob not in ORIGINAL_NAMES]
        if unknown:
            if len(ORIGINAL_NAMES) > LINE_LIMIT:
                ORIGINAL_NAMES.clear()
            native = {blob for blob, ace in blobs.values() if ace}
            try:
                for blob, raw in self.original_blobs(self.source, unknown):
                    ORIGINAL_NAMES[blob] = display_name(raw, blob in native)
            except OSError, ValueError:
                pass  # Without Git's originals, the names stay out of scope.
            for blob in unknown:
                ORIGINAL_NAMES.setdefault(blob, None)
        return {name: ORIGINAL_NAMES.get(blobs[name][0]) for name in blobs}

    def restore_refusals(self, names):
        """Gives the lines of these working copies that hold a refusal note an
        earlier run saved their source back, so the run translates them again.
        The run's saved outputs stay as they are."""
        restored = {}
        for name in names:
            path = self.path("files", name)
            try:
                document = decode_json(path.read_bytes())
            except OSError, ValueError:
                continue  # The engine reports a working copy it cannot read.
            count = restore(document, lambda name=name: self.original_document(name))
            if count:
                # As the engine writes game files.
                write_bytes(
                    path, json.dumps(document, ensure_ascii=False, indent=4).encode()
                )
                restored[name] = count
        return restored

    def status(self, names, fingerprint=None) -> dict[str, Any]:
        previous = self.record()["inputs"]
        current = self.sources(names, previous, fingerprint)
        return {
            "ready": [name for name in names if self.saved("files", name)],
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
            cache_bytes = system.read_bytes(cache) if cache.is_file() else None
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
                assert archive is not None  # Created above whenever refresh is set.
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
                    system.unlink(self.path("translated", name), missing_ok=True)
            if refresh:
                system.unlink(cache, missing_ok=True)
            else:
                write_json(self.index, {**record, "inputs": {**previous, **current}})
        except Exception:
            for (group, name), raw in old.items():
                path = self.path(group, name)
                if raw is None:
                    system.unlink(path, missing_ok=True)
                else:
                    write_bytes(path, raw)
            if cache_bytes is not None:
                write_bytes(cache, cache_bytes)
            if refresh:
                if indexed:
                    write_json(self.index, record)
                else:
                    system.unlink(self.index, missing_ok=True)
            raise
        return {
            "files": len(replacements),
            "selection": names,
            "archive": str(archive) if archive else None,
        }
