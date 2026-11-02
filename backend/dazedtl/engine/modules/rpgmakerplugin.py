# Libraries
import json
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import lru_cache
import os
import re
import util.dazedwrap as dazedwrap
import threading
import time
import traceback
import tiktoken
from pathlib import Path
from colorama import Fore
from dotenv import load_dotenv
from retry import retry
from tqdm import tqdm
from util.languages import source_pattern
from util.runtime_text import CONTROL_CODE
from util.sent_lines import SentLines
from util.translation import TranslationConfig, translateAI as sharedtranslateAI, getPricingConfig, calculateCost, run_stop_errors
from util.translation_task import fail_on_parser_error, module_receipt, write_output

# Globals
MODEL = os.getenv("model")
TIMEOUT = int(os.getenv("timeout"))
LANGUAGE = os.getenv("language").capitalize()
from util.paths import PROMPT_PATH, read_active_glossary

PROMPT = PROMPT_PATH.read_text(encoding="utf-8")
VOCAB = read_active_glossary()
LOCK = threading.Lock()
WIDTH = int(os.getenv("width"))
LISTWIDTH = int(os.getenv("listWidth"))
NOTEWIDTH = 70
MAXHISTORY = 10
ESTIMATE = ""
TOKENS = [0, 0]
NAMES = False  # Output a list of all the character names found
BRFLAG = False  # If the game uses <br> instead
FIXTEXTWRAP = True  # Overwrites textwrap
IGNORETLTEXT = False  # Ignores all translated text.
MISMATCH = []  # Lists files that throw a mismatch error (Length of GPT list response is wrong)
FILENAME = None

# tqdm Globals
BAR_FORMAT = "{l_bar}{bar:10}{r_bar}{bar:-10b}"
POSITION = 0
LEAVE = False
PBAR = None

# Regex - Need to change this if you want to translate from/to other languages. Default is Japanese Regex
LANGREGEX = source_pattern()

# Get pricing configuration based on the model
PRICING_CONFIG = getPricingConfig(MODEL)
INPUTAPICOST = PRICING_CONFIG["inputAPICost"]
OUTPUTAPICOST = PRICING_CONFIG["outputAPICost"]
BATCHSIZE = PRICING_CONFIG["batchSize"]
FREQUENCY_PENALTY = PRICING_CONFIG["frequencyPenalty"]

# Initialize Translation Config
TRANSLATION_CONFIG = TranslationConfig(
    model=MODEL,
    language=LANGUAGE,
    prompt=PROMPT,
    vocab=VOCAB,
    langRegex=LANGREGEX,
    batchSize=BATCHSIZE,
    maxHistory=MAXHISTORY,
    estimateMode=False  # Will be set dynamically based on ESTIMATE
)
LEAVE = False

def handlePlugin(filename, estimate):
    global ESTIMATE, PBAR, FILENAME
    ESTIMATE = estimate
    FILENAME = filename

    if ESTIMATE:
        start = time.time()
        translatedData = openFiles(filename)
        fail_on_parser_error(translatedData)

        # Print Result
        end = time.time()
        tqdm.write(module_receipt(filename, translatedData[1], end - start, MODEL))
        with LOCK:
            TOKENS[0] += translatedData[1][0]
            TOKENS[1] += translatedData[1][1]

        # Print Total
        totalString = module_receipt("TOTAL", TOKENS, end - start, MODEL)

        # Print any errors on maps
        if len(MISMATCH) > 0:
            return totalString + Fore.RED + f"\nMismatch Errors: {MISMATCH}" + Fore.RESET
        else:
            return totalString

    else:
        start = time.time()
        translatedData = openFiles(filename)
        fail_on_parser_error(translatedData)
        write_output(filename, "".join(translatedData[0]), encoding="utf_8", errors="ignore", newline="\n")

        # Print Result
        end = time.time()
        tqdm.write(module_receipt(filename, translatedData[1], end - start, MODEL))
        with LOCK:
            TOKENS[0] += translatedData[1][0]
            TOKENS[1] += translatedData[1][1]

    return module_receipt("TOTAL", TOKENS, end - start, MODEL)


