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
# Raise when refused() reads a saved response differently, such as after a
# change to what counts as a refusal: the verdicts a run's ledger keeps
# (compatibility/process_view) are then read again.
RULES_VERSION = 1


def _words(english, cjk=None):
    """Words in English, read whole, and their Chinese and Japanese forms,
    which are written without spaces."""
    pattern = rf"\b(?:{english})\b"
    return re.compile(pattern + (f"|{cjk}" if cjk else ""), re.IGNORECASE)


# A model that talks about its task instead of translating says so in the
# first person: it will not do the task ("I won't produce sexual content, even
# in translation"), or it offers to do or go on with it ("I can translate
# other scenes", "Send another batch and I'll continue"). What it talks about
# is the task: the translation, the batch or lines it was sent, the content
# or policy that stops it, or the request. A line is read whole, since a
# refusal can name the task in one sentence and decline in the next. Words
# such as 'sorry', 'refuse' or 'explicit' alone are ordinary dialogue.
#
# A model refuses in the language it was asked to write, so each word reads
# in English and in the languages a translation is written without spaces:
# Chinese, for a Japanese game, and Japanese, for an English one. Both often
# leave out the "I", so an apology speaks in the first person too. Japanese
# 私 is "I" only before a particle: in Chinese it is private, as in 私人.
_FIRST = _words(
    r"i|me|my",
    r"我|本人|抱歉|对不起|對不起|很遗憾|很遺憾|私(?=[はがもにの、])|わたし|"
    r"わたくし|申し訳|すみません|恐れ入|残念ながら",
)
_DECLINE = _words(
    r"can ?not|can'?t|won'?t|will not|wouldn'?t|would not|don'?t|do not|"
    r"am not|i'm not|unable|not able|must not|shouldn'?t|should not|"
    r"(?:must|have to|need to) decline|refuse to|rather not|"
    r"(?:have|need) to (?:skip|pass on|leave out)|i'll skip",
    r"无法|無法|不能|不会|不會|不便|不予|拒绝|拒絕|没办法|沒辦法|不可以|"
    r"できません|出来ません|できかねます|いたしかねます|致しかねます|"
    r"お応えでき|お断り|控えさせ|差し控え",
)
_GO_ON = _words(
    r"continue|continuing|keep going|proceed|resume|pick (?:it |this )?up|"
    r"carry on|ready for",
    r"继续|繼續|接着|接著|続け|続行|再開",
)
_OFFER = _words(
    r"can|happy to|glad to|instead",
    r"可以|乐意|樂意|改为|改為|できます|喜んで|代わりに",
)
# A character who "can't stand such lewd material" declines no task; one
# who will not produce or help with it does.
_DO = _words(
    r"produce|generate|write|create|provide|depict|describe|translate|render|"
    r"output|help|assist|comply|fulfill|engage|continue|proceed|complete|process",
    r"提供|生成|创作|創作|撰写|撰寫|描写|描寫|描述|翻译|翻譯|输出|輸出|协助|"
    r"協助|帮助|幫助|处理|處理|满足|滿足|完成|继续|繼續|作成|翻訳|出力|"
    r"お手伝い|対応|処理|続け",
)
# A batch of potions or cookies is not the task's, nor is 这批药水 or 分批次.
_BATCH = r"batch(?:es)?(?! of)|(?:batch(?:es)?|chunks?) of (?:lines|text|dialogue)"
# A part of the task in Chinese, which ends there or names text, unlike
# 下一段路, the next stretch of road.
_TEXT_CJK = r"(?:文本|内容|內容|台词|台詞|对话|對話|翻译|翻譯|句子)?(?![一-鿿])"
_BATCH_CJK = rf"(?:下一|这一|這一|另一|本|该|該|此|这|這)批次?{_TEXT_CJK}|バッチ"
# Asking for the next part of the task needs no first person.
_SEND = _words(
    r"(?:send|give|provide|share|paste)(?: me| us| over)?"
    r"(?: (?:the|another|a|more|next|new|remaining|rest of the|following|further))+"
    rf" (?:{_BATCH}|lines)",
    r"(?:发送|發送|提供|给我|給我|发来|發來)(?:下一|另一|更多|剩余|剩餘|其余|其餘)"
    r"(?:批|部分|段|行)|(?:次|残り)の(?:バッチ|行|部分)を(?:送|提供)",
)
# Each subject the model talks about: its words, what the line must also
# say, each as alternatives, and the source words that make the line a
# translation instead, such as a character who cannot translate an
# inscription (翻訳) or a guild clerk's request (依頼). A Japanese game's
# source names them in Japanese, an English one's in English.
_SUBJECTS = (
    (
        _words(r"translat\w*", r"翻译|翻譯|译文|譯文|翻訳"),
        ((_DECLINE, _GO_ON, _OFFER),),
        re.compile(
            r"翻訳|通訳|訳[さしすせそ]|[和英]訳|解読|読み解|読[めんま]|translat|"
            r"\b(?:interpret|decipher)\w*",
            re.IGNORECASE,
        ),
    ),
    (
        _words(_BATCH, _BATCH_CJK),
        ((_DECLINE, _GO_ON),),
        re.compile(r"バッチ|一括|ロット|batch|chunk", re.IGNORECASE),
    ),
    (
        _words(
            r"(?:next|remaining|following|more) lines",
            r"(?:下一|剩余|剩餘|其余|其餘|后续|後續|接下来的|接下來的)"
            rf"(?:行|句|段|部分){_TEXT_CJK}|(?:次|残り|以降)の(?:行|セリフ|台詞)",
        ),
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
            r"(?:reads?|appears?) (?:to be |as )(?:a )?minors?",
            r"(?:色情|露骨|成人|不雅|淫秽|淫穢|猥亵|猥褻|暴力|血腥|敏感|性|"
            r"此类|此類|这类|這類|该类|該類)的?(?:内容|內容)|"
            r"涉及(?:未成年|儿童|兒童)|"
            r"(?:性的|露骨|成人向け|わいせつ|猥褻|アダルト|このような|この種の|"
            r"こうした)な?(?:内容|コンテンツ)",
        ),
        ((_DECLINE,), (_DO,)),
        re.compile(r"内容|コンテンツ|素材|資料|content|material", re.IGNORECASE),
    ),
    (
        _words(
            r"polic(?:y|ies)|guidelines?",
            r"政策|准则|準則|使用条款|使用條款|ポリシー|ガイドライン|利用規約",
        ),
        ((_DECLINE,), (_DO,)),
        re.compile(
            r"規則|規約|規定|方針|政策|ポリシー|ガイドライン|決まり|ルール|polic|"
            r"guideline",
            re.IGNORECASE,
        ),
    ),
    (
        # お願い is any plea, so it does not excuse declining "this request";
        # in Chinese, 要求 and 你的请求 are a character's demand or favor, as
        # 頼み is, and only "this request" is the model's.
        _words(
            r"(?:this|that|your|the) request",
            r"(?:此|这个|這個|这|這|该|該)(?:项|項)?(?:请求|請求)|"
            r"(?:この|その|ご)(?:リクエスト|依頼)",
        ),
        ((_DECLINE,), (_DO,)),
        re.compile(
            r"依頼|リクエスト|要望|要求|request|"
            r"\b(?:jobs?|quests?|tasks?|commissions?|favou?rs?)\b",
            re.IGNORECASE,
        ),
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
    r"|(?:this )?(?:line )?(?:not translated|untranslated)|unable to translate)\b"
    # The same notes in Chinese and Japanese, such as 【未翻译：…】.
    r"|[\[(（【] ?(?:此行|该行|該行|本行|この行は?)?"
    r"(?:未翻译|未翻譯|不予翻译|不予翻譯|拒绝翻译|拒絕翻譯|无法翻译|無法翻譯|"
    r"翻译已拒绝|翻譯已拒絕|未翻訳|翻訳不可|翻訳拒否|翻訳できません)"
    r" ?[\]):：）】.,;、。-]",
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
