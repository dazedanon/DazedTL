"""Local payload and usage evidence; recording never calls a provider."""

import json
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from functools import partial
from inspect import signature
from pathlib import Path
from typing import cast

from dazedtl.translation.files import digest

from . import transmission
from .batch_evidence import joined
from .process_view import source_values
from .request_scope import columns, identities, source_locations

LAYER = "evidence"


def keep_aligned_partial_results(module):
    """Keep valid comment chunks instead of discarding the whole 408 group.

    The shared translator already substitutes original text for each rejected
    chunk. Preserve that aligned result; native mismatch logs and the file's
    MISMATCH list still report the rejected work. Name preflight remains atomic.
    """
    if (
        module is None
        or not hasattr(module, "THREAD_CTX")
        or not hasattr(module, "translateAI")
    ):
        return

    def translate(native, text, *args, **kwargs):
        result = native(text, *args, **kwargs)
        output = result[0] if isinstance(result, (list, tuple)) and result else None
        if (
            not getattr(module.THREAD_CTX, "in_speaker", False)
            and isinstance(text, list)
            and isinstance(output, list)
            and len(output) == len(text)
            and all(isinstance(value, str) for value in [*text, *output])
        ):
            module.THREAD_CTX.last_translation_had_mismatch = False
        return result

    module.translateAI.layer("partial-results", translate)


# Earlier lines quoted before each stretch of a shared request.
STRETCH_CONTEXT = 2
STRETCHES = (
    "These lines are separate stretches of one scene; the lines between them "
    "were translated earlier. Each stretch below lists the lines just before "
    "it, with their earlier English after →; continue the scene from them. "
    "Keep every line in the same format as its source line, including any "
    "name at its start. The stretches:"
)


def stretches(saved):
    """(start, end) of each run of lines without a reusable translation."""
    spans, start = [], None
    for index, value in enumerate([*saved, ""]):
        if value is None and start is None:
            start = index
        elif value is not None and start is not None:
            spans.append((start, index))
            start = None
    return spans


def shared_requests(spans, size):
    """Consecutive stretches grouped to fit one request each; a longer
    stretch keeps a group of its own."""
    groups, lines = [], 0
    for start, end in spans:
        if groups and lines + end - start <= size:
            groups[-1].append((start, end))
            lines += end - start
        else:
            groups.append([(start, end)])
            lines = end - start
    return groups


def stretch_notes(group, values, saved, source):
    """Each stretch's lines in the shared request and the lines before it:
    earlier translations with their source, or the call's own preceding
    source before its first line, one per line as the source context shows
    them."""

    def line(text):
        return " ".join(str(text).split())

    notes, position = [], 0
    for start, end in group:
        before = [
            line(values[index])
            + (f" → {line(saved[index])}" if saved[index] is not None else "")
            for index in range(max(0, start - STRETCH_CONTEXT), start)
        ] or [line(item) for item in source[-STRETCH_CONTEXT:] if isinstance(item, str)]
        first, last = position + 1, position + end - start
        span = f"line {first}" if first == last else f"lines {first}-{last}"
        notes.append(f"- {span}" + "".join(f"\n  {item}" for item in before))
        position += end - start
    return STRETCHES + "\n" + "\n".join(notes)


def kept(source, response):
    """Whether a line of a kept response kept its original text because it
    failed validation (translation keep_original_lines): it is no
    translation to reuse, so the next run sends it again."""
    from util.source_text import source_left

    return response == source and bool(source_left(response, source))


def accepted(translation, source, response, config):
    """Whether a saved translation of *source* still passes the response
    check, which reads Japanese left by the one source-text rule
    (util/source_text): a line it reads as left is sent again, never
    answered from what an earlier run saved."""
    pattern = getattr(config, "langRegex", None)
    if pattern is None or not isinstance(response, str):
        return True
    return not translation.validate_translation_content(
        [source], [response], pattern, getattr(config, "language", None)
    )[1]


def source_text(value, config):
    """Source-language text, which the shared translator sends; it cleans the rest."""
    pattern = getattr(config, "langRegex", None)
    return (
        isinstance(value, str)
        and bool(value.strip())
        and (pattern is None or re.search(pattern, value) is not None)
    )


