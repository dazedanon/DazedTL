"""Measured translation-quality comparisons on a frozen regression set
(util/quality_set).

A *variant* names how lines are translated: the method (Guided or
Assistant-led), a prompt file, the model, provider and effort, and context
switches. A *run* translates every item of a set, and of any targeted item
files, through that method's production request builders, whole chunks at a
time, and keeps each reply under its request's digest, so translating again
under the same run ID sends only what has no reply yet: a crash, a retry or
a set grown by a targeted file never pays twice. Runs never read a game, the
translation cache or the app's records.

A *comparison* scores runs on the items' target lines, cheapest first: the
mechanical gate (evaluation.translation_issues) as its own validity rate; a
glossary defect by an exact check of the glossary rows its correction
follows; another defect by a blind judge asking whether the line repeats the
defect the reviewer described; a control by a blind pairwise judgment
against the accepted line. Every comparison calibrates its judge on the
defects' first drafts and corrections, and withholds the judge's scores when
it cannot tell them apart well enough (CALIBRATION_MINIMUM). The baseline is
translated twice: a variant's change counts only beyond the gap between its
two runs, the noise floor, and each change is reported with an interval.

Paid requests need an approved cap: requests go in slices whose most
possible cost fits what the cap has left, so a run never spends past it.
"""

from __future__ import annotations

import copy
import hashlib
import json
import random
import re
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from util import batch_providers as batch_api
from util import evaluation, quality_set, system
from util.evaluation_settings import DEFAULT_MAX_OUTPUT_TOKENS, reasoning_profile
from util.paths import SKILLS_DIR, runtime_data_file

RUN_SCHEMA = "dazedtl-quality-run"
COMPARISON_SCHEMA = "dazedtl-quality-comparison"
# Raise when what a saved run or comparison holds, or how its keys are made,
# changes, so older saved work is refused instead of misread.
RUN_VERSION = 1
COMPARISON_VERSION = 1
PROVIDERS = ("anthropic", "openai", "gemini")
CONTEXT_SWITCHES = ("history", "glossary", "sfx", "speakers")
JUDGE_PROMPTS = {
    "defect": SKILLS_DIR / "quality_judge_defect.md",
    "pairwise": SKILLS_DIR / "quality_judge_pairwise.md",
}
# What a judgment's reply is expected to count, for estimates.
JUDGE_REPLY_TOKENS = 150
# The least a judge must separate known-bad from known-good lines before its
# scores are reported: Youden's J, the share of flawed lines it flags minus
# the share of fixed lines it flags, for the defect question and for the
# pairwise one. A measured change in a rate is the true change times J, so
# 0.70 keeps at least 70% of every effect. Equal sensitivity and specificity
# of 0.85 reach it. The calibration takes QA's findings as true and, for the
# defect question, is circular, so a judge's J is an upper bound
# (docs/development.md#comparing-a-change says what was checked and why).
CALIBRATION_MINIMUM = 0.70
BOOTSTRAP_SAMPLES = 2000
METRICS = {
    # name: (higher is better, what it counts)
    "validity": (True, "target lines that passed the mechanical gate (not a quality measure)"),
    "glossary": (True, "glossary defects whose correction's terms the line keeps"),
    "repeats": (False, "judged defects the line repeats"),
    "defects": (False, "defects the line repeats, by glossary check or judge"),
    "regressions": (False, "controls judged worse than the accepted line"),
}
JUDGED_METRICS = ("repeats", "defects", "regressions")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def _write_json(path: Path, value: Any) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    system.write_text(path, json.dumps(value, ensure_ascii=False, indent=1))


# Variants and judges


def _connection(value: dict, label: str) -> dict:
    provider = str(value.get("provider") or "").lower()
    if provider not in PROVIDERS:
        raise ValueError(f"{label}: provider must be one of {', '.join(PROVIDERS)}")
    model = str(value.get("model") or "").strip()
    if not model:
        raise ValueError(f"{label}: name the model")
    endpoint = str(value.get("endpoint") or "").strip()
    execution = str(value.get("execution") or "batch").lower()
    if execution not in ("batch", "live"):
        raise ValueError(f"{label}: execution is batch or live")
    effort = value.get("effort")
    if effort is not None:
        levels, _default = reasoning_profile({"provider": provider, "model": model})
        if effort not in levels:
            raise ValueError(
                f"{label}: {model} takes effort "
                + (", ".join(levels) if levels else "only from the provider (leave it out)")
            )
    return {
        "provider": provider,
        "model": model,
        "endpoint": endpoint,
        "execution": execution,
        # None sends no effort, as translation runs do: the provider's default.
        "effort": effort,
        "keyless": bool(value.get("keyless", evaluation.is_local_endpoint(endpoint))),
    }


