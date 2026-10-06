"""Identify unused second-pass choice responses in older consumed MV/MZ runs."""

import json
from collections import Counter, defaultdict
from functools import lru_cache

from dazedtl.translation.files import project_path, read_json

from .process_view import _read_cached, _verified_digest, file_stamp


def choice_locations(data):
    entries = data.get("events") if isinstance(data, dict) else data
    if not isinstance(entries, list):
        raise ValueError("Choice evidence requires an MV/MZ event list.")
    result, identities = {}, set()
    for entry in entries:
        if entry is None:
            continue
        identity = entry.get("id")
        if type(identity) is not int or identity in identities:
            raise ValueError("Event identity is ambiguous.")
        identities.add(identity)
        pages = entry.get("pages", [entry])
        for page_index, page in enumerate(pages):
            ordinal = 0
            for command in page.get("list", []):
                if command.get("code") != 102:
                    continue
                values = command.get("parameters", [None])[0]
                if (
                    not isinstance(values, list)
                    or not values
                    or not all(isinstance(value, str) for value in values)
                ):
                    raise ValueError("Choice fields are unavailable.")
                original = command.get("_original")
                original = (
                    tuple(original)
                    if isinstance(original, list)
                    and all(isinstance(value, str) for value in original)
                    else None
                )
                result[(identity, page_index, ordinal)] = (tuple(values), original)
                ordinal += 1
    return result


@lru_cache(maxsize=8)
def choice_outputs(source, source_stamp, output, output_stamp):
    before, after = (
        choice_locations(read_json(source)),
        choice_locations(read_json(output)),
    )
    if (
        set(before) != set(after)
        or file_stamp(source) != source_stamp
        or file_stamp(output) != output_stamp
    ):
        raise ValueError("Choice locations changed.")
    result = defaultdict(list)
    for location, (text, _) in before.items():
        translated, original = after[location]
        result[text].append(translated if original == text else None)
    return dict(result)


def saved_choices(root, filename):
    plan_path, job_path = (
        project_path(root, "plan.json"),
        project_path(root, "job.json"),
    )
    plan = _read_cached(str(plan_path), file_stamp(plan_path))
    job = _read_cached(str(job_path), file_stamp(job_path))
    if (
        plan.get("engine") not in {"MVMZ", "RPG Maker MV/MZ"}
        or (plan.get("dazedtl_request_policy") or {}).get("choiceCollection")
        or job.get("plan_hash")
        != _verified_digest(str(plan_path), file_stamp(plan_path))
    ):
        return {}
    expected = next(
        (
            item.get("sha256")
            for item in plan.get("files", [])
            if item.get("name") == filename
        ),
        None,
    )
    source, output = (
        project_path(root, "files/" + filename),
        project_path(root, "translated/" + filename),
    )
    source_stamp, output_stamp = file_stamp(source), file_stamp(output)
    if (
        not expected
        or _verified_digest(str(source), source_stamp) != expected
        or _verified_digest(str(output), output_stamp)
        != job.get("outputs", {}).get(filename)
    ):
        return {}
    return choice_outputs(source, source_stamp, output, output_stamp)


def context(entry):
    value = entry.get("request_context")
    try:
        value = json.loads(value) if isinstance(value, str) else value
    except ValueError:
        return None
    if not isinstance(value, dict) or set(value) != {"instructions", "source_items"}:
        return None
    if not all(
        isinstance(value[key], list)
        and all(isinstance(item, str) for item in value[key])
        for key in value
    ):
        return None
    return value


def unused_responses(root, queued, responses, receipts, files, mapped):
    from .batch_validation import response_value

    indices = {key: index for index, key in enumerate(queued)}
    families = defaultdict(dict)
    for key, entry in queued.items():
        families[(entry.get("dazedtl_file"), entry.get("payload"))][key] = entry
    result, outputs = {}, {}
    for key, entry in queued.items():
        filename = entry.get("dazedtl_file")
        if (
            key in receipts
            or key not in mapped
            or filename not in files
            or key not in responses
            or not entry.get("dazedtl_sources")
        ):
            continue
        reference = context(entry)
        if not reference or reference["source_items"] or not reference["instructions"]:
            continue
        family = families[(filename, entry["payload"])]
        used = [other for other in family if other != key]
        # One extra context-free request, and every context-bearing sibling
        # independently passed validation under the same frozen source binding.
        if not used or any(
            other not in mapped
            or receipts.get(other, {}).get("state") != "validated"
            or row.get("dazedtl_sources") != entry["dazedtl_sources"]
            or not (other_context := context(row))
            or not other_context["source_items"]
            or other_context["instructions"] != reference["instructions"]
            for other, row in family.items()
            if other != key
        ):
            continue
        try:
            if filename not in outputs:
                outputs[filename] = saved_choices(root, filename)
            source = tuple(json.loads(entry["payload"]).values())
            actual = outputs[filename].get(source, [])
            # There must be exactly one first-pass request per physical menu;
            # every saved menu must match the accepted sibling response.
            expected = [
                tuple(
                    value[0].upper() + value[1:] if value else value
                    for value in response_value(responses[other]["text"]).values()
                )
                for other in used
            ]
            if (
                len(actual) != len(used)
                or any(value is None for value in actual)
                or Counter(actual) != Counter(expected)
            ):
                continue
            candidate = tuple(
                value[0].upper() + value[1:] if value else value
                for value in response_value(responses[key]["text"]).values()
            )
            if candidate in actual:
                continue  # The retained output cannot distinguish identical responses.
            result[key] = {
                "state": "unused",
                "unused": {"appliedRequests": [indices[other] for other in used]},
            }
        except OSError, ValueError, KeyError, TypeError, AttributeError, IndexError:
            continue
    return result
