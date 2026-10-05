"""Coalesce compatible state calls while retaining the native field writer."""

import json
import re
import threading
from copy import deepcopy
from pathlib import Path

from dazedtl.storage import write_json
from dazedtl.translation.files import digest, read_json

POLICY = "compatible-states-v1"


def groups(calls, limit, context):
    result = []
    for index, call in enumerate(calls):
        key = context(call)
        chosen = None
        if key is not None:
            for group in result:
                merged = [
                    text for member in group for text in calls[member]["text"]
                ] + call["text"]
                if len(merged) <= limit and context(
                    {**call, "text": merged}
                ) == key == context(calls[group[0]]):
                    chosen = group
                    break
        if chosen is None:
            chosen = []
            result.append(chosen)
        chosen.append(index)
    return result


def remaining_calls(current, frozen):
    result = []
    for call in current:
        matches = [
            (index, original)
            for index, original in enumerate(frozen)
            if (original["stateIndex"], original["kind"])
            == (call["stateIndex"], call["kind"])
        ]
        if len(matches) != 1:
            raise ValueError(
                "Saved state grouping no longer matches the frozen source. Prepare a new run."
            )
        index, original = matches[0]
        if call["kind"] == "basic" and all(
            field in original["fields"] for field in call["fields"]
        ):
            offsets = [original["fields"].index(field) for field in call["fields"]]
        else:
            offsets = list(range(len(original["text"])))
        if (
            call["stateId"] != original["stateId"]
            or call["text"] != [original["text"][offset] for offset in offsets]
            or call["history"] != original["history"]
            or call["extra"] != original["extra"]
        ):
            raise ValueError(
                "Saved state grouping no longer matches the frozen source. Prepare a new run."
            )
        result.append((index, offsets))
    return result