def openFiles(filename):
    with open("files/" + filename, "r", encoding="utf_8") as readFile:
        translatedData = parsePlugin(readFile, filename)

        # Delete lines marked for deletion
        finalData = []
        for line in translatedData[0]:
            if line != "\\d\n":
                finalData.append(line)
        translatedData[0] = finalData

    return translatedData


def parsePlugin(readFile, filename):
    global PBAR
    totalTokens = [0, 0]

    # Read File into data
    data = readFile.readlines()

    # Create Progress Bar
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE) as pbar:
        pbar.desc = filename
        PBAR = pbar

        try:
            result = translatePlugin(data, pbar, filename)
            totalTokens[0] += result[0]
            totalTokens[1] += result[1]
        except run_stop_errors():
            raise
        except Exception as e:
            traceback.print_exc()
            return [data, totalTokens, e]
    return [data, totalTokens, None]


# A plugin string's escapes. Each level of nesting, the JS string and then
# each JSON.stringify of a parameter, struct, list or note, doubles the
# backslashes before them: a string whose quotes have q backslashes before
# them has q + 1 before each of its own escapes, such as a note's line break
# \n, and twice that, its depth, before a backslash of its text, such as a
# control code's.
#
# An escape is a backslash run and one of:
# - an escaped line break, n except before [ and a number or backslash, or <;
# - an actor name or name box code, \n[1], \n[\v[1]] or \n<Alice>, where a
#   note's line break before [1 or < reads the same, one level shallower;
# - any other control code as game text reads one (runtime_text's
#   CONTROL_CODE), such as \C[2], \I[5], \G or \{, but a lowercase word
#   alone, which can be the string's own escape, such as \r or \u3000.
# A request sends each code with one backslash, and the translation writes
# each back at its source's depth. A line break is read as its source writes
# it: at its codes' depth in a txtSubject, one level shallower in a note.
ESCAPE = re.compile(
    r"(\\+)(?:(n)(?!\[[\d\\]|<)|(?=(n)[\[<])"
    r"|(?![a-z][A-Za-z0-9_]*(?![A-Za-z0-9_\[<]))(?=" + CONTROL_CODE + "))"
)


def stringDepth(quote):
    """The depth of a plugin string whose quotes have the backslashes *quote*
    before them: twice their count and one."""
    return "\\" * (2 * len(quote) + 2)


def escapedNewline(text):
    """The escaped line break a plugin string uses, as its backslashes and n,
    or None."""
    for found in ESCAPE.finditer(text):
        if found.group(2):
            return found.group(0)
    return None


def sent(text, keepLineBreaks=False):
    """A plugin string's text as a request sends it: each code with one
    backslash, and each escaped line break as a space, or as \\n with one
    backslash in a field that keeps its line breaks."""
    lineBreak = "\\n" if keepLineBreaks else " "
    return ESCAPE.sub(lambda found: lineBreak if found.group(2) else "\\", text)


