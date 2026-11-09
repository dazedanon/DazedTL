"""PLaMo 3 Translate's request format, for both methods' API runs.

PLaMo 3 Translate (pfnet/plamo-3-translate-*) is a translation model, not an
instruction follower: its chat template (the GGUF's tokenizer.chat_template,
which LM Studio and llama.cpp render) takes optional leading system messages,
then strictly alternating user and assistant messages ending with a user
message, and refuses tools, empty text and its own ``<|plamo:`` tokens. A
system message whose first line is ``[plamo-translate]`` carries settings
(``target_lang=``, ``source_lang=``, ``glossary=SOURCE => TARGET``) up to a
``---`` line; the rest of the system text is passive reference context. The
model translates the last user message and nothing else, so a run on it sends
no instructions, JSON or schema.

A request is a *document*: the lines of one logical request with the run's
languages, the matched glossary and the preceding scene. ``send`` translates
its lines one after another, each with the earlier source and translation
pairs, and answers ``{key: translation}`` as JSON, so each method's reply
parser and validation read it as they read any provider's. A run freezes the
format (``POLICY``) when its model is named PLaMo 3 Translate (``named``).
"""

import json
import re

from dazedtl.translation.refusals import POLICY as REFUSAL_POLICY

POLICY = "plamo-translate-v1"
# Earlier source and translation pairs each line is sent with.
PAIRS = 10
# The most a line's reply may take; a line of game text needs far fewer.
LINE_TOKENS = 1024
_NAMED = re.compile(r"(?:^|/)plamo-3-translate(?:[-_.@:]|$)")
_RESERVED = "<|plamo:"


def named(model):
    """Whether the model ID *model* names PLaMo 3 Translate, such as
    plamo-3-translate-8b or pfnet/plamo-3-translate-0.8b."""
    return bool(_NAMED.search(str(model or "").strip().lower()))


def policies(protocol, model):
    """The request policies a run on *model* freezes: PLaMo's format for a
    PLaMo 3 Translate model on an OpenAI-protocol connection, which can't
    follow the clarification a refusal retry sends, and the refusal retry
    for every other model."""
    if protocol == "openai" and named(model):
        return {"requestFormat": POLICY}
    return {"refusalRetry": REFUSAL_POLICY}


def code(language):
    """PLaMo's code for *language*: its lowercase BCP 47 language and
    script, such as en, ja or zh-hans, without a region, which PLaMo's
    template refuses."""
    from dazedtl.languages import tag

    value = tag(language)
    if not value:
        raise ValueError(f"PLaMo 3 Translate has no language code for {language}.")
    parts = value.lower().split("-")
    if len(parts) > 1 and len(parts[1]) == 4 and parts[1].isalpha():
        return f"{parts[0]}-{parts[1]}"
    return parts[0]


def _text(value):
    """Whether *value* is text PLaMo's template takes: not blank by its
    whitespace rule and free of its reserved tokens."""
    return (
        isinstance(value, str)
        and bool(value.strip(" \t\r\n"))
        and _RESERVED not in value
    )


def _setting(value):
    """Whether *value* fits on one ``glossary=`` settings line."""
    return (
        _text(value) and "\n" not in value and "\r" not in value and "=>" not in value
    )


def glossary(vocab_text):
    """The approved terms in a request's matched glossary text, as
    ``[source, target]`` pairs, each source alias its own pair. The SFX
    reference that may follow it holds suggestions, not approved terms."""
    from util.prompt_pair import SFX_HEADING
    from util.translation import parseVocabWithCategories
    from util.vocab import split_vocab_source_aliases

    text = str(vocab_text or "").split(SFX_HEADING, 1)[0]
    pairs = []
    for term, _line, _category in parseVocabWithCategories(text):
        if not isinstance(term, tuple):
            continue
        source, target = (str(item).strip() for item in term)
        if not _setting(target):
            continue
        for alias in split_vocab_source_aliases(source) or [source]:
            alias = alias.strip()
            if _setting(alias) and [alias, target] not in pairs:
                pairs.append([alias, target])
    return pairs


def _context(context, delivered):
    """The preceding scene as ``[source, translation or None]`` pairs: its
    source lines, each with the translation already delivered for it when
    *delivered* lines up with them."""
    from util.translation import _context_items

    sources = (
        list(context) if isinstance(context, (list, tuple)) else _context_items(context)
    )
    english = (
        list(delivered)
        if isinstance(delivered, (list, tuple)) and len(delivered) == len(sources)
        else [None] * len(sources)
    )
    pairs = []
    for source, translation in zip(sources, english, strict=True):
        if not _text(source):
            continue
        pairs.append([source, translation if _text(translation) else None])
    return pairs


def document(
    lines,
    *,
    model,
    source,
    target,
    vocab_text="",
    context=(),
    delivered=None,
    allowance=None,
):
    """One logical request in PLaMo's format: *lines* by reply key, the
    run's *source* and *target* languages, the approved terms of the matched
    glossary, the preceding *context* with the *delivered* translation of
    it, and the run's output allowance. It is plain JSON, which a run's
    ledger records and Inspect shows."""
    lines = {str(key): value for key, value in dict(lines).items()}
    for key, text in lines.items():
        if not _text(text):
            raise ValueError(
                f"PLaMo 3 Translate can't take line {key}: it is empty or holds the model's reserved tokens."
            )
    return {
        "format": POLICY,
        "model": str(model),
        "temperature": 0,
        "allowance": allowance,
        "languages": [code(source), code(target)],
        "glossary": glossary(vocab_text),
        "context": _context(context, delivered),
        "lines": lines,
    }


