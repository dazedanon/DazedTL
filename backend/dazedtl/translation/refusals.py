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


def _words(pattern):
    return re.compile(rf"\b(?:{pattern})\b", re.IGNORECASE)


# A model that talks about its task instead of translating says so in the
# first person: it will not do the task ("I won't produce sexual content, even
# in translation"), or it offers to do or go on with it ("I can translate
# other scenes", "Send another batch and I'll continue"). What it talks about
# is the task: the translation, the batch or lines it was sent, the content
# or policy that stops it, or the request. A line is read whole, since a
# refusal can name the task in one sentence and decline in the next. Words
# such as 'sorry', 'refuse' or 'explicit' alone are ordinary dialogue.
_FIRST = _words(r"i|me|my")
_DECLINE = _words(
    r"can ?not|can'?t|won'?t|will not|wouldn'?t|would not|don'?t|do not|"
    r"am not|i'm not|unable|not able|must not|shouldn'?t|should not|"
    r"(?:must|have to|need to) decline|refuse to|rather not|"
    r"(?:have|need) to (?:skip|pass on|leave out)|i'll skip"
)
_GO_ON = _words(
    r"continue|continuing|keep going|proceed|resume|pick (?:it |this )?up|"
    r"carry on|ready for"
)
_OFFER = _words(r"can|happy to|glad to|instead")
# A character who "can't stand such lewd material" declines no task; one
# who will not produce or help with it does.
_DO = _words(
    r"produce|generate|write|create|provide|depict|describe|translate|render|"
    r"output|help|assist|comply|fulfill|engage|continue|proceed|complete|process"
)
# A batch of potions or cookies is not the task's.
_BATCH = r"batch(?:es)?(?! of)|(?:batch(?:es)?|chunks?) of (?:lines|text|dialogue)"
# Asking for the next part of the task needs no first person.
_SEND = _words(
    r"(?:send|give|provide|share|paste)(?: me| us| over)?"
    r"(?: (?:the|another|a|more|next|new|remaining|rest of the|following|further))+"
    rf" (?:{_BATCH}|lines)"
)
# Each subject the model talks about: its words, what the line must also
# say, each as alternatives, and the source words that make the line a
# translation instead, such as a character who cannot translate an
# inscription (翻訳) or a guild clerk's request (依頼).
_SUBJECTS = (
    (
        _words(r"translat\w*"),
        ((_DECLINE, _GO_ON, _OFFER),),
        re.compile(
            r"翻訳|通訳|訳[さしすせそ]|[和英]訳|解読|読み解|読[めんま]|translat",
            re.IGNORECASE,
        ),
    ),
    (
        _words(_BATCH),
        ((_DECLINE, _GO_ON),),
        re.compile(r"バッチ|一括|ロット|batch|chunk", re.IGNORECASE),
    ),
    (
        _words(r"(?:next|remaining|following|more) lines"),
        ((_GO_ON,),),
        re.compile(r"台詞|セリフ|せりふ|\blines?\b", re.IGNORECASE),
    ),
    (
        _words(
            r"(?:sexual(?:ly|i[sz]ed)?|explicit|graphic|erotic|pornographic|adult|"
            r"nsfw|lewd|obscene|such|this kind of|that kind of|this type of)"
            r"\s+(?:\w+\s+)?(?:content|material)|"
            r"(?:graphic|sexual) violence|gore|underage|"
            r"(?:involving|depicting|sexuali[sz]ing) (?:a |the )?(?:minor|child|children)|"
            r"(?:reads?|appears?) (?:to be |as )(?:a )?minors?"
        ),
        ((_DECLINE,), (_DO,)),
        re.compile(r"内容|コンテンツ|素材|資料|content|material", re.IGNORECASE),
    ),
    (
        _words(r"polic(?:y|ies)|guidelines?"),
        ((_DECLINE,), (_DO,)),
        re.compile(
            r"規則|規約|規定|方針|ポリシー|ガイドライン|決まり|ルール|polic|guideline",
            re.IGNORECASE,
        ),
    ),
    (
        # お願い is any plea, so it does not excuse declining "this request".
        _words(r"(?:this|that|your|the) request"),
        ((_DECLINE,), (_DO,)),
        re.compile(r"依頼|リクエスト|要望|要求|request", re.IGNORECASE),
    ),
)
# Any subject's words: most lines hold none and skip the rest.
_SUBJECT = re.compile(
    "|".join(words.pattern for words, _, _ in _SUBJECTS), re.IGNORECASE
)


def _task_talk(plain, source):
    """Whether `plain` is the model talking about its task, about a subject
    `source` does not name; an unknown source names none."""
    if not _SUBJECT.search(plain):
        return False
    asks = bool(_SEND.search(plain))
    if not (asks or _FIRST.search(plain)):
        return False
    return any(
        words.search(plain)
        and (asks or all(any(word.search(plain) for word in need) for need in needs))
        and not (source and excuse.search(source))
        for words, needs, excuse in _SUBJECTS
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
            r"[\[(（【] ?(?:declined|refus(?:al|ed)) ?[\]):：）】]|^(?:declined|refused)\.?$",
            re.IGNORECASE,
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
    request's; None when they are unknown, which counts the model's talk
    about its task and the notes that game text never holds."""
    # Wrapped text splits a note across lines, some formats keep those breaks
    # as an escaped "\n", and name fields use underscores.
    plain = re.sub(r"\\n(?!\[)", " ", text.replace("’", "'"))
    plain = re.sub(r"[\s_]+", " ", _CODES.sub(" ", plain)).strip()
    if _NOTE.search(plain) or _task_talk(plain, source):
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