def configure(module, translation, root, limit):
    if getattr(module.parseSS, "_dazedtl_state_groups", False):
        return
    native_parse, native_translate = module.parseSS, module.translateAI
    local = threading.local()

    def context(call):
        if call["kind"] != "basic" or not isinstance(call["history"], str):
            return None
        text = call["text"]
        if any(
            not isinstance(value, str)
            or "\ufffd" in value
            or not re.search(module.TRANSLATION_CONFIG.langRegex, value)
            or re.search(r"\\[nNvV]\[", value)
            for value in text
        ):
            return None
        protected = [
            translation.protect_script_codes(
                re.sub(r"(.)\1{9,}", lambda match: match[1] * 10, value)
            )[0]
            for value in text
        ]
        payload = json.dumps(
            {f"Line{i + 1}": value for i, value in enumerate(protected)},
            indent=4,
            ensure_ascii=False,
        )
        system, glossary, sfx, _ = translation.createContextParts(
            module.TRANSLATION_CONFIG, payload, "json", []
        )
        return system, glossary, sfx, call["history"], call["extra"]

    def dispatch(text, history, *extra):
        state = getattr(local, "state", None)
        if state is None:
            return native_translate(text, history, *extra)
        if state["capture"]:
            state["calls"].append(
                {
                    "text": deepcopy(text),
                    "history": history,
                    "extra": list(extra),
                    "stateId": state["stateId"],
                    "fields": state["fields"] if not state["seen"] else [],
                    "stateIndex": state["stateIndex"],
                    "kind": "basic"
                    if state["fields"] and not state["seen"]
                    else "notes",
                }
            )
            state["seen"] = True
            return [deepcopy(text), [0, 0]]
        index = state["index"]
        expected = state["calls"][index]
        if (text, history, list(extra)) != (
            expected["text"],
            expected["history"],
            expected["extra"],
        ):
            raise ValueError(
                "The state request mapping changed. No fallback request was sent."
            )
        state["index"] += 1
        member, offsets = state["remaining"][index]
        group = next(group for group in state["groups"] if member in group)
        first = group[0]
        if first not in state["results"]:
            sources = [
                value for member in group for value in state["frozen"][member]["text"]
            ]
            history = state["frozen"][first]["history"]
            extra = state["frozen"][first]["extra"]
            if len(group) > 1:
                associations = [
                    {"stateId": state["frozen"][member]["stateId"], "field": field}
                    for member in group
                    for field in state["frozen"][member]["fields"]
                ]
                if len(associations) != len(sources):
                    raise ValueError(
                        "Grouped state fields no longer match their source IDs."
                    )
                mapping = {
                    f"Line{i + 1}": value for i, value in enumerate(associations)
                }
                history += (
                    "\n\nState field associations (context only; translate only the supplied source strings):\n"
                    + json.dumps(mapping, ensure_ascii=False)
                )
            response, tokens = native_translate(sources, history, *extra)
            if not isinstance(response, list) or len(response) != len(sources):
                raise ValueError(
                    "Grouped state response IDs do not match the saved source mapping."
                )
            offset = 0
            for member in group:
                size = len(state["frozen"][member]["text"])
                state["results"][member] = response[offset : offset + size]
                offset += size
            state["tokens"][index] = tokens
        member, offsets = state["remaining"][index]
        return [
            [deepcopy(state["results"][member][offset]) for offset in offsets],
            state["tokens"].get(index, [0, 0]),
        ]

    def parse(data, filename):
        state = {"capture": True, "calls": [], "results": {}, "tokens": {}, "index": 0}
        local.state = state
        try:
            for state_index, item in enumerate(data):
                if item is not None:
                    fields = [
                        key
                        for key in (
                            "name",
                            "description",
                            "message1",
                            "message2",
                            "message3",
                            "message4",
                        )
                        if item.get(key)
                        and module._entry_field_needs_translation(item, key)
                    ]
                    state.update(
                        stateId=item.get("id"),
                        stateIndex=state_index,
                        seen=False,
                        fields=fields,
                    )
                    module.searchSS(deepcopy(item), None)
            calls = state["calls"]
            if any(not isinstance(call["text"], list) for call in calls):
                local.state = None
                return native_parse(data, filename)
            path = (
                Path(root)
                / "log"
                / ("dazedtl-state-groups-" + digest(filename)[:16] + ".json")
            )
            identity = digest({"calls": calls, "limit": limit, "policy": POLICY})
            if path.exists():
                saved = read_json(path)
                if saved.get("policy") != POLICY:
                    raise ValueError("Saved state grouping policy is unsupported.")
                frozen = saved["calls"]
                if saved.get("identity") != digest(
                    {"calls": frozen, "limit": limit, "policy": POLICY}
                ):
                    raise ValueError(
                        "Saved state grouping no longer matches its frozen request limit or source."
                    )
                remaining = remaining_calls(calls, frozen)
                chosen = saved["groups"]
            else:
                frozen = calls
                remaining = [
                    (index, list(range(len(call["text"]))))
                    for index, call in enumerate(calls)
                ]
                chosen = groups(calls, limit, context)
                write_json(
                    path,
                    {
                        "policy": POLICY,
                        "identity": identity,
                        "calls": calls,
                        "groups": chosen,
                    },
                )
            if (
                not isinstance(chosen, list)
                or any(
                    not isinstance(group, list)
                    or not group
                    or any(type(member) is not int for member in group)
                    or group != sorted(group)
                    for group in chosen
                )
                or sorted(member for group in chosen for member in group)
                != list(range(len(frozen)))
            ):
                raise ValueError(
                    "Saved state grouping is invalid. No fallback request was sent."
                )
            state.update(
                capture=False, groups=chosen, frozen=frozen, remaining=remaining
            )
            return native_parse(data, filename)
        finally:
            local.state = None

    parse._dazedtl_state_groups = True
    parse._dazedtl_native = native_parse
    dispatch._dazedtl_native = native_translate
    module.translateAI, module.parseSS = dispatch, parse


def restore(module):
    if getattr(module.parseSS, "_dazedtl_state_groups", False):
        module.parseSS = module.parseSS._dazedtl_native
        module.translateAI = module.translateAI._dazedtl_native