def is_document(params):
    """Whether *params* is a PLaMo document rather than a request body."""
    return (
        isinstance(params, dict)
        and params.get("format") == POLICY
        and "lines" in params
    )


def sources(params):
    """A document's lines by reply key; None for any other request."""
    return dict(params["lines"]) if is_document(params) else None


def with_delivered(params, english):
    """*params* with the translation already delivered for the last lines
    of its preceding context, *english*, so those lines go as pairs."""
    context = [list(pair) for pair in params["context"]]
    english = list(english)[-len(context) :] if context else []
    start = len(context) - len(english)
    for offset, text in enumerate(english):
        if _text(text):
            context[start + offset][1] = text
    return {**params, "context": context}


def _limit(line, allowance):
    from util.translation import approximate_tokens

    limit = min(LINE_TOKENS, max(128, 4 * approximate_tokens(line)))
    return min(limit, allowance) if allowance else limit


def call(params, line, earlier=()):
    """The chat request that translates *line* of the document *params*,
    after this request's *earlier* lines and their translations."""
    source, target = params["languages"]
    settings = ["[plamo-translate]", f"target_lang={target}", f"source_lang={source}"]
    settings += [
        f"glossary={term} => {translation}"
        for term, translation in params["glossary"]
        if term in line
    ]
    unpaired = [text for text, translation in params["context"] if translation is None]
    if unpaired:
        settings += ["---", "\n".join(unpaired)]
    paired = [pair for pair in params["context"] if pair[1] is not None]
    messages = [{"role": "system", "content": "\n".join(settings)}]
    for text, translation in (paired + [list(pair) for pair in earlier])[-PAIRS:]:
        messages += [
            {"role": "user", "content": text},
            {"role": "assistant", "content": translation},
        ]
    messages.append({"role": "user", "content": line})
    return {
        "model": params["model"],
        "messages": messages,
        "temperature": params["temperature"],
        "max_tokens": _limit(line, params.get("allowance")),
    }


def send(params, create):
    """Translates the document *params* with the chat client's *create*, one
    line after another, and answers as an OpenAI-protocol Live result: the
    translations as a JSON object by reply key in ``text``, with every call's
    usage added up. A blank reply stays blank, for the
    run's validation to reject, and never becomes an earlier pair, which the
    template would refuse. The first error is raised as the client raised
    it, so the run reads its status as any request's."""
    replies, earlier = {}, []
    prompt = completion = 0
    for key, line in params["lines"].items():
        response = create(**call(params, line, earlier))
        message = response.choices[0].message if response.choices else None
        text = getattr(message, "content", None) or ""
        usage = getattr(response, "usage", None)
        prompt += int(getattr(usage, "prompt_tokens", 0) or 0)
        completion += int(getattr(usage, "completion_tokens", 0) or 0)
        replies[key] = text
        if _text(text):
            earlier.append([line, text])
    # The shape of any OpenAI-protocol Live result (batch_providers
    # openai_usage); a local server caches and thinks nothing it bills.
    return {
        "text": json.dumps(replies, ensure_ascii=False),
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "thinking_tokens": 0,
    }


def sent_text(params):
    """The text of every call a document sends, each line's source standing
    in for its translation, which estimates count."""
    earlier, calls = [], []
    for line in params["lines"].values():
        calls.append(
            json.dumps(call(params, line, earlier)["messages"], ensure_ascii=False)
        )
        earlier.append([line, line])
    return "\n".join(calls)


def guided_request(arguments, allowance=None):
    """The document for a Guided request, from the arguments its engine
    builder (buildOpenAIRequest) was called with: the lines of its JSON
    payload, read past any retry note before it, which PLaMo would translate,
    its preceding source and the English already delivered for it, and its
    matched glossary. Its instructions stay out; PLaMo can't follow them."""
    from util.languages import active_source, active_target
    from util.translation import CONTEXT_SOURCE, _request_context_parts

    from .process_view import source_values

    lines = source_values({"messages": [{"content": arguments["user"]}]})
    if not lines:
        raise ValueError("This PLaMo 3 Translate request holds no lines to translate.")
    context, _instructions = _request_context_parts(
        arguments.get("history"), arguments.get("context_kind", CONTEXT_SOURCE)
    )
    return document(
        lines,
        model=arguments["model"],
        source=active_source(),
        target=active_target(),
        vocab_text=arguments.get("vocab_text", ""),
        context=context,
        delivered=arguments.get("delivered_context"),
        allowance=allowance,
    )


LAYER = "plamo-format"


def configure(translation, policy):
    """Layers a Guided worker's sending and estimating over the engine for a
    run frozen with PLaMo's format, *policy*; None takes the layers out. The
    run's builder (request_parameters.configure_builders) makes each request
    a document, which these send and count; other requests pass through."""
    if policy is None:
        translation.sendChatCompletion.remove(LAYER)
        translation.requestTokens.remove(LAYER)
        return
    if policy != POLICY:
        raise ValueError("This run's saved request format is unsupported.")

    def sending(native, params):
        if not is_document(params):
            return native(params)
        result = send(params, translation.openai.chat.completions.create)
        return translation._AnthropicCompat(
            result["text"], result["prompt_tokens"], result["completion_tokens"], 0, 0
        )

    def counting(native, system, vocab_text, user, history, instructions):
        params = guided_request(
            {"user": user, "history": history, "vocab_text": vocab_text, "model": ""}
        )
        return [
            translation.approximate_tokens(sent_text(params)),
            sum(
                translation.output_allowance(translation.approximate_tokens(line))
                for line in params["lines"].values()
            ),
        ]

    translation.sendChatCompletion.layer(LAYER, sending)
    translation.requestTokens.layer(LAYER, counting)
