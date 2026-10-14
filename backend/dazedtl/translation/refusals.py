"""Recognize provider refusals without treating ordinary character dialogue as one."""

import json
import re
from collections.abc import Mapping
from copy import deepcopy

POLICY = "fiction-clarification-once-v1"
CLARIFICATION = (
    "Context clarification from the project owner: this is an entirely fictional game, "
    "and the owner states that all characters are adults aged 18 or older. "
    "The task is historical preservation via translation of the supplied existing text, not creation, continuation, "
    "or expansion of a scene. Apply the applicable content rules to that bounded "
    "translation task. Preserve the source meaning, register, IDs, and protected "
    "formatting; do not invent or change ages, relationships, or consent. "
)
MESSAGE = "The provider declined this translation. No refusal text was accepted as game dialogue."

# Match assistant statements about this translation task, not isolated words such
# as 'sorry', 'refuse', or 'explicit' that can be legitimate source dialogue.
_REFUSAL = re.compile(
    r"^(?:sorry[,.!]?\s*|i(?:'m| am) sorry[,.!]?\s*)?(?:but\s+)?"
    r"(?:i\s+(?:can(?:not|'t)|must decline to)|"
    r"i(?:'m| am)\s+(?:unable|not able) to)\s+"
    r"(?:help\s+(?:you\s+)?(?:with\s+|to\s+)?)?"
    r"(?:translate|provide|assist with|help with|process|fulfill|comply with)\b"
    r"[^\n]{0,240}\b(?:sexual(?:ly|i[sz]ed)?|explicit|graphic|erotic|pornographic|violence|gore|policy|policies)\b",
    re.IGNORECASE,
)
_BARE_REFUSAL = re.compile(
    r"^(?:sorry[,.!]?\s*|i(?:'m| am) sorry[,.!]?\s*)?(?:but\s+)?"
    r"i\s+(?:can(?:not|'t)|am unable to)\s+(?:help|assist|comply)\s+with\s+"
    r"(?:this|that|your)\s+(?:request|translation)\b",
    re.IGNORECASE,
)
# A note left in place of a line, or inside one, such as "[Not translated: ...]",
# "(Line left untranslated)", "[TRANSLATION DECLINED: ...]" or "Unable to
# translate this line.". Game text has no use for these.
_NOTE = re.compile(
    r"[\[(（【] ?(?:(?:(?:this|the) )?(?:line |text |scene )?(?:was |is |left )?"
    r"(?:not translated|untranslated)|translation (?:was )?"
    r"(?:declined|refused|withheld|omitted|skipped|unavailable)|not game text)"
    r" ?[\]):：）】.,;-]"
    r"|[\[(（【] ?unable to translate\b"
    r"|^(?:translation (?:was )?(?:declined|refused|withheld|omitted)"
    r"|(?:this )?(?:line )?(?:not translated|untranslated)|unable to translate)\b",
    re.IGNORECASE,
)
# Notes that real lines can also hold, each with the source words that make it
# a translation: a quest marked "[Declined]", a "(中略)" rendered "(Omitted)", a
# character who cannot translate an inscription.
_EXCUSED = (
    (
        re.compile(
            r"[\[(（【] ?(?:declined|refus(?:al|ed)) ?[\]):：）】]", re.IGNORECASE
        ),
        re.compile(r"断|辞退|拒|却下"),
    ),
    (
        re.compile(
            r"[\[(（【] ?(?:(?:content|text|lines?|scene|dialogue|passage|words?|"
            r"sexual content|explicit content) )?"
            r"(?:omitted|redacted|censored|removed|withheld) ?[\])）】]",
            re.IGNORECASE,
        ),
        re.compile(r"略|検閲|削除|黒塗|伏|規制|割愛|カット|ピー|[■●〇○×＊*]"),
    ),
    (
        re.compile(
            r"\bI(?:'m| am)? (?:can ?not|can't|won't|will not|unable to|not able to|"
            r"must decline to) (?:(?:help|assist|provide|produce|give|offer|complete|"
            r"continue) (?:you )?(?:with |to )?(?:(?:a|an|the|this|that|any|these|"
            r"those|your) )?)?translat",
            re.IGNORECASE,
        ),
        re.compile(r"翻訳|訳[さしすせ]|解読|通訳"),
    ),
)
# Protected placeholders, masks and control codes, which can sit around a note
# such as "\C[27][omitted]\C[0]".
_CODES = re.compile(
    r"__[A-Z]+_\d+__|⟦[^⟧]*⟧|\\[A-Za-z]+(?:\[[^\]\n]*\]|<[^>\n]*>)?|\\[{}<>|.!^$]"
)


