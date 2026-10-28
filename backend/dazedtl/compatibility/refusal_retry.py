"""One durable clarification allowance for a guided Live translation request."""

import json
from types import SimpleNamespace
from typing import Any

from dazedtl.translation.files import digest
from dazedtl.translation.refusals import MESSAGE, ClarifyOnce, field, refused

from .process_view import source_values

USAGE = (
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


def receipt(response):
    choice = response.choices[0]
    message = choice.message
    usage = field(response, "usage")
    return {
        "content": field(message, "content"),
        "refusal": field(message, "refusal"),
        "finish_reason": field(choice, "finish_reason"),
        "usage": {key: field(usage, key, 0) or 0 for key in USAGE},
    }


def restored(value, *, replay=False):
    usage = {key: 0 if replay else count for key, count in value["usage"].items()}
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason=value["finish_reason"],
                message=SimpleNamespace(
                    content=value["content"], refusal=value["refusal"]
                ),
            )
        ],
        usage=SimpleNamespace(**usage),
    )


def send_once(translation, evidence, params):
    """Send the extra paid call without native fallback or SDK retry loops."""
    evidence.record(params, clarification_of=evidence.local.current)
    from util.batch_providers import create_anthropic_message, get_client

    provider = "anthropic" if "system" in params else "openai"
    # The SDK client type depends on the provider chosen above.
    client: Any = get_client(
        provider,
        api_key=translation.openai.api_key,
        api_url=None
        if provider == "anthropic"
        else str(translation.openai.base_url or ""),
        max_retries=0,
    )
    options: dict[str, Any] = {"timeout": 45, "max_retries": 0}
    organization = getattr(translation.openai, "organization", None)
    if provider != "anthropic" and organization:
        options["organization"] = organization
    client = client.with_options(**options)
    try:
        if provider == "anthropic":
            raw = create_anthropic_message(client, params)
            usage = raw.usage
            cached = field(usage, "cache_read_input_tokens", 0) or 0
            created = field(usage, "cache_creation_input_tokens", 0) or 0
            response = restored(
                {
                    "content": translation._anthropic_content_text(raw.content),
                    "refusal": MESSAGE if refused(raw) else None,
                    "finish_reason": field(raw, "stop_reason"),
                    "usage": {
                        "prompt_tokens": (field(usage, "input_tokens", 0) or 0)
                        + cached
                        + created,
                        "completion_tokens": field(usage, "output_tokens", 0) or 0,
                        "cache_read_input_tokens": cached,
                        "cache_creation_input_tokens": created,
                    },
                }
            )
        else:
            response = client.chat.completions.create(**params)
        translation._log_live_response(provider, params, response)
        value = receipt(response)
        with evidence.connect() as connection:
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
                    evidence.local.current,
                ),
            )
        return response
    finally:
        client.close()


class SavedRetries:
    """Guided's clarification journal: a `clarification_retries` row per
    call, holding the request it ended on and, once known, the response a
    retry of the call replays. The clarified payload itself is kept as the
    params of its own request row (evidence.record)."""

    def __init__(self, evidence):
        self.evidence = evidence
        with evidence.connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS clarification_retries "
                "(identity TEXT PRIMARY KEY, response TEXT, request_id INTEGER)"
            )

    def __contains__(self, identity):
        return self.saved(identity) is not None

    def saved(self, identity):
        with self.evidence.connect() as connection:
            return connection.execute(
                "SELECT response,request_id FROM clarification_retries WHERE identity=?",
                (identity,),
            ).fetchone()

    def record(self, identity, _params, response=None):
        """Journal the call on the request it is at; with no response yet,
        a retry before `answer` must be reconciled instead of paid again."""
        with self.evidence.connect() as connection:
            connection.execute(
                "INSERT INTO clarification_retries VALUES (?,?,?)",
                (identity, response, self.evidence.local.current),
            )

    def answer(self, identity, response):
        with self.evidence.connect() as connection:
            connection.execute(
                "UPDATE clarification_retries SET response=?,request_id=? WHERE identity=?",
                (response, self.evidence.local.current, identity),
            )


class RefusalRetry:
    """Retries one refused translateText call with a clarification, at most once."""

    def __init__(self, evidence, call_signature, *, policy=None, translation=None):
        self.evidence, self.signature = evidence, call_signature
        self.journal = SavedRetries(evidence)
        self.clarify = ClarifyOnce(policy, self.journal)
        self.translation = translation

    def reject(self, response):
        evidence = self.evidence
        value = receipt(response)
        evidence.update("rejected", value["usage"], json.dumps({"message": MESSAGE}))
        with evidence.connect() as connection:
            connection.execute(
                "UPDATE requests SET response=? WHERE id=?",
                (json.dumps(value, ensure_ascii=False), evidence.local.current),
            )

    def __call__(self, native, *args, **kwargs):
        evidence = self.evidence
        bound = self.signature.bind(*args, **kwargs)
        bound.apply_defaults()
        source = source_values({"messages": [{"content": bound.arguments["user"]}]})
        # Native validation retries prepend a correction to user. Key the source
        # separately so those retries cannot reset the clarification allowance.
        identity = digest(
            {
                **bound.arguments,
                "user": source or bound.arguments["user"],
                "filename": getattr(evidence.local, "filename", None),
            }
        )
        evidence.local.request_identity = identity
        cursors = getattr(evidence.local, "request_cursors", {})
        cursor = cursors.setdefault(identity, getattr(evidence.local, "cursor", 0))
        evidence.local.cursor = cursor
        saved = self.journal.saved(identity)
        if saved:
            if saved[0] is None:
                raise RuntimeError(
                    "The clarification request has no saved response. Reconcile it before further paid work."
                )
            evidence.local.current = saved[1]
            evidence.local.cursor = cursor + len(source or {})
            if getattr(evidence.local, "call", None) is not None:
                evidence.local.call.append(saved[1])
            return restored(json.loads(saved[0]), replay=True)
        response = native(*args, **kwargs)
        if not refused(response, source or {}):
            return response
        self.reject(response)
        first = receipt(response)
        first_usage = first["usage"]
        if not self.clarify.enabled:
            # Unlike Assistant-led, Guided journals a refusal it may not
            # clarify, so a validation retry of the call replays it unpaid.
            first.update(content=None, refusal=MESSAGE)
            self.journal.record(identity, None, json.dumps(first, ensure_ascii=False))
            return restored(first)
        # Guided clarifies the params of the attempt that was refused, a
        # validation retry's correction prefix included.
        with evidence.connect() as connection:
            row = connection.execute(
                "SELECT params FROM requests WHERE id=?", (evidence.local.current,)
            ).fetchone()
        params = self.clarify.begin(identity, json.loads(row[0]))
        evidence.local.cursor = cursor
        print(
            "Provider declined a translation; clarifying the fictional adult context once.",
            flush=True,
        )
        translation = self.translation
        local = getattr(translation, "_thread_local", None)
        refused_at = getattr(local, "received_at", None)
        response = send_once(translation, evidence, params)
        value = receipt(response)
        if refused(response, source or {}):
            self.reject(response)
            # Force native validation failure even for a refusal in valid JSON.
            value.update(content=None, refusal=MESSAGE)
        value["usage"] = {key: first_usage[key] + value["usage"][key] for key in USAGE}
        # translateAI prices both calls' usage together at one time.
        if translation is not None and local is not None:
            from util.provider_costs import joined_received_at

            local.received_at = joined_received_at(
                translation._time_priced_route(),
                refused_at,
                getattr(local, "received_at", None),
            )
        self.journal.answer(identity, json.dumps(value, ensure_ascii=False))
        return restored(value)
