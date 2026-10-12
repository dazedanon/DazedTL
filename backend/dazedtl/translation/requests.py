"""Engine-independent request and result contracts, without provider calls."""

import json
import math
import re
from collections import Counter

from .files import digest, unique_object

# API runs under this policy send a request's lines keyed "1" to "N" instead
# of their unit IDs, which can be long paths and would otherwise repeat in
# every list a request holds and in the reply. A run freezes the policy in
# its configuration, so earlier runs keep resuming with their own payloads.
LINE_KEYS = "line-keys-v1"
SCENES = "These lines come from separate scenes; keep each scene's speakers and context to its own lines:"
SPEAKERS = (
    "Speakers by line (context only: do not translate these labels, add them to dialogue, "
    "or include them in the output). Use them with the glossary for character voice and pronoun context, "
    "and preserve any speaker tags actually present in the source."
)
VOICE = (
    "A line without a listed speaker has no identified speaker, which is valid. "
    "Do not inherit a previous speaker or infer identity or gender from speech style. "
    "Narration and UI need not have a speaker. Resolve the subject and addressee separately from the speaker, "
    "using the surrounding Japanese in the same scene and event branch. Preserve source-supported ambiguity "
    "and voice without inventing a character identity."
)
QA_NOTES = "Source ambiguities for targeted review; these are uncertainties, not established facts:"


def scene_list(scenes):
    """The note naming which lines of a packed request belong to each scene,
    from (scene, unit IDs) in request order."""
    return (
        SCENES
        + "\n"
        + "\n".join(
            f"- {scene}: {len(ids)} {'line' if len(ids) == 1 else 'lines'}, {ids[0]} to {ids[-1]}"
            for scene, ids in scenes
        )
    )


def _scene_spans(note, ids):
    """A scene_list note as (scene, first, last) line positions, [] without
    one, or None when the note names lines some other way."""
    if not note:
        return []
    head, _, rest = note.partition("\n")
    if head != SCENES:
        return None
    spans, position = [], 0
    for line in rest.split("\n"):
        for count in range(1, len(ids) - position + 1):
            tail = f": {count} {'line' if count == 1 else 'lines'}, {ids[position]} to {ids[position + count - 1]}"
            if (
                line.startswith("- ")
                and line.endswith(tail)
                and len(line) > len(tail) + 2
            ):
                spans.append((line[2 : -len(tail)], position + 1, position + count))
                position += count
                break
        else:
            return None
    return spans if position == len(ids) else None


def provider_keys(request, configuration):
    """Unit ID -> the key a provider sees for its line: its position under
    LINE_KEYS, else the ID itself. A request whose scene note names lines
    another way, as a hand-written plan's may, keeps its IDs so the note
    still matches."""
    ids = list(request["sources"])
    context = request.get("context", {})
    if (
        configuration.get("lineKeys") != LINE_KEYS
        or "line_kinds" not in context
        or _scene_spans(context.get("scene_context", ""), ids) is None
    ):
        return {identity: identity for identity in ids}
    return {identity: str(position) for position, identity in enumerate(ids, 1)}


def provider_sources(request, configuration):
    keys = provider_keys(request, configuration)
    return {keys[identity]: text for identity, text in request["sources"].items()}


def _ranges(positions):
    spans = []
    for position in positions:
        if spans and spans[-1][1] == position - 1:
            spans[-1][1] = position
        else:
            spans.append([position, position])
    return ", ".join(
        str(first) if first == last else f"{first}-{last}" for first, last in spans
    )