class Evidence:
    def __init__(
        self,
        root,
        mode,
        plan=None,
        *,
        share_stretches=False,
        map_name_identities=False,
        source_aware=False,
    ):
        self.path = Path(root) / "log/dazedtl-process.sqlite3"
        self.mode = mode
        # Runs frozen before the reuse-stretches policy keep a request per
        # stretch, so their Batch requests rebuild identically.
        self.share_stretches = share_stretches
        # Runs frozen with the map-name-identities policy identify each line
        # of a call gathering several files' lines, the grouped map display
        # names, in its own files; older runs identify it in the calling file,
        # so their Batch reuses, and so requests, rebuild identically.
        self.map_name_identities = map_name_identities
        # Runs frozen with the source-text v2 policy reuse no saved line the
        # response check reads as left; older runs reuse every saved line, so
        # their Batch requests rebuild identically.
        self.source_aware = source_aware
        self.local = threading.local()
        # The translator's own thread state, once installed.
        self.translation_local = None
        self.plan = plan or {}
        self.reused = dict(self.plan.get("dazedtl_continuation", {}))
        self.root, self.locations = Path(root), {}
        self.translatable, self.translatable_lock = set(), threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS requests (id INTEGER PRIMARY KEY, params TEXT, state TEXT, usage TEXT, error TEXT)"
            )
            for name in (
                "sources",
                "filename",
                "response",
                "raw_response",
                "kept_lines",
            ):
                if name not in columns(connection):
                    connection.execute(
                        "ALTER TABLE requests ADD COLUMN " + name + " TEXT"
                    )
            for name in ("clarification_of", "retry_of"):
                if name not in columns(connection):
                    connection.execute(
                        "ALTER TABLE requests ADD COLUMN " + name + " INTEGER"
                    )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS validated_items (identity TEXT PRIMARY KEY, source TEXT, response TEXT)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS validated_provenance (identity TEXT PRIMARY KEY, filename TEXT)"
            )
            if mode == "estimate":
                # Reused responses need no request, so only this list proves
                # that a file without one has no text left to translate.
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS translatable_files (filename TEXT PRIMARY KEY)"
                )
            for key, source, response in connection.execute(
                "SELECT identity,source,response FROM validated_items"
            ):
                self.reused[key] = {"source": source, "response": json.loads(response)}
        from dazedtl.translation.refusals import text_refusal

        self.reused = {
            key: row
            for key, row in self.reused.items()
            if not text_refusal(row.get("response"), (row.get("source"),))
        }

    def unsent(self):
        """An estimate or Batch collection only builds requests it never sends."""
        return self.mode == "estimate" or (
            self.mode == "batch"
            and os.getenv("BATCH_PHASE", "").strip().lower() == "collect"
        )

    @contextmanager
    def session(self):
        """Shares one connection among an unsent pass's writes until it ends.

        Such a pass records thousands of requests in quick succession, and
        opening the database and waiting for the disk on each one took most
        of an estimate's time on Windows. A crash while nothing is sent costs
        only local work, so its commits skip the disk wait and keep their
        journal file.
        """
        if getattr(self.local, "connection", None) is not None or not self.unsent():
            yield
            return
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            connection.execute("PRAGMA synchronous=OFF")
            connection.execute("PRAGMA journal_mode=TRUNCATE")
            self.local.connection = connection
            yield
        finally:
            self.local.connection = None
            connection.close()

    @contextmanager
    def connect(self):
        shared = getattr(self.local, "connection", None)
        connection = shared or sqlite3.connect(self.path, timeout=10)
        try:
            with connection:
                yield connection
        finally:
            if shared is None:
                connection.close()

    def file_locations(self, filename):
        """Each string's paths in a file of the run, read once."""
        if filename not in self.locations:
            path = self.root / "files" / str(filename)
            try:
                self.locations[filename] = (
                    source_locations(json.loads(path.read_text(encoding="utf-8-sig")))
                    if path.is_file()
                    else {}
                )
            except OSError, ValueError:
                self.locations[filename] = {}
        return self.locations[filename]

    def found_text(self, filename):
        with self.translatable_lock:
            if filename in self.translatable:
                return
            with self.connect() as connection:
                connection.execute(
                    "INSERT OR IGNORE INTO translatable_files VALUES (?)", (filename,)
                )
            self.translatable.add(filename)

    def prepared(self, params, state="prepared", *, clarification_of=None):
        # A validation retry sends the same lines again, so it records the
        # first attempt; the request's lines then count once.
        identity = getattr(self.local, "request_identity", None)
        attempts = (
            self.local.validation_groups.get(identity, [])
            if identity is not None and getattr(self.local, "call", None) is not None
            else []
        )
        with self.connect() as connection:
            row = connection.execute(
                "INSERT INTO requests(params,state,sources,filename,clarification_of,retry_of) VALUES (?,?,?,?,?,?)",
                (
                    json.dumps(params, ensure_ascii=False),
                    state,
                    json.dumps(getattr(self.local, "sources", [])),
                    getattr(self.local, "filename", None),
                    clarification_of,
                    attempts[0] if attempts else None,
                ),
            )
            self.local.current = row.lastrowid
            if getattr(self.local, "call", None) is not None:
                self.local.call.append(row.lastrowid)
                self.local.validation_groups.setdefault(identity, []).append(
                    row.lastrowid
                )

    def record(self, params, *, clarification_of=None):
        # Durable intent precedes the SDK call; merely built estimate payloads
        # never acquire an uncertain/submitted state.
        values = source_values(params) or {}
        keys = getattr(self.local, "all_sources", [])
        files = getattr(self.local, "all_line_files", None)
        cursor = getattr(self.local, "cursor", 0)
        # The translator names the call's lines each request sends: a chunk
        # leaves out lines without source text. A request built outside its
        # chunks takes the call's next lines.
        lines = getattr(self.translation_local, "request_lines", None)
        if lines is not None and all(0 <= line < len(keys) for line in lines):
            self.local.sources = [keys[line] for line in lines]
            self.local.line_files = [files[line] for line in lines] if files else None
        else:
            self.local.sources = keys[cursor : cursor + len(values)] or keys
            self.local.line_files = None
        self.local.cursor = cursor + len(values)
        self.prepared(
            params,
            "submitted" if self.mode == "translate" else "prepared",
            clarification_of=clarification_of,
        )
        transmission.begin()

    def update(self, state, usage=None, error=None):
        current = getattr(self.local, "current", None)
        if current is not None:
            with self.connect() as connection:
                connection.execute(
                    "UPDATE requests SET state=?,usage=?,error=? WHERE id=?",
                    (
                        state,
                        json.dumps(usage) if usage is not None else None,
                        error,
                        current,
                    ),
                )

    def install(self, translation, module=None):
        """Records each request, response and validation outcome of this run."""
        self.translation_local = getattr(translation, "_thread_local", None)
        # Identical requests of several files, such as a scene two maps
        # repeat, are queued once; each file asking for one, first asker first.
        askers = {}

        def queued(native, *args, **kwargs):
            key = native(*args, **kwargs)
            with translation.BATCH_LOCK:
                entry = translation._batch_queue_pending.get(key)
                if entry is not None:
                    filename = getattr(self.local, "filename", None)
                    entry.update(
                        dazedtl_sources=getattr(self.local, "sources", []),
                        dazedtl_file=filename,
                    )
                    served = askers.setdefault(key, [])
                    if filename not in served:
                        served.append(filename)
                    # The response is used in every file that asked for it.
                    if len(served) > 1:
                        entry["dazedtl_files"] = list(served)
                    # A request gathering several files' lines, such as map
                    # display names, records the files of each line.
                    files = getattr(self.local, "line_files", None)
                    if files:
                        entry["dazedtl_line_files"] = files
                    else:
                        entry.pop("dazedtl_line_files", None)
            return key

        translation.queue_batch_request.layer(LAYER, queued)

        def join(native, kept, entry):
            # A fragment written before another file asked for the request
            # names fewer of the files it serves.
            kept = native(kept, entry)
            return joined(kept, entry) or kept

        translation._join_queued_request.layer(LAYER, join)

        def received(native, provider, params, usage):
            current = getattr(self.local, "current", None)
            with self.connect() as connection:
                row = connection.execute(
                    "SELECT params FROM requests WHERE id=?", (current,)
                ).fetchone()
            if row and json.loads(row[0]) != params:
                self.update(
                    "uncertain",
                    error=json.dumps(
                        {
                            "message": "The engine generated a different fallback payload; the earlier attempt remains retained."
                        }
                    ),
                )
                self.prepared(params)
            self.update(
                "received",
                {
                    key: getattr(usage, key, None)
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                },
            )
            return native(provider, params, usage)

        translation._write_request_debug_log.layer(LAYER, received)
        from .refusal_retry import receipt

        def captured(native, *args, **kwargs):
            response = native(*args, **kwargs)
            value = receipt(response)
            # Save every returned body before validation, including malformed
            # JSON and refusals. Accepted, restored values stay separate.
            with self.connect() as connection:
                connection.execute(
                    "UPDATE requests SET raw_response=? WHERE id=?",
                    (
                        json.dumps(
                            {
                                "text": value["content"],
                                "refusal": value["refusal"],
                                "finish_reason": value["finish_reason"],
                            },
                            ensure_ascii=False,
                        ),
                        self.local.current,
                    ),
                )
            return response

        from dazedtl.translation.refusals import POLICY as REFUSAL_POLICY

        retry = None
        if self.mode == "translate":
            from .refusal_retry import RefusalRetry

            retry = RefusalRetry(
                self,
                signature(translation.translateText),
                translation=translation,
                allow_clarification=(self.plan.get("dazedtl_request_policy") or {}).get(
                    "refusalRetry"
                )
                == REFUSAL_POLICY,
            )

        if self.mode == "translate":
            transmission.install()

        def call(native, *args, **kwargs):
            self.local.current = None
            transmission.end()
            attempt = partial(captured, native)
            try:
                if retry is not None:
                    return retry(attempt, *args, **kwargs)
                return attempt(*args, **kwargs)
            except Exception as error:
                from .provider_responses import error_evidence

                secret = (
                    getattr(getattr(translation, "openai", None), "api_key", "") or ""
                )
                detail = error_evidence(error, secret)
                # Observed tries decide whether anything reached the provider.
                # Without them only an outright refusal of the final error does;
                # recovered inner errors are display evidence, not authority.
                tries = transmission.observed()
                never_sent = (
                    transmission.never_sent(tries)
                    if tries
                    else getattr(error, "status_code", None) in transmission.REFUSED
                )
                self.update(
                    "failed" if never_sent else "uncertain", error=json.dumps(detail)
                )
                raise
            finally:
                transmission.end()

        translation.translateText.layer(LAYER, call)
        # Translate runs validate through the native cache writer; others settle
        # requests when translateAI returns.
        validates_cache = (
            self.mode == "translate"
            and getattr(translation, "cache_translation", None) is not None
        )
        if validates_cache:

            def cached(native, payload, output, *args, **kwargs):
                result = native(payload, output, *args, **kwargs)
                current = getattr(self.local, "current", None)
                if (
                    current is not None
                    and getattr(self.local, "call", None) is not None
                ):
                    with self.connect() as connection:
                        row = connection.execute(
                            "SELECT params,state FROM requests WHERE id=?", (current,)
                        ).fetchone()
                        if (
                            row
                            and row[1] == "received"
                            and source_values(json.loads(row[0]))
                            == source_values({"messages": [{"content": payload}]})
                        ):
                            connection.execute(
                                "UPDATE requests SET state='validated',response=? WHERE id=?",
                                (
                                    json.dumps(
                                        output
                                        if isinstance(output, list)
                                        else [output],
                                        ensure_ascii=False,
                                    ),
                                    current,
                                ),
                            )
                            previous = self.local.validation_groups.get(
                                getattr(self.local, "request_identity", None), []
                            )
                            connection.executemany(
                                "UPDATE requests SET state='rejected',error=? WHERE id=? AND state IN ('received','rejected')",
                                [
                                    (
                                        json.dumps(
                                            {
                                                "code": "replaced_response",
                                                "message": "A later validated response was used for this request.",
                                            }
                                        ),
                                        identity,
                                    )
                                    for identity in previous
                                    if identity != current
                                ],
                            )
                return result

            translation.cache_translation.layer(LAYER, cached)

            def kept_lines(
                native,
                payload,
                language,
                cache_context=None,
                request_context=None,
                lines=None,
            ):
                native(payload, language, cache_context, request_context, lines)
                current = getattr(self.local, "current", None)
                if current is not None and lines:
                    with self.connect() as connection:
                        connection.execute(
                            "UPDATE requests SET kept_lines=? WHERE id=? AND state='validated'",
                            (json.dumps(lines), current),
                        )

            if getattr(translation, "keep_original_lines", None) is not None:
                translation.keep_original_lines.layer(LAYER, kept_lines)
        call_signature = signature(translation.translateAI)

        def validated(native, *args, **kwargs):
            with self.session():
                return checked(native, *args, **kwargs)

        def remaining(native, bound, saved):
            """Translates a call's lines that have no reusable translation.

            Under the reuse-stretches policy, stretches between reused lines
            share requests up to the request size, each labelled with the lines
            before it; otherwise, and for a call with one stretch, each
            stretch is sent with its preceding source. Each request's mismatch keeps its own
            lines' native fallback, and every attempt's usage counts.
            """
            values = bound.arguments["text"]
            config = bound.arguments.get("config")
            size = getattr(config, "batchSize", None)
            output, tokens, mismatched = list(saved), [0, 0], False
            for group in shared_requests(
                stretches(saved),
                size if self.share_stretches and type(size) is int and size > 0 else 1,
            ):
                part = call_signature.bind(*bound.args, **bound.kwargs)
                lines = [index for start, end in group for index in range(start, end)]
                part.arguments["text"] = [values[index] for index in lines]
                if part.arguments.get("line_files"):
                    part.arguments["line_files"] = [
                        part.arguments["line_files"][index] for index in lines
                    ]
                history = part.arguments.get("history")
                start = group[0][0]
                if len(group) > 1:
                    source, instructions = translation._request_context_parts(
                        history,
                        part.arguments.get("context_kind"),
                        part.arguments.get("request_instructions"),
                    )
                    part.arguments["history"] = {
                        "instructions": [
                            *instructions,
                            stretch_notes(group, values, saved, source),
                        ],
                        "source_items": [],
                    }
                    if "request_instructions" in part.arguments:
                        part.arguments["request_instructions"] = None
                elif start and isinstance(history, list):
                    limit = getattr(config, "maxHistory", 10)
                    part.arguments["history"] = (history + values[:start])[-limit:]
                translated, used = validated(native, *part.args, **part.kwargs)
                mismatched |= translation.last_translation_had_mismatch()
                if len(translated) != len(lines):
                    mismatched = True
                    translated = [values[index] for index in lines]
                for index, value in zip(lines, translated):
                    output[index] = value
                tokens = [a + b for a, b in zip(tokens, used)]
            translation._thread_local.last_translation_had_mismatch = mismatched
            return [output, tokens]

        def checked(native, *args, **kwargs):
            bound = call_signature.bind(*args, **kwargs)
            text = bound.arguments.get("text")
            filename = bound.arguments.get("filename")
            values = text if isinstance(text, list) else [text]
            line_files = bound.arguments.get("line_files")
            if line_files is None or len(line_files) != len(values):
                line_files = None
            self.local.all_line_files = line_files
            if self.mode == "estimate":
                config = bound.arguments.get("config")
                if line_files is None:
                    if any(source_text(value, config) for value in values):
                        self.found_text(filename)
                else:
                    for names, value in zip(line_files, values):
                        if source_text(value, config):
                            for name in names:
                                self.found_text(name)
            if not all(isinstance(value, str) for value in values):
                # Lines that are not text have no identities; the previous
                # call's must not stand in for them.
                self.local.all_sources, self.local.sources = [], []
                self.local.filename, self.local.cursor = filename, 0
                return native(*args, **kwargs)
            phase = (self.plan.get("workflow") or {}).get("phase")
            history = bound.arguments.get("history")

            def identified(name, lines):
                """The lines' identities in file `name` and their reuse keys. A
                duplicated source string has ambiguous field provenance. Retain
                separate response context instead of silently substituting one
                field's translation into a different context."""
                locations = self.file_locations(name)
                keys = identities(name, phase, lines, locations)
                return keys, [
                    key
                    if len(locations.get(value, [])) <= 1
                    else digest([key, history])
                    for key, value in zip(keys, lines)
                ]

            keys, reuse_keys = identified(filename, values)
            # Each line's reuse keys with the files they belong to.
            owners = [[(key, filename)] for key in reuse_keys]
            lookups = owners
            if self.map_name_identities and line_files is not None:
                # Each grouped line is identified in every file it belongs to,
                # as a call of that file alone identifies it; a name an older
                # run saved under the calling file stays reusable.
                keys, owners = [], []
                for value, names in zip(values, line_files):
                    line_keys, line_owners = [], []
                    for name in names or [filename]:
                        (key,), (reuse,) = identified(name, [value])
                        line_keys.append(key)
                        line_owners.append((reuse, name))
                    keys.append(line_keys[0])
                    owners.append(line_owners)
                lookups = [[*owner, *older] for owner, older in zip(owners, lookups)]
            (
                self.local.all_sources,
                self.local.sources,
                self.local.filename,
                self.local.cursor,
            ) = keys, keys, filename, 0
            config = bound.arguments.get("config")
            reused = [
                next(
                    (
                        row
                        for row in (self.reused.get(key) for key, _ in lookup)
                        if row is not None
                        and row.get("source") == value
                        and (
                            not self.source_aware
                            or accepted(translation, value, row["response"], config)
                        )
                    ),
                    None,
                )
                for lookup, value in zip(lookups, values)
            ]
            if translation.get_batch_phase() in {"collect", "estimate"}:
                # A scan summary counts the lines saved translations answer.
                record_stats = getattr(translation, "_record_batch_collect_stats", None)
                if record_stats is not None:
                    record_stats(reused_items=sum(row is not None for row in reused))
            if values and all(row is not None for row in reused):
                translation._thread_local.last_translation_had_mismatch = False
                # Every reused row was checked above.
                output = [cast(dict, row)["response"] for row in reused]
                return [output if isinstance(text, list) else output[0], [0, 0]]
            saved = [row["response"] if row is not None else None for row in reused]
            if isinstance(text, list) and any(value is not None for value in saved):
                return remaining(native, call_signature.bind(*args, **kwargs), saved)
            previous = getattr(self.local, "call", None)
            self.local.call = []
            self.local.request_cursors = {}
            self.local.validation_groups = {}
            try:
                result = native(*args, **kwargs)
                if not translation.last_translation_had_mismatch():
                    with self.connect() as connection:
                        if not validates_cache:
                            connection.executemany(
                                "UPDATE requests SET state='validated' WHERE id=? AND state='received'",
                                [(identity,) for identity in self.local.call],
                            )
                        output = (
                            result[0] if isinstance(result[0], list) else [result[0]]
                        )
                        if len(output) == len(values) and (
                            self.mode == "translate"
                            or translation.get_batch_phase() == "consume"
                        ):
                            connection.executemany(
                                "INSERT OR REPLACE INTO validated_items VALUES (?,?,?)",
                                [
                                    (
                                        key,
                                        source,
                                        json.dumps(response, ensure_ascii=False),
                                    )
                                    for owner, source, response in zip(
                                        owners, values, output
                                    )
                                    if not kept(source, response)
                                    for key, _ in owner
                                ],
                            )
                            connection.executemany(
                                "INSERT OR REPLACE INTO validated_provenance VALUES (?,?)",
                                [
                                    (key, name)
                                    for owner, source, response in zip(
                                        owners, values, output
                                    )
                                    if not kept(source, response)
                                    for key, name in owner
                                ],
                            )
                            if not validates_cache:
                                connection.executemany(
                                    "UPDATE requests SET response=? WHERE id=? AND state='validated'",
                                    [
                                        (
                                            json.dumps(output, ensure_ascii=False),
                                            identity,
                                        )
                                        for identity in self.local.call
                                    ],
                                )
                if validates_cache:
                    # Native validation has returned. Bodies not accepted by its
                    # cache writer are rejected attempts, including earlier retries.
                    # Exceptions skip this step and retain their recovery guard.
                    with self.connect() as connection:
                        connection.executemany(
                            "UPDATE requests SET state='rejected',error=? WHERE id=? AND state='received'",
                            [
                                (
                                    json.dumps(
                                        {
                                            "message": "The response failed translation validation. Original text or a later validated response was used."
                                        }
                                    ),
                                    identity,
                                )
                                for identity in self.local.call
                            ],
                        )
                return result
            finally:
                self.local.call = previous

        translation.translateAI.layer(LAYER, validated)
        if self.mode == "batch":
            from .batch_validation import install

            install(self, translation)
        keep_aligned_partial_results(module)
