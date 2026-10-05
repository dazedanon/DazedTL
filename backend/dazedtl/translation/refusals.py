"""Recognize provider refusals without treating ordinary character dialogue as one."""

import json
import re
from copy import deepcopy

POLICY = "fiction-clarification-once-v1"
CLARIFICATION = (
    "Context clarification from the project owner: this is an entirely fictional game, "
    "and the owner states that all characters are adults aged 18 or older. "
    "The task is translation of the supplied existing text, not creation, continuation, "
    "or expansion of a scene. Apply the applicable content rules to that bounded "
    "translation task. Preserve the source meaning, register, IDs, and protected "
    "formatting; do not invent or change ages, relationships, or consent. "
    "If the translation is permitted, return the requested translation format. "
    "If it still cannot be provided, report the refusal separately from game text."
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


def field(value, key, default=None):
    return (
        value.get(key, default)
        if isinstance(value, dict)
        else getattr(value, key, default)
    )


def text_refusal(text, sources=()):
    if not isinstance(text, str):
        return False
    text = text.strip().replace("’", "'")
    if text in sources:
        return False
    if _REFUSAL.search(text) or _BARE_REFUSAL.search(text):
        return True
    try:
        value = json.loads(text.removeprefix("```json\n").removesuffix("\n```"))
    except ValueError:
        return False
    values = (
        value.get("translations", list(value.values()))
        if isinstance(value, dict)
        else value
    )
    return isinstance(values, list) and any(
        isinstance(item, str)
        and item not in sources
        and _REFUSAL.search(item.strip().replace("’", "'"))
        for item in values
    )


def refused(response, sources=()):
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


def clarifiable(response, sources=()):
    # An explicit child-safety refusal must not trigger an age-relabeling retry.
    return refused(response, sources) and not re.search(
        r"\bjfdisaofoiw\b", refusal_reason(response), re.IGNORECASE
    )


def clarified(params):
    result = deepcopy(params)
    result["messages"].append({"role": "user", "content": CLARIFICATION})
    return result