def provider_view(request, configuration):
    """What a provider reads of a request: its user message, sources and
    constraints by key, the scene note and the reply instruction. Under
    LINE_KEYS, speakers and kinds are listed as line ranges, and lines
    without a speaker are left out instead of listed as null."""
    keys = provider_keys(request, configuration)
    context = request["context"]
    if all(key == identity for identity, key in keys.items()):
        return {
            "keys": keys,
            "user": context["user"],
            "sources": request["sources"],
            "constraints": request["constraints"],
            "scene_context": context.get("scene_context", ""),
            "reply": (
                "Return only a JSON object mapping each supplied source ID to its translated string. "
                "Do not add, remove, merge, or rename IDs. Speaker labels and surrounding source are context only."
            ),
        }

    def grouped(values):
        groups = {}
        for identity, value in values.items():
            if value is not None:
                groups.setdefault(value, []).append(int(keys[identity]))
        return groups

    sources = provider_sources(request, configuration)
    parts = []
    speakers = grouped(context["speakers"])
    if speakers:
        parts.append(
            SPEAKERS
            + "\n"
            + "\n".join(f"{name}: {_ranges(lines)}" for name, lines in speakers.items())
        )
    parts.append(
        "Line kinds (context only; do not include them in the output): "
        + "; ".join(
            f"{kind} {_ranges(lines)}"
            for kind, lines in grouped(context["line_kinds"]).items()
        )
        + "\n"
        + VOICE
    )
    if context.get("qa_notes"):
        parts.append(
            QA_NOTES
            + "\n"
            + json.dumps(
                {
                    keys[identity]: note
                    for identity, note in context["qa_notes"].items()
                },
                ensure_ascii=False,
            )
        )
    parts.append(
        "Translate only the following source text, keeping its keys, order and the required output schema:\n```json\n"
        + json.dumps(sources, ensure_ascii=False)
        + "\n```"
    )
    spans = _scene_spans(context.get("scene_context", ""), list(request["sources"]))
    return {
        "keys": keys,
        "user": "\n\n".join(parts),
        "sources": sources,
        "constraints": {
            keys[identity]: rule for identity, rule in request["constraints"].items()
        },
        "scene_context": SCENES
        + "\n"
        + "\n".join(
            f"- {scene}: {f'line {first}' if first == last else f'lines {first}-{last}'}"
            for scene, first, last in spans
        )
        if spans
        else "",
        "reply": (
            "Return only a JSON object mapping each line key to its translated string. "
            "Do not add, remove, merge, or rename keys. Speaker labels and surrounding source are context only."
        ),
    }


def from_provider(request, configuration, result):
    """A provider's reply with its line keys mapped back to unit IDs."""
    keys = provider_keys(request, configuration)
    if all(key == identity for identity, key in keys.items()):
        return result
    value = _parsed(result)
    identities = {key: identity for identity, key in keys.items()}
    if not isinstance(value, dict) or set(value) != set(identities):
        raise ValueError("Response keys do not match the requested lines.")
    return {identities[key]: text for key, text in value.items()}