def variant(value: dict) -> dict:
    """A validated variant: its name, method, connection, prompt file and
    context switches (each on unless turned off, as runs translate)."""
    if not isinstance(value, dict):
        raise ValueError("A variant is a JSON object")
    name = str(value.get("name") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", name):
        raise ValueError("Name the variant with letters, digits, '.', '_' or '-'")
    method = value.get("method")
    if method not in quality_set.METHODS:
        raise ValueError(f"{name}: method must be one of {', '.join(quality_set.METHODS)}")
    unknown = set(value) - {
        "name", "method", "provider", "model", "endpoint", "execution", "effort",
        "keyless", "prompt", "context",
    }
    if unknown:
        raise ValueError(f"{name}: unknown fields {', '.join(sorted(unknown))}")
    switches = value.get("context") or {}
    if not isinstance(switches, dict) or set(switches) - set(CONTEXT_SWITCHES) or not all(
        type(on) is bool for on in switches.values()
    ):
        raise ValueError(f"{name}: context switches are {', '.join(CONTEXT_SWITCHES)}, each true or false")
    prompt = value.get("prompt")
    if prompt is not None:
        prompt = str(Path(prompt).expanduser().resolve())
        if not Path(prompt).is_file():
            raise ValueError(f"{name}: no prompt file {prompt}")
    return {
        "name": name,
        "method": method,
        **_connection(value, name),
        "prompt": prompt,
        "context": {switch: switches.get(switch, True) for switch in CONTEXT_SWITCHES},
    }


def judge(value: dict | None = None) -> dict:
    """A validated judge: its connection, output limit and prompt files."""
    value = dict(value or {})
    prompts = value.pop("prompts", None) or {}
    limit = value.pop("max_output_tokens", DEFAULT_MAX_OUTPUT_TOKENS)
    if type(limit) is not int or limit < 1:
        raise ValueError("judge: max_output_tokens is a whole number")
    connection = _connection(value, "judge")
    files = {
        kind: Path(prompts[kind]).expanduser().resolve() if kind in prompts else runtime_data_file(path)
        for kind, path in JUDGE_PROMPTS.items()
    }
    return {
        **connection,
        "max_output_tokens": limit,
        "prompts": {kind: path.read_text(encoding="utf-8") for kind, path in files.items()},
        "prompt_files": {kind: str(path) for kind, path in files.items()},
    }


def _candidate(connection: dict) -> dict:
    """The connection as evaluation's pricing reads it."""
    return {
        "provider": connection["provider"],
        "model": connection["model"],
        "endpoint": connection["endpoint"],
        "execution": connection["execution"],
        "keyless": connection["keyless"],
        "label": connection.get("name") or connection["model"],
    }


def _prompt_text(value: dict) -> str:
    from util.skills.system import base_system_prompt

    return base_system_prompt(value["prompt"])


# Items


def load(set_path: Path, targeted: Iterable[Path] = ()) -> dict:
    """A regression set and targeted item files as one list of items, each
    with its scope: the set's ``tune`` or ``held-out`` half, or
    ``targeted:<file name>``."""
    header, items = quality_set.load(set_path)
    if header["kind"] != "set":
        raise ValueError(f"{set_path} is a targeted item file, not a regression set")
    files = [{"name": header["name"], "kind": "set", "version": header["version"], "path": str(set_path)}]
    contexts = {f"{header['name']}/{key}": value for key, value in header["contexts"].items()}
    loaded = []
    for item in items:
        loaded.append({**item, "key": f"{header['name']}/{item['id']}", "scope": item["split"],
                       "context": f"{header['name']}/{item['context']}"})
    for path in targeted:
        extra, extra_items = quality_set.load(path)
        if extra["kind"] != "targeted":
            raise ValueError(f"{path} is a regression set, not a targeted item file")
        if extra["language"] != header["language"]:
            raise ValueError(f"{path} translates another language pair than the set")
        if any(entry["name"] == extra["name"] for entry in files):
            raise ValueError(f"Two files are named {extra['name']}")
        files.append({"name": extra["name"], "kind": "targeted", "version": extra["version"], "path": str(path)})
        contexts.update({f"{extra['name']}/{key}": value for key, value in extra["contexts"].items()})
        for item in extra_items:
            loaded.append({**item, "key": f"{extra['name']}/{item['id']}", "scope": "targeted:" + extra["name"],
                           "context": f"{extra['name']}/{item['context']}"})
    return {"files": files, "language": header["language"], "contexts": contexts, "items": loaded,
            "by_key": {item["key"]: item for item in loaded}}


def scopes(loaded: dict) -> list[str]:
    found = list(dict.fromkeys(item["scope"] for item in loaded["items"]))
    return sorted(found, key=lambda scope: ({"held-out": 0, "tune": 1}.get(scope, 2), scope))


# Requests


def _system(value: dict, context: dict) -> str:
    from util.skills.system import compose_system_prompt

    return compose_system_prompt(_prompt_text(value), context["overlays"])


def _guided(item: dict, context: dict, value: dict, language: dict) -> dict:
    """The request Guided's translateAI queues for the item's chunk: its
    lines as the RPG Maker module sends them, the previous lines as source
    context, the matched glossary and SFX reference."""
    from util.rpgmaker_blocks import message_entry
    from util.translation import CONTEXT_SOURCE, buildClaudeRequest, buildOpenAIRequest

    from dazedtl.compatibility.request_parameters import provider_defaults
    from dazedtl.settings.preferences import GENERATION_PARAMETERS

    switches = value["context"]

    def sent(line: dict) -> str:
        speaker = (line.get("speaker_name") or "") if switches["speakers"] else ""
        return message_entry(line["source"], speaker) or line["source"]

    lines = [sent(line) for line in item["lines"]]
    history = [sent(line) for line in item["history"]][-10:] if switches["history"] else []
    segments = [
        {"id": f"{item['key']}#{index}", "source": text, "scene_id": item["key"],
         "stratum": item["type"], "initial_history": history}
        for index, text in enumerate(lines)
    ]
    logical = evaluation._build_logical_requests(
        segments, _system(value, context),
        context["glossary"] if switches["glossary"] else "", len(lines),
        switches["sfx"], language["target"],
    )[0]
    vocab = logical["glossary"] + logical["sfx_reference"]
    if value["provider"] == "anthropic":
        params = buildClaudeRequest(
            logical["system"], logical["user"], logical["history"], "json",
            value["model"], len(lines), vocab_text=vocab, context_kind=CONTEXT_SOURCE,
        )
    else:
        params = buildOpenAIRequest(
            logical["system"], logical["user"], logical["history"], 0.05, "json",
            value["model"], len(lines), vocab_text=vocab, api_provider=value["provider"],
            context_kind=CONTEXT_SOURCE, api_url=value["endpoint"],
        )
    params = provider_defaults(params, GENERATION_PARAMETERS)
    return {
        "method": "guided",
        "params": params,
        "sources": {str(index + 1): text for index, text in enumerate(logical["protected_sources"])},
        "sent": lines,
        "protected": logical["protected_sources"],
        "replacements": logical["replacements"],
    }


def _assistant_configuration(value: dict) -> dict:
    from dazedtl.settings.preferences import GENERATION_PARAMETERS
    from dazedtl.translation.requests import LINE_KEYS

    return {
        "provider": value["provider"],
        "protocol": value["provider"],
        "model": value["model"],
        "endpoint": value["endpoint"],
        "mode": value["execution"],
        "lineKeys": LINE_KEYS,
        "generationParameters": GENERATION_PARAMETERS,
        "maxOutputTokens": None,
    }


def _assistant_led(item: dict, context: dict, value: dict, language: dict) -> dict:
    """The request an Assistant-led run sends for the item's chunk as one
    plan batch: its lines by unit ID with their speakers and kinds, and the
    preceding Japanese as source context."""
    from util.len_translation import request_context, request_glossary
    from util.prompt_pair import render

    from dazedtl.compatibility.translation import finish_context, request_payload
    from dazedtl.translation.requests import logical_request, provider_sources

    switches = value["context"]
    ids = [f"{item['id']}/{index + 1}" for index in range(len(item["lines"]))]
    sources = {identity: line["source"] for identity, line in zip(ids, item["lines"])}
    speakers = {
        identity: (line.get("speaker") if switches["speakers"] else None)
        for identity, line in zip(ids, item["lines"])
    }
    shared = {
        "system": render(_system(value, context), language["source"], language["target"]),
        "glossary": request_glossary(context["glossary"]) if switches["glossary"] else "",
        "content_sha256": "",
    }
    request_ctx = request_context(
        None, sources, speakers=speakers,
        source_context="\n".join(line["source"] for line in item["history"]) if switches["history"] else "",
        language=language["target"], _shared=shared,
        _reference_pack={"status": "not-configured", "matches": {}},
    )
    if not switches["sfx"]:
        request_ctx["sfx_reference"] = ""
    finish_context(request_ctx, {"scene_context": ""}, language["target"])
    request = logical_request(
        {"id": item["id"], "sources": sources, "speakers": speakers,
         "kinds": {identity: line["kind"] for identity, line in zip(ids, item["lines"])}},
        request_ctx,
    )
    configuration = _assistant_configuration(value)
    return {
        "method": "assistant-led",
        "params": request_payload(request, configuration),
        "sources": provider_sources(request, configuration),
        "request": request,
        "ids": ids,
    }


def request(item: dict, loaded: dict, value: dict) -> dict | None:
    """The item's request under the variant, None when its method's request
    cannot be built from the item."""
    from util.languages import reading

    if quality_set.unavailable(item, value["method"]):
        return None
    context = loaded["contexts"][item["context"]]
    language = loaded["language"]
    with reading(language["source"], language["target"]):
        built = (_guided if value["method"] == "guided" else _assistant_led)(item, context, value, language)
    evaluation.apply_reasoning(built["params"], value["provider"], value["effort"] or "provider_default")
    built["key"] = _digest(built["params"])[:32]
    return built


def reply(item: dict, built: dict, raw: dict | None, error: str | None = None) -> dict:
    """The item's target line out of its request's reply: its translation
    and what the mechanical gate found, whole-request faults included."""
    from util.speakers import strip_speaker_prefix
    from util.translation import extractTranslation, restore_script_codes

    target = item["target"]
    if raw is None:
        return {"valid": False, "translation": "", "issues": [error or "No reply"]}
    text = raw.get("text", "")
    if built["method"] == "guided":
        translations = extractTranslation(text, True)
        issues = []
        if not isinstance(translations, list):
            translations, issues = [], ["Response was not parseable JSON"]
        if len(translations) != len(built["sent"]):
            issues.append(f"Line count differs ({len(built['sent'])} expected, {len(translations)} returned)")
        line = translations[target] if target < len(translations) else ""
        replacements = built["replacements"][target]
        issues += evaluation.translation_issues(
            built["sent"][target], built["protected"][target], replacements, line
        )
        translation = strip_speaker_prefix(
            restore_script_codes(line, replacements, escape_orphan_backslashes=True)
        )
        return {"valid": not issues, "translation": translation, "issues": issues}
    from dazedtl.translation.requests import LINE_KEYS, from_provider, result_value

    issues = []
    line = ""
    try:
        values = result_value(
            built["request"], from_provider(built["request"], {"lineKeys": LINE_KEYS}, text)
        )
        line = values[built["ids"][target]]
    except ValueError as exc:
        issues.append(str(exc))
    source = item["lines"][target]["source"]
    issues += evaluation.translation_issues(source, source, {}, line)
    return {"valid": not issues, "translation": line, "issues": issues}


# Saved requests and their replies


def _rows_ceiling(params: dict) -> int:
    return int(params.get("max_tokens") or params.get("max_completion_tokens") or 0)


def estimate(requests: list[tuple[dict, int]], connection: dict) -> dict:
    """What *requests*, each (params, expected reply tokens), likely cost and
    the most they can cost, priced as evaluation prices its candidates."""
    from dazedtl.translation.requests import sent_tokens

    inputs = sum(sent_tokens(params, _token_count) for params, _reply in requests)
    outputs = sum(reply_tokens for _params, reply_tokens in requests)
    ceiling = sum(_rows_ceiling(params) for params, _reply in requests)
    value = evaluation.estimate_cost(_candidate(connection), inputs, outputs, ceiling)
    return {"requests": len(requests), **value}


def _token_count(text: str) -> int:
    from util.translation import approximate_tokens

    return approximate_tokens(text)


def _reply_tokens(built: dict) -> int:
    from util.translation import output_allowance

    return output_allowance(_token_count(json.dumps(built["sources"], ensure_ascii=False)))


class ProviderTransport:
    """Sends requests to the connection's provider: a Batch where it takes
    one, else one by one."""

    def __init__(self, connection: dict, secret: str = ""):
        self.connection = connection
        self.secret = secret
        self.batch = connection["execution"] == "batch"
        self.free = connection["keyless"]
        self._client = None

    def client(self):
        if self._client is None:
            self._client = batch_api.get_client(
                self.connection["provider"], api_key=self.secret,
                api_url=self.connection["endpoint"] or None, max_retries=0,
            )
        return self._client

    def submit(self, rows: list[dict]) -> str:
        google = batch_api._google_client(self.secret) if self.connection["provider"] == "gemini" else None
        return batch_api.submit_batch(
            self.connection["provider"], rows, client=self.client(), google_client=google
        )["id"]

    def status(self, batch_id: str) -> dict:
        return batch_api.retrieve_batch(self.connection["provider"], batch_id, client=self.client())

    def results(self, batch_id: str, custom_ids: dict) -> tuple[dict, list, dict]:
        google = batch_api._google_client(self.secret) if self.connection["provider"] == "gemini" else None
        return batch_api.download_results(
            self.connection["provider"], batch_id, custom_ids, client=self.client(), google_client=google
        )

    def live(self, params: dict) -> dict:
        return batch_api.execute_live_request(self.connection["provider"], params, client=self.client())


def _usage(raw: dict) -> dict:
    cached = int(raw.get("cache_read_input_tokens", 0) or 0)
    written = int(raw.get("cache_creation_input_tokens", 0) or 0)
    return {
        "input_tokens": max(0, int(raw.get("prompt_tokens", 0) or 0) - cached - written),
        "output_tokens": int(raw.get("completion_tokens", 0) or 0),
        "cache_read_input_tokens": cached,
        "cache_creation_input_tokens": written,
        "thinking_tokens": int(raw.get("thinking_tokens", 0) or 0),
    }


def _limit(cap: float | None, transport) -> float:
    if transport.free:
        return float("inf")
    if cap is None or cap <= 0:
        raise ValueError("Paid requests need an approved cap: pass --cap with the dollars approved")
    return float(cap)


def execute(path: Path, identity: dict, wanted: dict[str, tuple[dict, int]], *, transport,
            connection: dict, cap: float | None, log: Callable[[str], None] = print,
            wait: bool = False, retry_failed: bool = False, poll_seconds: float = 30.0) -> dict:
    """Sends the *wanted* requests (key: (params, expected reply tokens))
    that have no saved reply, keeping replies in the store at *path*, whose
    *identity* must match. Requests go in slices whose most possible cost
    fits what *cap* has left after what was spent and what pending Batches
    may cost; without *wait*, a pending Batch is left to the next call."""
    state = _read_json(path)
    if state is None:
        state = {"identity": identity, "results": {}, "errors": {}, "pending": [], "spent_usd": 0.0}
    elif state.get("identity") != identity:
        raise ValueError(
            f"{path} holds other work: its saved identity differs; use another ID or the same settings"
        )
    candidate = _candidate(connection)

    def save() -> None:
        state["updated"] = _now()
        _write_json(path, state)

    def collect() -> None:
        for batch in list(state["pending"]):
            status = transport.status(batch["id"])
            if not status["ended"]:
                continue
            try:
                found, errors, usage = transport.results(batch["id"], batch["custom_ids"])
                # Requests carry the five-minute cache, as translation runs' do.
                spent = evaluation._price_usage(candidate, usage, cache_ttl="5m")
            except Exception as exc:  # noqa: BLE001 - a failed Batch fails its requests, saved
                # A failed Batch may have billed the rows it finished, which
                # it does not report, so it counts as costing its most.
                found, spent = {}, batch["ceiling_usd"]
                errors = [(custom, str(exc)) for custom in batch["custom_ids"]]
            state["results"].update(found)
            for custom, message in errors:
                # Providers name a failed row by its custom ID.
                key = batch["custom_ids"].get(custom, custom)
                if key in batch["custom_ids"].values() and key not in found:
                    state["errors"][key] = str(message)
            for key in batch["custom_ids"].values():
                if key not in found and key not in state["errors"]:
                    state["errors"][key] = "The Batch returned no reply"
            state["spent_usd"] += spent
            state["pending"].remove(batch)
            log(f"Batch {batch['id']}: {len(found)} replies, {len(batch['custom_ids']) - len(found)} without")
            save()

    # Requests this call sent: a failed one is retried at most once a call.
    tried: set[str] = set()

    def missing() -> list[str]:
        waiting = {key for batch in state["pending"] for key in batch["custom_ids"].values()}
        return [
            key for key in wanted
            if key not in state["results"] and key not in waiting
            and (key not in state["errors"] or (retry_failed and key not in tried))
        ]

    def send(keys: list[str]) -> bool:
        limit = _limit(cap, transport)
        left = limit - state["spent_usd"] - sum(batch["ceiling_usd"] for batch in state["pending"])
        chosen, ceiling = [], 0.0
        for key in keys:
            most = estimate([wanted[key]], connection)["maximum_cost_usd"]
            if ceiling + most > left:
                break
            chosen.append(key)
            ceiling += most
        if not chosen:
            if not state["pending"]:
                raise ValueError(
                    f"The cap of ${limit:.2f} is spent (${state['spent_usd']:.2f}); "
                    f"{len(keys)} requests are left unsent. Approve a higher cap to go on."
                )
            return False
        for key in chosen:
            state["errors"].pop(key, None)
        tried.update(chosen)
        if transport.batch:
            custom_ids = {f"q{index:06d}": key for index, key in enumerate(chosen)}
            batch_id = transport.submit(
                [{"custom_id": custom, "params": wanted[key][0]} for custom, key in custom_ids.items()]
            )
            state["pending"].append({
                "id": batch_id, "custom_ids": custom_ids, "ceiling_usd": ceiling, "submitted": _now(),
            })
            log(f"Submitted Batch {batch_id}: {len(chosen)} requests, at most ${ceiling:.2f}")
            save()
            return True
        for index, key in enumerate(chosen, 1):
            try:
                raw = transport.live(wanted[key][0])
                state["results"][key] = raw
                state["spent_usd"] += evaluation._price_usage(candidate, _usage(raw), cache_ttl="5m")
            except Exception as exc:  # noqa: BLE001 - kept as this request's failure
                state["errors"][key] = str(exc)
            if index % 10 == 0 or index == len(chosen):
                save()
        return True

    collect()
    unsent = missing()
    if unsent:
        cost = estimate([wanted[key] for key in unsent], connection)
        log(
            f"{len(unsent)} requests to send: likely ${cost['cost_usd']:.2f}, at most "
            f"${cost['maximum_cost_usd']:.2f}; spent ${state['spent_usd']:.2f}"
            + ("" if transport.free or cap is None else f" of the ${cap:.2f} cap")
        )
    while True:
        keys = missing()
        sent = send(keys) if keys else False
        if not wait or not (state["pending"] or (sent and missing())):
            break
        if state["pending"]:
            time.sleep(poll_seconds)
            collect()
    save()
    return state


# Runs


def _run_identity(value: dict) -> dict:
    return {"schema": RUN_SCHEMA, "version": RUN_VERSION, "variant": value,
            "prompt_sha256": _digest(_prompt_text(value))}


def run_path(runs: Path, run_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", run_id or ""):
        raise ValueError("A run ID is letters, digits, '.', '_' or '-'")
    return Path(runs) / run_id / "run.json"


def requests_for(loaded: dict, value: dict) -> dict[str, dict]:
    """Each item's built request under *value*, by item key; an item its
    method cannot be built from is left out."""
    built = {}
    for item in loaded["items"]:
        made = request(item, loaded, value)
        if made is not None:
            built[item["key"]] = made
    return built


def translate(loaded: dict, value: dict, runs: Path, run_id: str, *, transport, cap: float | None,
              log: Callable[[str], None] = print, wait: bool = False, retry_failed: bool = False,
              poll_seconds: float = 30.0) -> dict:
    """Translates the items under *value* as run *run_id*, reusing every
    reply the run already holds."""
    path = run_path(runs, run_id)
    built = requests_for(loaded, value)
    wanted = {made["key"]: (made["params"], _reply_tokens(made)) for made in built.values()}
    state = execute(path, _run_identity(value), wanted, transport=transport, connection=value, cap=cap,
                    log=log, wait=wait, retry_failed=retry_failed, poll_seconds=poll_seconds)
    return {"run_id": run_id, **progress(state, wanted)}


def progress(state: dict, wanted: Iterable[str]) -> dict:
    keys = list(wanted)
    waiting = {key for batch in state["pending"] for key in batch["custom_ids"].values()}
    return {
        "requests": len(keys),
        "replied": sum(key in state["results"] for key in keys),
        "failed": sum(key in state["errors"] and key not in state["results"] for key in keys),
        "pending": sum(key in waiting for key in keys),
        "spent_usd": state["spent_usd"],
    }


def run_lines(loaded: dict, runs: Path, run_id: str) -> tuple[dict, dict[str, dict]]:
    """A finished run's variant and each item's target line (reply), by
    item key; refuses a run with requests still unanswered and unfailed."""
    path = run_path(runs, run_id)
    state = _read_json(path)
    if state is None:
        raise ValueError(f"No run {run_id} in {runs}")
    value = state["identity"]["variant"]
    if state["identity"] != _run_identity(value):
        raise ValueError(f"Run {run_id} was made under another prompt file or run version")
    built = requests_for(loaded, value)
    open_keys = [
        made["key"] for made in built.values()
        if made["key"] not in state["results"] and made["key"] not in state["errors"]
    ]
    if open_keys:
        raise ValueError(f"Run {run_id} has {len(open_keys)} requests without a reply; translate it again first")
    lines = {
        key: reply(_item(loaded, key), made, state["results"].get(made["key"]), state["errors"].get(made["key"]))
        for key, made in built.items()
    }
    return value, lines


def _item(loaded: dict, key: str) -> dict:
    return loaded["by_key"][key]


# Judging


DEFECT_SCHEMA = {
    "type": "object",
    "properties": {"repeats": {"type": "boolean"}, "evidence": {"type": "string"}},
    "required": ["repeats", "evidence"],
    "additionalProperties": False,
}
PAIRWISE_SCHEMA = {
    "type": "object",
    "properties": {"worse": {"type": "string", "enum": ["A", "B", "neither"]}, "evidence": {"type": "string"}},
    "required": ["worse", "evidence"],
    "additionalProperties": False,
}


def judged_by_glossary(item: dict) -> bool:
    return item["type"] == "defect" and bool(item.get("glossary"))


def glossary_kept(item: dict, translation: str) -> bool:
    """Whether a line keeps the English of every glossary row its item's
    correction follows, exactly as the glossary spells it."""
    return all(row["target"] in translation for row in item["glossary"])


def _scene(item: dict) -> str:
    def shown(line: dict) -> str:
        name = line.get("speaker_name") or line.get("speaker")
        text = line["source"].replace("\n", " ")
        return f"[{name}] {text}" if name else text

    rows = ["   " + shown(line) for line in item["history"]]
    rows += [(">> " if index == item["target"] else "   ") + shown(line) for index, line in enumerate(item["lines"])]
    return "\n".join(rows)


def _judge_params(config: dict, kind: str, user: str) -> dict:
    from dazedtl.settings.providers import completion_field, response_format

    schema = DEFECT_SCHEMA if kind == "defect" else PAIRWISE_SCHEMA
    prompt = config["prompts"][kind]
    if config["provider"] == "anthropic":
        params: dict[str, Any] = {
            "model": config["model"],
            "max_tokens": config["max_output_tokens"],
            "system": [{"type": "text", "text": prompt}],
            "messages": [{"role": "user", "content": user}],
            "output_config": {"format": {"type": "json_schema", "schema": schema}},
        }
    else:
        params = {
            "model": config["model"],
            "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": user}],
            "response_format": response_format(
                config["provider"], config["endpoint"], config["model"], schema, "quality_judgment",
                batch=config["execution"] == "batch",
            ),
        }
        field = "max_completion_tokens" if completion_field(config["provider"], config["endpoint"]) else "max_tokens"
        params[field] = config["max_output_tokens"]
    return evaluation.apply_reasoning(params, config["provider"], config["effort"] or "provider_default")