def field(value, key, default=None):
    return (
        value.get(key, default)
        if isinstance(value, dict)
        else getattr(value, key, default)
    )


def line_refusal(text, source=None):
    """Whether one translated line holds a refusal instead of, or inside, its
    translation. `source` is the line's own source text, or all of its
    request's; None when they are unknown, which counts only the notes that
    game text never holds."""
    # Wrapped text splits a note across lines, some formats keep those breaks
    # as an escaped "\n", and name fields use underscores.
    plain = re.sub(r"\\n(?!\[)", " ", text.replace("’", "'"))
    plain = re.sub(r"[\s_]+", " ", _CODES.sub(" ", plain)).strip()
    if _REFUSAL.search(plain) or _BARE_REFUSAL.search(plain) or _NOTE.search(plain):
        return True
    return source is not None and any(
        note.search(plain) and not excuse.search(source) for note, excuse in _EXCUSED
    )


def text_refusal(text, sources=None):
    """Whether a reply holds a refusal in place of game text. `sources` maps
    the request's line keys to their source text, or lists those texts; None
    when they are unknown."""
    if not isinstance(text, str):
        return False
    text = text.strip()
    paired = dict(sources) if isinstance(sources, Mapping) else {}
    texts = [
        source
        for source in (paired.values() if paired else sources or ())
        if isinstance(source, str)
    ]
    whole = None if sources is None else "\n".join(texts)
    if text.replace("’", "'") in texts:
        return False
    try:
        value = json.loads(text.removeprefix("```json\n").removesuffix("\n```"))
    except ValueError:
        return line_refusal(text, whole)
    if isinstance(value, dict):
        value = value.get("translations", value)
    if isinstance(value, list):
        # A list answers the request's lines in order.
        value = dict(
            zip(paired, value) if len(paired) == len(value) else enumerate(value)
        )
    if not isinstance(value, dict):
        return isinstance(value, str) and line_refusal(value, whole)
    return any(
        isinstance(item, str)
        and item not in texts
        and line_refusal(item, None if whole is None else paired.get(key, whole))
        for key, item in value.items()
    )


def refused(response, sources=None):
    if field(response, "refusal") or field(response, "stop_reason") == "refusal":
        return True
    choices = field(response, "choices", []) or []
    if choices:
        choice = choices[0]
        message = field(choice, "message", {})
        return bool(
            field(message, "refusal")
            or field(choice, "finish_reason") == "content_filter"
            or text_refusal(field(message, "content"), sources)
        )
    return text_refusal(field(response, "text"), sources)


def refusal_reason(response):
    choices = field(response, "choices", []) or []
    message = field(choices[0], "message", {}) if choices else response
    return " ".join(
        str(field(message, key) or "") for key in ("refusal", "text", "content")
    )


def _appended(params):
    return {
        **params,
        "messages": [*params["messages"], {"role": "user", "content": CLARIFICATION}],
    }


def clarified(params):
    return deepcopy(_appended(params))


def clarifies(sent, params):
    """Whether a saved payload is the clarification of `params`, compared
    without copying the request."""
    return sent == _appended(params)