def plan_input(value, *, allow_legacy=False):
    if not isinstance(value, dict):
        raise ValueError("A source plan must be a JSON object.")
    legacy = allow_legacy and "version" not in value
    fields = {"complete", "inputs", "batches"} | (set() if legacy else {"version"})
    if not legacy and (type(value.get("version")) is not int or value["version"] != 2):
        raise ValueError(
            "New source plans require version 2 with line kinds and explicit speakers. Use plan-format for an example."
        )
    if set(value) != fields or type(value["complete"]) is not bool:
        raise ValueError("A plan requires version, complete, inputs, and batches.")
    if (
        not isinstance(value["inputs"], list)
        or not value["inputs"]
        or not all(isinstance(path, str) for path in value["inputs"])
    ):
        raise ValueError("Bind the plan to its source and guidance files.")
    batches = value["batches"]
    if not isinstance(batches, list) or not batches:
        raise ValueError("The plan must contain at least one source batch.")
    identities = set()
    for batch in batches:
        allowed = {
            "id",
            "sources",
            "speakers",
            "source_context",
            "scene_context",
            "instruction_key",
            "constraints",
        }
        if not legacy:
            allowed |= {"kinds", "qa_notes"}
        if not isinstance(batch, dict) or set(batch) - allowed:
            raise ValueError(
                "Unknown batch fields. Keep injection metadata in the engine's source store."
            )
        name = batch.get("id")
        if (
            not isinstance(name, str)
            or not name.strip()
            or len(name) > 240
            or name in identities
        ):
            raise ValueError(
                "Every batch needs a unique, stable ID below 241 characters."
            )
        identities.add(name)
        sources = batch.get("sources")
        if (
            not isinstance(sources, dict)
            or not sources
            or any(
                not isinstance(key, str)
                or not key
                or len(key) > 240
                or not isinstance(text, str)
                or not text.strip()
                for key, text in sources.items()
            )
        ):
            raise ValueError("Each batch needs an ID-to-source-text object.")
        if "speakers" in batch and (
            not isinstance(batch["speakers"], dict)
            or set(batch["speakers"]) != set(sources)
            or any(
                speaker is not None
                and (not isinstance(speaker, str) or "\n" in speaker)
                for speaker in batch["speakers"].values()
            )
        ):
            raise ValueError(
                "Speaker metadata must match every source ID; use null when unknown."
            )
        if not legacy:
            kinds = batch.get("kinds")
            if (
                not isinstance(kinds, dict)
                or set(kinds) != set(sources)
                or any(
                    not isinstance(kind, str)
                    or kind not in {"dialogue", "narration", "ui", "unknown"}
                    for kind in kinds.values()
                )
            ):
                raise ValueError(
                    "Classify every source ID as dialogue, narration, ui, or unknown."
                )
            if "speakers" not in batch:
                raise ValueError(
                    "Record a speaker for every source ID; null is valid for unknown or inapplicable speakers."
                )
            for identity, speaker in batch["speakers"].items():
                if speaker is not None and (
                    not speaker.strip() or any(char in speaker for char in "\r\n\0")
                ):
                    raise ValueError(
                        "Speaker names must be nonempty single-line text; use null when unknown."
                    )
                if kinds[identity] == "ui" and speaker is not None:
                    raise ValueError(
                        "UI text has no speaker; use null and keep character names in the source text."
                    )
            notes = batch.get("qa_notes", {})
            if (
                not isinstance(notes, dict)
                or set(notes) - set(sources)
                or any(
                    not isinstance(note, str)
                    or not note.strip()
                    or len(note) > 2000
                    or "\0" in note
                    for note in notes.values()
                )
            ):
                raise ValueError(
                    "QA notes must describe a concrete source ambiguity, keyed by source ID, in 1–2000 characters."
                )
        for key in ("source_context", "scene_context", "instruction_key"):
            if key in batch and not isinstance(batch[key], str):
                raise ValueError("Batch context and instruction keys must be text.")
        constraints = batch.get("constraints", {})
        if not isinstance(constraints, dict) or set(constraints) - set(sources):
            raise ValueError("Constraints must refer to this batch's source IDs.")
        for key, rule in constraints.items():
            if not isinstance(rule, dict) or set(rule) - {
                "tokens",
                "max_lines",
                "max_characters",
            }:
                raise ValueError(
                    "Supported constraints are protected tokens, max_lines, and max_characters."
                )
            tokens = rule.get("tokens", [])
            if not isinstance(tokens, list) or not all(
                isinstance(token, str) and token and token in sources[key]
                for token in tokens
            ):
                raise ValueError("Declare only protected tokens present in the source.")
            for bound in ("max_lines", "max_characters"):
                if bound in rule and (type(rule[bound]) is not int or rule[bound] < 1):
                    raise ValueError("Layout bounds must be positive whole numbers.")
    return value


def output_schema(sources):
    return {
        "type": "object",
        "properties": {key: {"type": "string"} for key in sources},
        "required": list(sources),
        "additionalProperties": False,
    }


def _parsed(result):
    if isinstance(result, str):
        text = result.strip()
        if text.startswith("```json\n") and text.endswith("\n```"):
            text = text[8:-4]
        try:
            return json.loads(text, object_pairs_hook=unique_object)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                "The response is not a single translation JSON object."
            ) from exc
    return result