def _defect_task(config: dict, language: dict, item: dict, line: str) -> dict:
    user = (
        f"Source language: {language['source']}. Target language: {language['target']}.\n\n"
        f"Source scene, the line under review marked >>:\n```\n{_scene(item)}\n```\n\n"
        f"The defect a reviewer found in an earlier translation of the marked line:\n{item['reason']}\n\n"
        f"Translation of the marked line to check:\n```\n{line}\n```"
    )
    return {"kind": "defect", "params": _judge_params(config, "defect", user)}


def _pairwise_task(config: dict, language: dict, item: dict, candidate: str, reference: str,
                   seed: str) -> dict:
    first = random.Random(seed).random() < 0.5
    left, right = (candidate, reference) if first else (reference, candidate)
    user = (
        f"Source language: {language['source']}. Target language: {language['target']}.\n\n"
        f"Source scene, the line under review marked >>:\n```\n{_scene(item)}\n```\n\n"
        f"Translation A of the marked line:\n```\n{left}\n```\n\n"
        f"Translation B of the marked line:\n```\n{right}\n```"
    )
    return {"kind": "pairwise", "params": _judge_params(config, "pairwise", user),
            "candidate": "A" if first else "B"}


def _same(left: str, right: str) -> bool:
    return re.sub(r"\s+", " ", left).strip() == re.sub(r"\s+", " ", right).strip()