def written(translation, source, depth=None, width=None):
    """A translation as the plugin string *source* it replaces writes it.

    Each code in the translation, at whatever depth the reply writes it,
    takes the depth of the source's codes, or where the source has none,
    *depth*, the string's own (None keeps the reply's); an actor name or
    name box code takes the depth of the source's own. With *width* the
    translation is wrapped to it. Each line break, a raw or an escaped one,
    is written as the source writes one; where it writes none, a wrapped
    string writes a line break escaped as its own, half its depth, and any
    other a space, as a raw line break would end the JS string.
    """
    newline, codes = None, {}
    for found in ESCAPE.finditer(source):
        if found.group(2):
            newline = newline or found.group(0)
        else:
            codes.setdefault(bool(found.group(3)), found.group(1))
    depth = codes.get(False, depth)
    names = codes.get(True, depth)

    def atDepth(found):
        if found.group(2):
            return "\n"
        return (names if found.group(3) else depth) or found.group(1)

    text = ESCAPE.sub(atDepth, translation)
    if width:
        text = dazedwrap.wrapText(text, width=width)
        if newline is None and depth:
            newline = depth[: len(depth) // 2] + "n"
    return text.replace("\n", newline or " ")


# The plugin fields. One walk over the file (fields) records each string the
# module translates once: its kind, its span on its line, its escape depth and
# the text its request sends. The requests are sent from those records and
# each translation is written back to its own span, so the writing pass never
# looks for a field again: it cannot take another field's translation, write
# over the same text elsewhere on the line or find a field the requests left
# out. Text two kinds match belongs to the field the walk reads first, so a
# stat label inside a drawTextEx label is part of that label.
#
# A field is bounded by its own string: one a pattern anchors on runs from
# its opening quote to that string's closing quote (stringEnd), and a label
# inside a string must end inside it (around). A field read only in part of
# the file reads only there: a disp_list region's strings inside the object
# its anchor opens, and a drawTextEx label inside the string that holds the
# call, a plugin setting's script, or on its line where no string does.


@dataclass(frozen=True, eq=False)
class Group:
    """One request: its history label, and whether it sends each text once
    however many fields hold it."""

    history: str
    once: bool = False


def everywhere(line, region):
    return [(0, len(line))]


def inRegion(line, region):
    return region


def drawing(line, region):
    """Where a drawTextEx call's labels are read on *line*: the string
    holding each call, or the whole line for a call outside any string."""
    scopes = set()
    for call in re.finditer("drawTextEx", line):
        strings = around(line, call.start())
        scopes.add(strings[-1][1:] if strings else (0, len(line)))
    return sorted(scopes)


@dataclass(frozen=True, eq=False)
class Kind:
    """A kind of field: how the walk finds it in the spans of a line it reads
    (the span of each field's text and the backslashes it reads its depth
    from), the request it
    joins, the text that request sends, None for a match it leaves, how a
    translation is written, and where on a line it reads, by the line and the
    spans of the disp_list regions on it."""

    find: Callable[[str, list[tuple[int, int]]], Iterator[tuple[int, int, str]]]
    group: Group
    request: Callable[[str], str | None]
    write: Callable[[str, "Field", str], str]
    reads: Callable[[str, list[tuple[int, int]]], list[tuple[int, int]]] = everywhere


@dataclass(frozen=True, eq=False)
class Field:
    """One field: its kind, its line and span there, its text, the
    backslashes before its string's quote or a label's codes, and the text its
    request sends."""

    kind: Kind
    line: int
    start: int
    end: int
    text: str
    quote: str
    request: str


# JavaScript string literals. A label in a drawTextEx call can sit in any
# string of its line, and in a plugin setting's script one string deeper for
# each level, so its translation is written into each string around it.
#
# What can open a string, a comment or a regular expression, and each one's
# text: a string runs to its unescaped quote or the line's end, a regular
# expression to its unescaped slash outside a [class].
JS_TOKEN = re.compile(r"//|/\*|[/'\"`]")
JS_STRING = {
    quote: re.compile(r"(?:[^\\%s]|\\.)*" % quote, re.S) for quote in "'\"`"
}
JS_REGEX = re.compile(r"(?:[^\\/\[\n]|\\.|\[(?:[^\\\]\n]|\\.)*\]?)*/?")
# A slash after one of these, or first on its line, opens a regular
# expression; after anything else it divides.
REGEX_AFTER = set("(,=:[!&|?{};+-*%<>~^")


@lru_cache(maxsize=16)
def literals(text):
    """Each string literal of a line of JavaScript, as the span of its text
    and its quote, in line order; a comment ends the line."""
    found, index = [], 0
    while (token := JS_TOKEN.search(text, index)) is not None:
        mark, index = token.group(), token.end()
        if mark == "//":
            break
        if mark == "/*":
            close = text.find("*/", index)
            if close < 0:
                break
            index = close + 2
        elif mark == "/":
            before = token.start() - 1
            while before >= 0 and text[before] in " \t":
                before -= 1
            if before < 0 or text[before] in REGEX_AFTER:
                index = JS_REGEX.match(text, index).end()
        else:
            end = JS_STRING[mark].match(text, index).end()
            found.append((index, end, mark))
            index = end + 1
    return tuple(found)


@lru_cache(maxsize=16)
def unescaped(text, start, end):
    """The text of the string at *start* to *end* in *text*, each escape
    read, and where in *text* each of its characters was."""
    chars, places, index = [], [], start
    while index < end:
        if text[index] == "\\" and index + 1 < end:
            index += 1
        chars.append(text[index])
        places.append(index)
        index += 1
    return "".join(chars), places


def around(line, position, levels=None):
    """Each string around *position* in *line*, outermost first, up to
    *levels* of them: its quote and the span of its text in *line*."""
    found, text, outer = [], line, []

    def inLine(index):
        # A place in the innermost text read so far as a place in the line
        for start, places in reversed(outer):
            index = places[index - 1] + 1 if index else start
        return index

    while levels is None or len(found) < levels:
        spans = literals(text)
        # The last string starting at or before the position, if it holds it
        index = bisect_right(spans, (position, len(text) + 1)) - 1
        if index < 0 or not position < spans[index][1]:
            break
        start, end, quote = spans[index]
        found.append((quote, inLine(start), inLine(end)))
        text, places = unescaped(text, start, end)
        outer.append((start, places))
        position = bisect_left(places, position)
    return found


def enclosing(line, position, depth):
    """The quote of each string around *position* in *line*, outermost first,
    for a code there with the backslashes *depth*: one string for each
    doubling of them, as each string doubles the backslashes inside it."""
    levels = max(1, len(depth).bit_length() - 1)
    return [quote for quote, _start, _end in around(line, position, levels)]


@lru_cache(maxsize=8)
def closingQuote(mark):
    return re.compile(r"(\\*)" + re.escape(mark))


def stringEnd(line, start, quote, mark):
    """Where the text from *start* of a string opened by *mark* with the
    backslashes *quote* before it ends: before the first *mark* its own depth
    closes, or None where its line does not.

    Each string around it doubles the backslashes of what it holds and adds
    one before each quote, so a string q backslashes deep is closed by a quote
    with q more than a multiple of 2(q + 1) before it, an even count at the top
    level; a quote of its text, escaped deeper, never matches.
    """
    period = 2 * (len(quote) + 1)
    for found in closingQuote(mark).finditer(line, start):
        if len(found.group(1)) % period == len(quote):
            return found.start()
    return None


def within(scopes, start, end):
    return any(first <= start and end <= last for first, last in scopes)


def opening(pattern):
    """Fields whose *pattern* ends at their string's opening quote, with its
    backslashes in group "quote": each field's text runs to its string's own
    closing quote."""
    compiled = re.compile(pattern)

    def find(line, scopes):
        for match in compiled.finditer(line):
            start = match.end()
            end = stringEnd(line, start, match.group("quote"), line[start - 1])
            if end is not None and within(scopes, start, end):
                yield start, end, match.group("quote")

    return find


def inside(pattern):
    """Fields inside a string, *pattern*'s group "text": each kept where the
    string around its text also holds the rest of its match. After a match
    that is not kept, the search goes on from the start of its text, so a
    field it ran over, as in '\\}' + n + '\\}回数\\{', is still read."""
    compiled = re.compile(pattern)

    def kept(line, scopes, match):
        start, end = match.span("text")
        if not within(scopes, start, end):
            return False
        strings = around(line, start)
        return bool(strings) and match.end() <= strings[-1][2]

    def find(line, scopes):
        match = compiled.search(line)
        while match:
            if kept(line, scopes, match):
                yield *match.span("text"), match.group("quote")
                match = compiled.search(line, match.end())
            else:
                match = compiled.search(line, match.start("text"))

    return find


def literalText(text, quotes):
    """*text* written inside the strings of *quotes*, outermost first: each of
    their quote characters, with any backslashes the reply put before it, is
    escaped for every string around it, so none ends one."""
    escapes = {}
    for char in set(quotes):
        escaped = char
        for quote in reversed(quotes):
            escaped = escaped.replace("\\", "\\\\").replace(quote, "\\" + quote)
        escapes[char] = escaped
    if not escapes:
        return text
    return re.sub(
        r"\\*([" + re.escape("".join(escapes)) + "])",
        lambda found: escapes[found.group(1)],
        text,
    )


def jsonText(text):
    """A translation as a plugin parameter's JSON string writes it: double
    quotes as single ones, each escaped with one backslash for the JavaScript
    string the parameter sits in, except one after a backslash or another."""
    text = text.replace('"', "'")
    return re.sub(r"([^\\'])'", r"\1\\'", text)


def subjectText(text):
    """A translation as a txtSubject string writes it: its quotes, except one
    after a backslash or another, as the Armenian apostrophe."""
    text = re.sub(r"([^\\'])'", r"\1՚", text)
    return re.sub(r"([^\\'])\"", r"\1՚", text)


def regionRequest(text):
    return sent(text).strip() or None


def regionWrite(translation, field, line):
    # Wrapped where the source has line breaks, in its double-quoted string
    text = written(
        translation,
        field.text,
        stringDepth(""),
        50 if escapedNewline(field.text) else None,
    )
    return literalText(text, ['"'])


def subjectRequest(text):
    if not re.search(LANGREGEX, text) or re.search(r"^[\\]+$", text):
        return None
    text = sent(text)
    return text.strip() if text.replace("\u3000", "") and text.strip() else None


def subjectWrite(translation, field, line):
    text = written(subjectText(translation), field.text, stringDepth(""))
    with open("log/translations.txt", "a+", encoding="utf-8") as tlFile:
        tlFile.write(f"{field.text} ({text})\n")
    return text


def questRequest(text):
    # Codes at depth one, line breaks as spaces
    return sent(text).strip() if text else None


def jsonWrite(translation, field, line):
    return jsonText(written(translation, field.text, stringDepth(field.quote)))


def jsonWrapped(translation, field, line):
    return jsonText(written(translation, field.text, stringDepth(field.quote), WIDTH))


def menuRequest(text):
    if not re.search(LANGREGEX, text) or re.search(r"^[\\]+$", text):
        return None
    if not text.replace("\u3000", "").strip():
        return None
    # Codes and line breaks at depth one
    return sent(text, True).strip()


def labelRequest(text):
    # Game variable references are counted words (COUNTER_WORD)
    if "$gameVariables" in text or not re.search(LANGREGEX, text):
        return None
    if not text.replace("\u3000", "").strip():
        return None
    return sent(text, True).strip()


def labelWrite(translation, field, line):
    text = written(translation, field.text, field.quote).replace('"', "'")
    return literalText(text, enclosing(line, field.start, field.quote))


def statRequest(text):
    if not re.search(LANGREGEX, text) or not text.replace("\u3000", "").strip():
        return None
    return text.strip()


def statWrite(translation, field, line):
    return literalText(translation, enclosing(line, field.start, field.quote))


QUEST_GROUPS = (
    Group("Quest Name"),
    Group("Quest Client"),
    Group("Quest Location"),
    Group("Quest Location"),
    Group("Quest Summary"),
    Group("Quest Goal"),
)
CUSTOM = Group("Relic Name")
MENU_TEXT = Group("Menu Item")
MENU_COMMON_HELP = Group("Menu Help Text")
MENU_HELP = Group("Menu Help Text")
DRAWN_LABEL = Group("Status Tracker Label", once=True)
STAT_LABEL = Group("Character Stat Name", once=True)
SAVE_PARAM = Group("Save Screen Label")
# The requests in the order they are sent
GROUPS = (
    *QUEST_GROUPS,
    CUSTOM,
    MENU_TEXT,
    MENU_COMMON_HELP,
    MENU_HELP,
    DRAWN_LABEL,
    STAT_LABEL,
    SAVE_PARAM,
)


# A disp_list region: the object or list its anchor opens, and its strings
REGION_ANCHOR = re.compile(r"data_map_name_list[\\\"']*\s*[:=]?\s*([{\[])")
REGION_STRING = re.compile(source_pattern("disp_list"))
CLOSES = {"{": "}", "[": "]"}


def regionStrings(line, scopes):
    for start, end, _quote in literals(line):
        if within(scopes, start, end) and REGION_STRING.fullmatch(line, start - 1, end + 1):
            yield start, end, ""


def regions(data):
    """The span of each line's disp_list region, by line: from the bracket
    its anchor opens to the one that closes it, counting the brackets of the
    code between, not those in its strings."""
    found, opener, depth = {}, None, 0
    for index, line in enumerate(data):
        if opener is None and "data_map_name_list" not in line:
            continue
        spans = literals(line)
        begin = 0
        if opener is None:
            anchor = REGION_ANCHOR.search(line)
            if anchor is None or any(s <= anchor.start(1) < e for s, e, _q in spans):
                continue
            opener, depth, begin = anchor.group(1), 0, anchor.start(1)
        strings = iter(spans)
        string = next(strings, None)
        end, position = len(line), begin
        while position < len(line):
            while string is not None and string[1] < position:
                string = next(strings, None)
            if string is not None and string[0] <= position <= string[1]:
                position = string[1] + 1
                continue
            char = line[position]
            depth += (char == opener) - (char == CLOSES[opener])
            if depth == 0:
                end, opener = position, None
                break
            position += 1
        found[index] = [(begin, end)]
    return found


# The kinds in the order the walk reads them on a line
KINDS = (
    # A disp_list region's strings (e.g., this.disp_list = { key: { subkey:
    # ["string1", "string2"] } })
    Kind(
        regionStrings,
        CUSTOM,
        regionRequest,
        regionWrite,
        inRegion,
    ),
    # A key or assignment holding a string, or a parameter's fallback
    # (parameters['txtSubject'] || 'クエスト'), never code between them
    Kind(
        opening(
            r"""txtSubject(?:\\*["'])?(?:\s*[:=]|\]\s*\|\|)\s*(?P<quote>\\*)["']"""
        ),
        CUSTOM,
        subjectRequest,
        subjectWrite,
    ),
    Kind(
        opening(r'[\\]+"QuestName[\\]+":(?P<quote>[\\]+)"'),
        QUEST_GROUPS[0],
        questRequest,
        jsonWrite,
    ),
    Kind(
        opening(r'QuestClientName[\\]+":(?P<quote>[\\]+)"'),
        QUEST_GROUPS[1],
        questRequest,
        jsonWrite,
    ),
    Kind(
        opening(r'QuestLocation[\\]+":(?P<quote>[\\]+)"'),
        QUEST_GROUPS[2],
        questRequest,
        jsonWrite,
    ),
    Kind(
        opening(r'PlaceInformation[\\]+":(?P<quote>[\\]+)"'),
        QUEST_GROUPS[3],
        questRequest,
        jsonWrite,
    ),
    # Quest summary and goals, wrapped
    Kind(
        opening(r'[\\]+"QuestContent[\\]+":[\\]+"(?P<quote>[\\]+)"'),
        QUEST_GROUPS[4],
        questRequest,
        jsonWrapped,
    ),
    Kind(
        opening(r'ObjectiveContent[\\]+":[\\]+"(?P<quote>[\\]+)"'),
        QUEST_GROUPS[5],
        questRequest,
        jsonWrapped,
    ),
    # SceneCustomMenu command labels and help
    Kind(
        opening(r'[\\]+"Text[\\]+":(?P<quote>[\\]+)"'),
        MENU_TEXT,
        menuRequest,
        jsonWrite,
    ),
    Kind(
        opening(r'[\\]+"CommonHelpText[\\]+":(?P<quote>[\\]+)"'),
        MENU_COMMON_HELP,
        menuRequest,
        jsonWrite,
    ),
    Kind(
        opening(r'[\\]+"HelpText[\\]+":(?P<quote>[\\]+)"'),
        MENU_HELP,
        menuRequest,
        jsonWrite,
    ),
    # NUUN_SaveScreen labels (現在地, プレイ時間, 所持金)
    Kind(
        opening(r'[\\]+"ParamName[\\]+":(?P<quote>[\\]+)"'),
        SAVE_PARAM,
        menuRequest,
        jsonWrite,
    ),
    # drawTextEx brace labels (\}【口づけ】\{, \}回数：\{)
    Kind(
        inside(r"(?P<quote>[\\]+)\}(?P<text>.+?)[\\]+\{"),
        DRAWN_LABEL,
        labelRequest,
        labelWrite,
        drawing,
    ),
    # drawTextEx stat labels (\C[16]攻撃力\C[0])
    Kind(
        inside(r"C\[\d+\](?P<text>[^C\\,`\[\]]+?)(?P<quote>[\\]+)C\[0\]"),
        STAT_LABEL,
        statRequest,
        statWrite,
        drawing,
    ),
)

# A drawTextEx counter after a game variable, written as English counts: 回
# as a word of its own, not the start of a longer one such as 回復
COUNTER_WORD = re.compile(
    r"(\$\{\$gameVariables\.value\(\d+\)\}\s*)回(?!" + LANGREGEX + ")"
)


def fields(data):
    """Every field of a plugin file's lines *data*, in file order."""
    found, regionSpans = [], regions(data)
    for index, line in enumerate(data):
        taken = []
        for kind in KINDS:
            scopes = kind.reads(line, regionSpans.get(index, []))
            if not scopes:
                continue
            for start, end, quote in kind.find(line, scopes):
                request = kind.request(line[start:end])
                if request is None or any(start < last and first < end for first, last in taken):
                    continue
                taken.append((start, end))
                found.append(Field(kind, index, start, end, line[start:end], quote, request))
    return found


def translatePlugin(data, pbar, filename):
    tokens = [0, 0]
    with open("log/translations.txt", "a+", encoding="utf-8") as tlFile:
        tlFile.write("\nCustom:\n")

    # Each group's request, each line with the fields its reply goes to
    # (util/sent_lines); a label sent once goes to every field holding it
    requests = {group: SentLines(unlabel=None) for group in GROUPS}
    holders, edits = {}, {}
    for field in fields(data):
        group = field.kind.group
        key = (group, field.request) if group.once else field
        if key in holders:
            holders[key].append(field)
            continue
        holders[key] = [field]

        def write(reply, fields=holders[key]):
            for held in fields:
                edits.setdefault(held.line, []).append((held, reply))

        requests[group].send(field.request, write)

    total = sum(len(lines) for lines in requests.values())
    if total > 0:
        pbar.total = total
        pbar.refresh()

    # Each group's translations, where its reply has a line for each request
    # line. A quest group is sent even when empty and its empty reply taken:
    # the file is written when any reply is.
    translated = False
    for group in GROUPS:
        lines = requests[group]
        if not lines and group not in QUEST_GROUPS:
            continue
        response = translateAI(lines.lines, group.history)
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        if lines.write(response[0], MISMATCH, LOCK, filename):
            translated = True
    if not translated:
        return tokens

    # Each translation written to its field's span
    for index, lineEdits in edits.items():
        line, parts, last = data[index], [], 0
        for field, translation in sorted(lineEdits, key=lambda edit: edit[0].start):
            parts += [line[last : field.start], field.kind.write(translation, field, line)]
            last = field.end
        data[index] = "".join(parts) + line[last:]

    # Hardcoded counter word: 回 → x, where a drawTextEx call reads labels;
    # the one-letter word keeps each scope's span
    for index, line in enumerate(data):
        if "$gameVariables" in line:
            for start, end in drawing(line, []):
                line = line[:start] + COUNTER_WORD.sub(r"\1x", line[start:end]) + line[end:]
            data[index] = line
    return tokens


def translateAI(text, history, history_ctx=None):
    """
    Legacy wrapper function for the new shared translation utility.
    This maintains compatibility with existing code while using the new shared implementation.
    """
    global PBAR, MISMATCH, FILENAME

    # Update config estimate mode based on global ESTIMATE
    TRANSLATION_CONFIG.estimateMode = bool(ESTIMATE)

    # Call the new shared translation function
    return sharedtranslateAI(
        text=text,
        history=history,
        config=TRANSLATION_CONFIG,
        filename=FILENAME,
        pbar=PBAR,
        lock=LOCK,
        mismatchList=MISMATCH
    )