def result_value(request, result):
    result = _parsed(result)
    sources = request["sources"]
    if not isinstance(result, dict) or set(result) != set(sources):
        raise ValueError("Response IDs do not match the requested source IDs.")
    for identity, text in result.items():
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Every requested unit needs a nonempty translation.")
        rule = request.get("constraints", {}).get(identity, {})
        tokens = set(rule.get("tokens", []))
        # Common masks are always protected, even when an adapter omits its contract.
        tokens.update(re.findall(r"⟦[^⟧\r\n]+⟧|\{W\d+\}", sources[identity]))
        if any(text.count(token) != sources[identity].count(token) for token in tokens):
            raise ValueError("The response changed a protected token.")
        if Counter(re.findall(r"⟦[^⟧\r\n]+⟧|\{W\d+\}", text)) != Counter(
            re.findall(r"⟦[^⟧\r\n]+⟧|\{W\d+\}", sources[identity])
        ):
            raise ValueError("The response added or removed a protected mask.")
        if "max_lines" in rule and len(text.split("\n")) > rule["max_lines"]:
            raise ValueError("The response exceeds its declared line bound.")
        if "max_characters" in rule and len(text) > rule["max_characters"]:
            raise ValueError("The response exceeds its declared character bound.")
    return dict(result)


def logical_request(batch, context):
    if "kinds" in batch:
        context = dict(context)
        context.update(
            line_kinds=batch["kinds"],
            speakers=batch["speakers"],
            qa_notes=batch.get("qa_notes", {}),
        )
        context["user"] += (
            "\n\nLine classification (context only; do not include it in the output):\n"
            + json.dumps(batch["kinds"], ensure_ascii=False)
            + "\nUnknown speakers are valid. Do not inherit a previous speaker or infer identity or gender from speech style. "
            "Narration and UI need not have a speaker. Resolve the subject and addressee separately from the speaker, "
            "using the surrounding Japanese in the same scene and event branch. Preserve source-supported ambiguity "
            "and voice without inventing a character identity."
        )
        if context["qa_notes"]:
            context["user"] += (
                "\nSource ambiguities for targeted review; these are uncertainties, not established facts:\n"
                + json.dumps(context["qa_notes"], ensure_ascii=False)
            )
        context.pop("request_sha256", None)
        context["request_sha256"] = digest(context)
    value = {
        "id": batch["id"],
        "sources": batch["sources"],
        "context": context,
        "constraints": batch.get("constraints", {}),
    }
    semantic = {
        key: item
        for key, item in context.items()
        if key not in {"context_sha256", "request_sha256"}
    }
    if "reference_translations" in semantic:
        semantic["reference_translations"] = {
            "matches": semantic["reference_translations"].get("matches", {})
        }
    # Folder relocation and cache bookkeeping do not change what the model sees.
    value["fingerprint"] = digest({**value, "context": semantic})
    return value


def quote(requests, configuration, count_tokens):
    rates = configuration["rates"]
    if any(
        type(rates.get(key)) not in (int, float)
        or not math.isfinite(rates[key])
        or rates[key] < 0
        for key in ("input", "output")
    ):
        raise ValueError("Choose valid model pricing before estimating API work.")
    inputs = sum(
        count_tokens(json.dumps(item["params"], ensure_ascii=False))
        for item in requests
    )
    outputs = sum(
        max(
            1,
            math.ceil(
                count_tokens(json.dumps(item["sources"], ensure_ascii=False)) * 2.5
            ),
        )
        for item in requests
    )
    live = (inputs * rates["input"] + outputs * rates["output"]) / 1_000_000
    factor = rates["batch_factor"]
    batch = live * factor if factor is not None else None
    if configuration.get("openrouterBatch"):
        from dazedtl.settings.openrouter import validate_policy

        policy = validate_policy(
            configuration["openrouterBatch"], configuration["model"]
        )
        batch = (inputs * policy["input"] + outputs * policy["output"]) / 1_000_000
    return {
        "requests": len(requests),
        "units": sum(len(item["sources"]) for item in requests),
        "input_tokens": inputs,
        "output_tokens": outputs,
        "live_cost": live,
        "batch_cost": batch,
        "cost": batch
        if configuration["mode"] == "batch" and batch is not None
        else live,
        "model": configuration["model"],
        "provider": configuration["provider"],
        "rates": rates,
        "basis": "Complete compiled requests; 2.5× source-token output allowance, no assumed cache savings. Provider reasoning, retries, and images are additional.",
    }