def judge_tasks(config: dict, loaded: dict, lines: dict[str, dict[str, dict]]) -> dict[str, dict]:
    """Every judgment a comparison needs, by key: the calibration of the
    judge on each judged defect's first draft and correction, then the runs'
    judged defects and controls whose line passed the gate. Each task holds
    what the stand-in judge answers from (``truth``), which is never sent."""
    language = loaded["language"]
    tasks: dict[str, dict] = {}

    def add(key: str, task: dict, truth: Any) -> None:
        task["truth"] = truth
        tasks[key] = task

    for item in loaded["items"]:
        if item["type"] != "defect" or judged_by_glossary(item):
            continue
        # The judge reads the reviewer's description of this very draft, so
        # flagging it is easier than flagging a new line's wording.
        add(f"calibration/draft/{item['key']}", _defect_task(config, language, item, item["draft"]), True)
        add(f"calibration/accepted/{item['key']}", _defect_task(config, language, item, item["accepted"]), False)
        add(f"calibration/pair/{item['key']}",
            _pairwise_task(config, language, item, item["draft"], item["accepted"], "calibration/" + item["key"]),
            "candidate")
    for run_id, run in lines.items():
        for key, line in run.items():
            item = _item(loaded, key)
            if not line["valid"] or judged_by_glossary(item):
                continue
            if item["type"] == "defect":
                add(f"run/{run_id}/{key}", _defect_task(config, language, item, line["translation"]),
                    _same(line["translation"], item["draft"]))
            else:
                add(f"run/{run_id}/{key}",
                    _pairwise_task(config, language, item, line["translation"], item["accepted"],
                                   f"{run_id}/{key}"),
                    "neither")
    return tasks


