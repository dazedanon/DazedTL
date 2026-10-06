"""Record native Batch validation and reconcile older consumed response logs.

The native runner continues after a bad response. Its per-file mismatch flag
cannot identify which other requests were accepted. Per-response receipts
retain that distinction without revalidating, changing grouping or sending work.
"""

import json
import re
import threading
from collections import Counter
from contextlib import closing
from functools import lru_cache
from inspect import signature

from dazedtl.translation.files import digest

from .process_view import (
    batch_state,
    consumed_files,
    evidence_root,
    file_stamp,
    ledger,
    ledger_stamp,
    saved,
)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def response_value(text):
    """The native log formatter turns the provider's array schema into LineN."""
    value = json.loads(text)
    if isinstance(value, dict) and isinstance(value.get("translations"), list):
        return {
            f"Line{index + 1}": text for index, text in enumerate(value["translations"])
        }
    if isinstance(value, dict):
        numbers = sorted(int(key[4:]) for key in value if re.fullmatch(r"Line\d+", key))
        if numbers:
            return {
                f"Line{number}": value.get(f"Line{number}", "") for number in numbers
            }
    return value


def source_value(value):
    return (
        isinstance(value, dict)
        and bool(value)
        and all(
            re.fullmatch(r"Line\d+", key) and isinstance(text, str)
            for key, text in value.items()
        )
    )


LAYER = "batch-validation"


def install(evidence, translation):
    """Record native pass/fail per consumed response, independent of its wording."""
    with evidence.connect() as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS batch_validation "
            "(request_key TEXT PRIMARY KEY, filename TEXT, source TEXT, response_hash TEXT, state TEXT)"
        )
    local = threading.local()
    call_signature = signature(translation.translateAI)

    def received(native, payload, language, cache_context=None, request_context=None):
        response = native(payload, language, cache_context, request_context)
        if getattr(local, "call", None) is not None:
            key = translation.get_cache_key(
                payload, language, cache_context, request_context
            )
            # Native lookup alone decides whether a legacy context key is valid.
            if key not in translation._batch_results:
                key = translation.get_cache_key(payload, language, cache_context)
            if translation._batch_results.get(key) == response:
                local.call[key] = (payload, language, cache_context, request_context)
                with evidence.connect() as connection:
                    connection.execute(
                        "INSERT OR REPLACE INTO batch_validation VALUES (?,?,?,?,?)",
                        (
                            key,
                            local.filename,
                            canonical(json.loads(payload)),
                            digest(response),
                            "received",
                        ),
                    )
        return response

    def accepted(
        native, payload, output, language, cache_context=None, request_context=None
    ):
        result = native(payload, output, language, cache_context, request_context)
        matching = [
            key
            for key, args in (getattr(local, "call", None) or {}).items()
            if args == (payload, language, cache_context, request_context)
        ]
        if matching:
            with evidence.connect() as connection:
                connection.executemany(
                    "UPDATE batch_validation SET state='validated' WHERE request_key=?",
                    [(key,) for key in matching],
                )
        return result

    def validated(native, *args, **kwargs):
        previous = getattr(local, "call", None), getattr(local, "filename", None)
        local.call = {}
        local.filename = call_signature.bind(*args, **kwargs).arguments.get("filename")
        try:
            result = native(*args, **kwargs)
            # Only a returned native validation pass settles rejected responses.
            # Exceptions retain received state and the existing execution guard.
            if local.call:
                with evidence.connect() as connection:
                    connection.executemany(
                        "UPDATE batch_validation SET state='rejected' WHERE request_key=? AND state='received'",
                        [(key,) for key in local.call],
                    )
            return result
        finally:
            local.call, local.filename = previous

    translation.require_batch_result.layer(LAYER, received)
    translation.cache_translation.layer(LAYER, accepted)
    translation.translateAI.layer(LAYER, validated)


@lru_cache(maxsize=8)
def validation_receipts(root, stamp):
    connection = ledger(root)
    if connection is None:
        return []
    with closing(connection):
        if not connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='batch_validation'"
        ).fetchone():
            return []
        return connection.execute(
            "SELECT request_key,filename,source,response_hash,state FROM batch_validation"
        ).fetchall()


def recorded_outcomes(root, queued, responses):
    if not (root / "log/dazedtl-process.sqlite3").is_file():
        return {}
    result = {}
    for key, filename, source, response_hash, state in validation_receipts(
        str(root), ledger_stamp(root)
    ):
        entry = queued.get(key)
        if (
            not entry
            or state not in {"validated", "rejected"}
            or key not in responses
            or filename != entry.get("dazedtl_file")
            or source != canonical(json.loads(entry["payload"]))
            or response_hash != digest(responses[key])
        ):
            continue
        result[key] = {"state": state}
        if state == "rejected":
            result[key]["error"] = {
                "code": "validation_failed",
                "message": "This response failed translation validation. Original text was kept for this request.",
            }
    return result


@lru_cache(maxsize=8)
def expected_bodies(entries):
    result = {}
    for payload, raw in entries:
        try:
            value = response_value(raw)
            body, identity = (
                json.dumps(value, indent=4, ensure_ascii=False),
                canonical(value),
            )
        except ValueError, TypeError:
            body, identity = raw, raw
        result.setdefault(canonical(json.loads(payload)), set()).add((body, identity))
    return {
        source: sorted(values, key=lambda row: len(row[0]), reverse=True)
        for source, values in result.items()
    }