class StandInJudge:
    """Answers judgments from the set's own labels, for tests and dry runs
    only: a line repeats a defect only when it is the first draft, and of a
    draft and its correction the draft is worse. Its scores measure nothing,
    and reports made with it say so."""

    batch = False
    free = True

    def __init__(self, tasks: dict[str, dict]):
        self.answers = {}
        for task in tasks.values():
            if task["kind"] == "defect":
                answer = {"repeats": bool(task["truth"]), "evidence": "stand-in"}
            elif task["truth"] == "candidate":
                answer = {"worse": task["candidate"], "evidence": "stand-in"}
            else:
                answer = {"worse": "neither", "evidence": "stand-in"}
            self.answers[_digest(task["params"])] = json.dumps(answer)

    def live(self, params: dict) -> dict:
        return {"text": self.answers[_digest(params)], "prompt_tokens": 0, "completion_tokens": 0}


def _judgment(kind: str, raw: dict | None) -> dict | None:
    if raw is None:
        return None
    text = str(raw.get("text") or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        value = json.loads(text)
    except ValueError:
        return None
    if kind == "defect" and isinstance(value, dict) and type(value.get("repeats")) is bool:
        return value
    if kind == "pairwise" and isinstance(value, dict) and value.get("worse") in ("A", "B", "neither"):
        return value
    return None


def _task_key(key: str, task: dict) -> str:
    # The judgment's own key holds the run and role, so two runs' identical
    # lines get independent judgments and the noise floor keeps the judge's.
    return _digest({"task": key, "params": task["params"]})[:32]


# Scores


def calibration(tasks: dict[str, dict], judged: dict[str, dict | None]) -> dict:
    """How well the judge separated the first drafts from their corrections:
    for the defect question, the share of drafts it flagged (sensitivity) and
    of corrections it passed (specificity); for the pairwise one, the share
    of pairs where it found the draft worse and where it found the correction
    worse. J is their separation (CALIBRATION_MINIMUM)."""
    flagged = {"draft": [], "accepted": []}
    pairs = {"draft": 0, "accepted": 0, "total": 0}
    unanswered = 0
    for key, task in tasks.items():
        if not key.startswith("calibration/"):
            continue
        value = judged.get(key)
        if value is None:
            unanswered += 1
            continue
        role = key.split("/")[1]
        if role in flagged:
            flagged[role].append(bool(value["repeats"]))
        else:
            pairs["total"] += 1
            if value["worse"] == task["candidate"]:
                pairs["draft"] += 1
            elif value["worse"] != "neither":
                pairs["accepted"] += 1

    def share(values: list[bool]) -> float | None:
        return sum(values) / len(values) if values else None

    sensitivity = share(flagged["draft"])
    false_flags = share(flagged["accepted"])
    defect_j = None if sensitivity is None or false_flags is None else sensitivity - false_flags
    pair_j = (pairs["draft"] - pairs["accepted"]) / pairs["total"] if pairs["total"] else None
    passed = all(value is not None and value >= CALIBRATION_MINIMUM for value in (defect_j, pair_j))
    return {
        "defect": {"drafts_flagged": sensitivity, "corrections_passed": None if false_flags is None else 1 - false_flags,
                   "cases": len(flagged["draft"]), "j": defect_j},
        "pairwise": {"drafts_worse": pairs["draft"] / pairs["total"] if pairs["total"] else None,
                     "corrections_worse": pairs["accepted"] / pairs["total"] if pairs["total"] else None,
                     "cases": pairs["total"], "j": pair_j},
        "unanswered": unanswered,
        "minimum": CALIBRATION_MINIMUM,
        "passed": passed,
    }


def item_scores(loaded: dict, run_id: str, run: dict[str, dict], tasks: dict[str, dict],
                judged: dict[str, dict | None]) -> dict[str, dict[str, float]]:
    """Each item's value of every metric it has in one run, by item key."""
    scores: dict[str, dict[str, float]] = {}
    for key, line in run.items():
        item = _item(loaded, key)
        values: dict[str, float] = {"validity": float(line["valid"])}
        if line["valid"]:
            if judged_by_glossary(item):
                kept = glossary_kept(item, line["translation"])
                values["glossary"] = float(kept)
                values["defects"] = float(not kept)
            else:
                judgment = judged.get(f"run/{run_id}/{key}")
                if judgment is not None:
                    if item["type"] == "defect":
                        values["repeats"] = float(judgment["repeats"])
                        values["defects"] = float(judgment["repeats"])
                    else:
                        task = tasks[f"run/{run_id}/{key}"]
                        values["regressions"] = float(judgment["worse"] == task["candidate"])
        scores[key] = values
    return scores


def _interval(values: list[float], clusters: list[str], seed: str) -> list[float] | None:
    """A 95% percentile bootstrap interval of the mean of *values*,
    resampling whole clusters (an item, or its recurring group)."""
    if len(values) < 2:
        return None
    grouped: dict[str, list[float]] = defaultdict(list)
    for value, cluster in zip(values, clusters):
        grouped[cluster].append(value)
    groups = list(grouped.values())
    draw = random.Random(seed)
    means = []
    for _ in range(BOOTSTRAP_SAMPLES):
        sample = [value for _ in groups for value in groups[draw.randrange(len(groups))]]
        means.append(sum(sample) / len(sample))
    means.sort()
    return [round(means[int(0.025 * (len(means) - 1))], 4), round(means[int(0.975 * (len(means) - 1))], 4)]


def _rate(values: list[float]) -> dict | None:
    if not values:
        return None
    from util.evaluation_pairwise import _binomial_bounds

    hits = round(sum(values))
    low, high = _binomial_bounds(hits, len(values), 0.025)
    return {"rate": hits / len(values), "count": len(values), "interval": [round(low, 4), round(high, 4)]}


def compare_scores(loaded: dict, scores: dict[str, dict[str, dict[str, float]]], baseline: list[str],
                   variants: list[str], *, judge_trusted: bool) -> dict:
    """Each scope's rates per run, the noise floor between the two baseline
    runs and each variant's change against their mean, with intervals and
    whether it counts."""
    report: dict[str, Any] = {}
    first, second = baseline
    for scope in scopes(loaded):
        items = [item for item in loaded["items"] if item["scope"] == scope]
        section: dict[str, Any] = {"items": len(items), "metrics": {}}
        for metric, (higher, meaning) in METRICS.items():
            if metric in JUDGED_METRICS and not judge_trusted:
                section["metrics"][metric] = {"withheld": "judge calibration below the minimum"}
                continue
            rates = {
                run_id: _rate([scores[run_id][i["key"]][metric] for i in items
                               if metric in scores[run_id].get(i["key"], {})])
                for run_id in [*baseline, *variants]
            }
            if all(value is None for value in rates.values()):
                continue
            paired = [
                item for item in items
                if all(metric in scores[run_id].get(item["key"], {}) for run_id in [*baseline, *variants])
            ]
            clusters = [item.get("group") or item["key"] for item in paired]

            def values(run_id: str, paired: list[dict] = paired, metric: str = metric) -> list[float]:
                return [scores[run_id][item["key"]][metric] for item in paired]

            noise_values = [b - a for a, b in zip(values(first), values(second))]
            noise = sum(noise_values) / len(noise_values) if noise_values else 0.0
            noise_interval = _interval(noise_values, clusters, f"{scope}/{metric}/noise")
            # The floor is the largest gap the two baseline runs' interval
            # admits, not only their mean gap, which items changing both
            # ways would cancel out.
            floor = max([abs(noise), *(abs(bound) for bound in noise_interval or [])])
            entry: dict[str, Any] = {
                "meaning": meaning,
                "higher_is_better": higher,
                "rates": rates,
                "paired_items": len(paired),
                "noise": {"gap": noise, "interval": noise_interval, "floor": floor},
                "changes": {},
            }
            mean = [(a + b) / 2 for a, b in zip(values(first), values(second))]
            for run_id in variants:
                deltas = [v - m for v, m in zip(values(run_id), mean)]
                delta = sum(deltas) / len(deltas) if deltas else 0.0
                interval = _interval(deltas, clusters, f"{scope}/{metric}/{run_id}")
                better = delta if higher else -delta
                # A change counts, either way, beyond the floor and with an
                # interval that keeps clear of no change.
                counts = abs(delta) > floor and interval is not None and (interval[0] > 0 or interval[1] < 0)
                entry["changes"][run_id] = {
                    "delta": delta,
                    "interval": interval,
                    "gain": better > 0 and counts,
                    "regression": better < 0 and counts,
                }
            section["metrics"][metric] = entry
        report[scope] = section
    return report


def verdict(report: dict, variant_id: str, *, judge_trusted: bool) -> dict:
    """Whether the variant may land: no regression on the held-out half in
    validity, defects or control regressions, and a gain on its targeted
    items with no regression there."""
    if not judge_trusted:
        return {"pass": False, "reason": "the judge's calibration is below the minimum, so its scores are withheld"}
    held = report.get("held-out", {}).get("metrics", {})
    regressions = [
        metric for metric in ("validity", "defects", "regressions")
        if held.get(metric, {}).get("changes", {}).get(variant_id, {}).get("regression")
    ]
    if regressions:
        return {"pass": False, "reason": "regression on the held-out half: " + ", ".join(regressions)}
    targeted = {scope: section for scope, section in report.items() if scope.startswith("targeted:")}
    if not targeted:
        return {"pass": False, "reason": "no regression on the held-out half, but no targeted items show a gain"}
    for scope, section in targeted.items():
        changes = [entry.get("changes", {}).get(variant_id, {}) for entry in section["metrics"].values()]
        if any(change.get("regression") for change in changes):
            return {"pass": False, "reason": f"regression on {scope}"}
        if not any(change.get("gain") for change in changes):
            return {"pass": False, "reason": f"no gain beyond the noise floor on {scope}"}
    return {"pass": True, "reason": "no held-out regression and a gain on every targeted file"}


def comparison_path(runs: Path, compare_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", compare_id or ""):
        raise ValueError("A comparison ID is letters, digits, '.', '_' or '-'")
    return Path(runs) / compare_id / "judgments.json"


def compare(loaded: dict, runs: Path, baseline: list[str], variants: list[str], config: dict, *,
            compare_id: str, transport, cap: float | None, stand_in: bool = False,
            log: Callable[[str], None] = print, wait: bool = False, poll_seconds: float = 30.0) -> dict:
    """Judges the runs and reports their comparison. *transport* sends the
    judgments; with *stand_in* it is the StandInJudge."""
    if len(baseline) != 2 or len(set(baseline)) != 2:
        raise ValueError("Name the two runs of the baseline, for the noise floor")
    if set(baseline) & set(variants):
        raise ValueError("A baseline run cannot also be a variant run")
    values = {}
    lines = {}
    for run_id in [*baseline, *variants]:
        values[run_id], lines[run_id] = run_lines(loaded, runs, run_id)
    first, second = (copy.deepcopy(values[run_id]) for run_id in baseline)
    if first != second:
        raise ValueError("The two baseline runs were made under different variants")
    tasks = judge_tasks(config, loaded, lines)
    if stand_in:
        transport = StandInJudge(tasks)
    keys = {_task_key(key, task): key for key, task in tasks.items()}
    wanted = {
        digest: (tasks[key]["params"], JUDGE_REPLY_TOKENS) for digest, key in keys.items()
    }
    identity = {
        "schema": COMPARISON_SCHEMA, "version": COMPARISON_VERSION,
        "judge": {key: config[key] for key in ("provider", "model", "endpoint", "effort", "max_output_tokens")},
        "judge_prompts_sha256": _digest(config["prompts"]),
        "stand_in": stand_in,
    }
    state = execute(comparison_path(runs, compare_id), identity, wanted, transport=transport,
                    connection=config, cap=cap, log=log, wait=wait, poll_seconds=poll_seconds)
    judged = {
        key: _judgment(tasks[key]["kind"], state["results"].get(digest))
        for digest, key in keys.items()
    }
    status = progress(state, wanted)
    if status["pending"] or (status["requests"] - status["replied"] - status["failed"]):
        return {"complete": False, "judging": status}
    trust = calibration(tasks, judged)
    scores = {run_id: item_scores(loaded, run_id, lines[run_id], tasks, judged) for run_id in lines}
    report = compare_scores(loaded, scores, baseline, variants, judge_trusted=trust["passed"])
    result = {
        "complete": True,
        "created": _now(),
        "files": loaded["files"],
        "baseline": baseline,
        "variants": {run_id: values[run_id] for run_id in [baseline[0], *variants]},
        "judge": {**identity["judge"], "prompt_files": config["prompt_files"], "stand_in": stand_in,
                  "prompts_sha256": identity["judge_prompts_sha256"]},
        "calibration": trust,
        "judging": status,
        "scopes": report,
        "verdicts": {run_id: verdict(report, run_id, judge_trusted=trust["passed"]) for run_id in variants},
    }
    _write_json(comparison_path(runs, compare_id).with_name("report.json"), result)
    return result


def render(result: dict) -> str:
    """A comparison as text."""
    if not result.get("complete"):
        status = result["judging"]
        return f"Judging is not finished: {status['replied']} of {status['requests']} replied, {status['pending']} pending."

    def pct(value: float | None) -> str:
        return "-" if value is None else f"{value * 100:.1f}%"

    lines = []
    judge = result["judge"]
    lines.append(
        f"Judge: {judge['provider']} {judge['model']}, effort {judge['effort'] or 'provider default'}"
        + (" (STAND-IN: answers from the set's labels; these scores measure nothing)" if judge["stand_in"] else "")
    )
    trust = result["calibration"]
    lines.append(
        "Calibration: defect question flags {} of drafts and passes {} of corrections (J {}, {} cases); "
        "pairwise finds the draft worse in {} and the correction worse in {} (J {}). Minimum J {:.2f}: {}.".format(
            pct(trust["defect"]["drafts_flagged"]), pct(trust["defect"]["corrections_passed"]),
            "-" if trust["defect"]["j"] is None else f"{trust['defect']['j']:.2f}", trust["defect"]["cases"],
            pct(trust["pairwise"]["drafts_worse"]), pct(trust["pairwise"]["corrections_worse"]),
            "-" if trust["pairwise"]["j"] is None else f"{trust['pairwise']['j']:.2f}",
            trust["minimum"], "passed" if trust["passed"] else "FAILED, judged scores withheld",
        )
    )
    first, second = result["baseline"]
    for scope, section in result["scopes"].items():
        lines.append("")
        lines.append(f"{scope} ({section['items']} items)")
        for metric, entry in section["metrics"].items():
            if "withheld" in entry:
                lines.append(f"  {metric}: withheld, {entry['withheld']}")
                continue
            rates = ", ".join(
                f"{run_id} {pct(rate['rate'])} of {rate['count']}" if rate else f"{run_id} -"
                for run_id, rate in entry["rates"].items()
            )
            noise = entry["noise"]
            lines.append(f"  {metric}, {entry['meaning']}: {rates}")
            lines.append(
                f"    noise {first} to {second}: {noise['gap'] * 100:+.1f} points, floor {noise['floor'] * 100:.1f}"
                + (f" [{noise['interval'][0] * 100:+.1f}, {noise['interval'][1] * 100:+.1f}]" if noise["interval"] else "")
            )
            for run_id, change in entry["changes"].items():
                mark = "GAIN" if change["gain"] else "REGRESSION" if change["regression"] else "within noise"
                interval = change["interval"]
                lines.append(
                    f"    {run_id} vs baseline: {change['delta'] * 100:+.1f} points"
                    + (f" [{interval[0] * 100:+.1f}, {interval[1] * 100:+.1f}]" if interval else "")
                    + f", {mark}"
                )
    lines.append("")
    for run_id, outcome in result["verdicts"].items():
        lines.append(f"Verdict for {run_id}: {'PASS' if outcome['pass'] else 'does not pass'}: {outcome['reason']}.")
    return "\n".join(lines)


# Estimates before any paid call


def estimate_plan(loaded: dict, values: list[dict], config: dict | None, repetitions: int = 2) -> dict:
    """What translating the items under each variant *repetitions* times
    and judging each variant's runs in a comparison of their own, which
    calibrates the judge, likely cost and may cost at most. The judgments'
    lines are unknown before the runs, so the accepted lines stand in."""
    plan: dict[str, Any] = {"repetitions": repetitions, "variants": {}}
    for value in values:
        built = requests_for(loaded, value)
        # Items in one chunk share its request, which a run sends once.
        unique = {made["key"]: made for made in built.values()}
        one = estimate([(made["params"], _reply_tokens(made)) for made in unique.values()], value)
        entry: dict[str, Any] = {
            "method": value["method"], "model": value["model"], "execution": value["execution"],
            "items": len(built), "unavailable": len(loaded["items"]) - len(built),
            "one_run": one,
            "likely_usd": one["cost_usd"] * repetitions,
            "ceiling_usd": one["maximum_cost_usd"] * repetitions,
            "judge": None,
        }
        if config is not None:
            runs = {
                f"{value['name']}-{repetition + 1}": {
                    key: {"valid": True, "translation": _item(loaded, key)["accepted"]} for key in built
                }
                for repetition in range(repetitions)
            }
            tasks = judge_tasks(config, loaded, runs)
            judged = estimate([(task["params"], JUDGE_REPLY_TOKENS) for task in tasks.values()], config)
            entry["judge"] = {
                "model": config["model"], "execution": config["execution"],
                "calibration_requests": sum(key.startswith("calibration/") for key in tasks),
                "run_requests": sum(key.startswith("run/") for key in tasks),
                "likely_usd": judged["cost_usd"], "ceiling_usd": judged["maximum_cost_usd"],
            }
        plan["variants"][value["name"]] = entry
    plan["likely_usd"] = sum(
        entry["likely_usd"] + (entry["judge"]["likely_usd"] if entry["judge"] else 0)
        for entry in plan["variants"].values()
    )
    plan["ceiling_usd"] = sum(
        entry["ceiling_usd"] + (entry["judge"]["ceiling_usd"] if entry["judge"] else 0)
        for entry in plan["variants"].values()
    )
    return plan


def render_plan(plan: dict) -> str:
    lines = []
    for name, entry in plan["variants"].items():
        one = entry["one_run"]
        lines.append(
            f"{name} ({entry['method']}, {entry['model']}, {entry['execution']}): {entry['items']} items in"
            f" {one['requests']} requests a run"
            + (f", {entry['unavailable']} items unavailable to this method" if entry["unavailable"] else "")
            + f"; one run likely ${one['cost_usd']:.2f}, at most ${one['maximum_cost_usd']:.2f}"
            f" ({one['input_tokens']:,} input, {one['output_tokens']:,} output tokens);"
            f" x{plan['repetitions']}: likely ${entry['likely_usd']:.2f}, at most ${entry['ceiling_usd']:.2f}"
        )
        judged = entry["judge"]
        if judged:
            lines.append(
                f"  its comparison's judge ({judged['model']}, {judged['execution']}): "
                f"{judged['calibration_requests']} calibration and {judged['run_requests']} run judgments;"
                f" likely ${judged['likely_usd']:.2f}, at most ${judged['ceiling_usd']:.2f}"
            )
    lines.append(
        f"total: likely ${plan['likely_usd']:.2f}, at most ${plan['ceiling_usd']:.2f}. "
        "Likely excludes reasoning tokens; at most assumes every request uses its whole output limit."
    )
    return "\n".join(lines)