@lru_cache(maxsize=8)
def records(path, stamp, entries):
    with path.open(encoding="utf-8") as stream:
        text = stream.read(64_000_001)
    if len(text) > 64_000_000 or file_stamp(path) != stamp:
        return set(), set()
    decoder = json.JSONDecoder()
    expected = expected_bodies(entries)

    def recorded_body(source, start, ending):
        # Consume the complete retained body, including any text that happens
        # to resemble another log marker. Longest exact matches win.
        return next(
            (
                (identity, start + len(body) + len(ending))
                for body, identity in expected.get(canonical(source), [])
                if text.startswith(body + ending, start)
            ),
            None,
        )

    accepted, rejected = set(), set()
    if path.name == "translation.txt":
        marker = re.compile(
            r"^\[(BATCH|CACHE)\] Applied (?:provider batch result|cached translation \(no new API call\))\nInput:\n",
            re.MULTILINE,
        )
        offset = 0
        while match := marker.search(text, offset):
            try:
                source, end = decoder.raw_decode(text, match.end())
                if text[end : end + 9] != "\nOutput:\n":
                    break
                if match[1] == "BATCH":
                    found = recorded_body(source, end + 9, "\n")
                    if found is None:
                        break
                    response, offset = found
                else:
                    response, offset = decoder.raw_decode(text, end + 9)
                    if not source_value(response):
                        break
                    response = canonical(response)
                if source_value(source):
                    accepted.add((canonical(source), response))
            except ValueError:
                # Do not scan arbitrary malformed provider text for markers.
                break
    else:
        marker = re.compile(
            r"^Validation mismatch: ([^\n]+)\nOriginal text kept after \d+ attempts\.\nInput:\n",
            re.MULTILINE,
        )
        offset = 0
        while match := marker.search(text, offset):
            try:
                source, end = decoder.raw_decode(text, match.end())
                prefix = "\nProvider output:\n"
                if text[end : end + len(prefix)] != prefix:
                    break
                found = recorded_body(source, end + len(prefix), "\n\n")
                if found is None:
                    break
                response, offset = found
                if source_value(source):
                    rejected.add((match[1], canonical(source), response))
            except ValueError:
                break
    return accepted, rejected


def failure(source, response):
    message = "Translation validation rejected this response. Original text was kept for this request."
    try:
        translated = response_value(response.get("text", ""))
    except ValueError, TypeError:
        return {
            "code": "invalid_response",
            "message": "The response was not valid translation JSON. Original text was kept for this request.",
        }
    if not source_value(translated) or set(translated) != set(source):
        return {
            "code": "line_mismatch",
            "message": "The response did not contain the expected translation lines. Original text was kept for this request.",
        }
    placeholders = lambda values: Counter(
        re.findall(r"__PROTECTED_\d+__", "\n".join(values))
    )
    if placeholders(source.values()) != placeholders(translated.values()):
        message = "The response changed or omitted protected control-code placeholders. Original text was kept for this request."
    return {"code": "validation_mismatch", "message": message}


def outcomes(root, queued, responses):
    recorded = recorded_outcomes(root, queued, responses)
    files = consumed_files(root, allow_mismatches=True)
    if not files:
        return recorded
    manifests = {
        row["id"]: row.get("custom_ids") for row in batch_state(root).get("batches", [])
    }
    mapped, unbound = set(), set()
    for row in saved(evidence_root(root), "batch_history.json").get("batches", []):
        mapping = row.get("custom_ids") or {}
        (mapped if manifests.get(row.get("id")) == mapping else unbound).update(
            mapping.values()
        )
    accepted, rejected = set(), set()
    rows = tuple(
        (
            key,
            entry["payload"],
            entry.get("dazedtl_file"),
            tuple(entry.get("dazedtl_sources") or []),
            responses[key]["text"]
            if isinstance(responses.get(key), dict)
            and isinstance(responses[key].get("text"), str)
            else None,
        )
        for key, entry in queued.items()
    )
    entries = tuple((row[1], row[4]) for row in rows if row[4] is not None)
    for name in ("translation.txt", "mismatchHistory.txt"):
        path = root / "log" / name
        if not path.is_file() or path.is_symlink() or path.parent.is_symlink():
            continue
        stamp = file_stamp(path)
        if stamp[1] > 64_000_000:
            continue
        try:
            good, bad = records(path, stamp, entries)
            accepted.update(good)
            rejected.update(bad)
        except OSError, ValueError:
            continue
    bound = frozenset(mapped - unbound)
    result = dict(
        match_outcomes(rows, frozenset(accepted), frozenset(rejected), files, bound)
    )
    from .choice_history import unused_responses

    result.update(unused_responses(root, queued, responses, result, files, bound))
    result.update(recorded)
    return result


@lru_cache(maxsize=8)
def match_outcomes(rows, accepted, rejected, files, mapped):
    # Identical protected payloads can represent different files or source
    # identities. A text-only log cannot settle those ambiguous associations.
    bindings = {}
    for _, payload, filename, identities, _ in rows:
        source = canonical(json.loads(payload))
        binding = (filename, identities)
        bindings.setdefault(source, set()).add(binding)
    result = {}
    for key, payload, filename, identities, response in rows:
        if key not in mapped or filename not in files or response is None:
            continue
        source = json.loads(payload)
        if not source_value(source):
            continue
        identity = canonical(source)
        if len(bindings[identity]) != 1 or not identities:
            continue
        try:
            body = canonical(response_value(response))
        except ValueError, TypeError:
            body = response
        good, bad = (identity, body) in accepted, (filename, identity, body) in rejected
        if good == bad:
            continue  # Conflicting or missing validation is still unresolved.
        result[key] = (
            {"state": "validated"}
            if good
            else {"state": "rejected", "error": failure(source, {"text": response})}
        )
    return result
