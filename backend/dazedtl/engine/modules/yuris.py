import json
import os
import re
import threading
import time
import traceback
from pathlib import Path

from colorama import Fore
from tqdm import tqdm

import util.dazedwrap as dazedwrap
from util.languages import source_pattern
from util.speakers import strip_echoed_speaker, translate_speaker
from util.translation import (
    TranslationConfig,
    calculateCost,
    getPricingConfig,
    translateAI as sharedtranslateAI,
    run_stop_errors,
    found_mismatch,
)
from util.translation_task import fail_on_parser_error, format_receipt, module_receipt, write_output


MODEL = os.getenv("model")
LANGUAGE = os.getenv("language").capitalize()
from util.paths import PROMPT_PATH, read_active_glossary

PROMPT = PROMPT_PATH.read_text(encoding="utf-8")
VOCAB = read_active_glossary()
LOCK = threading.Lock()
WIDTH = int(os.getenv("width"))
MAXHISTORY = 10
ESTIMATE = ""
TOKENS = [0, 0]
NAMESLIST = []
MISMATCH = []
FILENAME = None
PBAR = None

BAR_FORMAT = "{l_bar}{bar:10}{r_bar}{bar:-10b}"
POSITION = 0
LEAVE = False

LANGREGEX = source_pattern()
PRICING_CONFIG = getPricingConfig(MODEL)
BATCHSIZE = PRICING_CONFIG["batchSize"]

TRANSLATION_CONFIG = TranslationConfig(
    model=MODEL,
    language=LANGUAGE,
    prompt=PROMPT,
    vocab=VOCAB,
    langRegex=LANGREGEX,
    batchSize=BATCHSIZE,
    maxHistory=MAXHISTORY,
    estimateMode=False,
)

_ASSET_EXT = re.compile(
    r"\.(png|jpe?g|gif|webp|bmp|tga|tif|ogg|mp3|wav|mid|json|txt|xml|ttf|otf|woff2?|ks|tjs)\b",
    re.I,
)
# Typeface / UI font name tokens — translating breaks runtime font resolution.
_FONTISH = re.compile(
    r"ゴシック|ゴチック|明朝|Mincho|Gothic|ＰＧ|ＭＳ|メイリオ|Meiryo|游ゴ|Yu\s?Gothic|"
    r"Tahoma|Arial|Consolas|Segoe|SimSun|宋体|黑体|DF体|ヒラギノ|Hiragino|"
    r"Noto\s|IPA|Ricty|VL\s|@",
    re.I,
)


def _yuris_nonempty_messages(data: list) -> list[str]:
    out: list[str] = []
    for item in data:
        if isinstance(item, dict):
            msg = item.get("message")
            if isinstance(msg, str) and msg.strip():
                out.append(msg)
    return out


def _yuris_font_face_table(msgs: list[str]) -> bool:
    if not msgs or len(msgs) > 120:
        return False
    if any(len(m) > 120 for m in msgs):
        return False
    ascii_label = re.compile(r"^[A-Za-z0-9 _+.,'-]{1,64}$")
    for m in msgs:
        if _FONTISH.search(m):
            continue
        if ascii_label.fullmatch(m.strip()):
            continue
        return False
    return True


def yuris_whole_file_pass_through_reason(data) -> str | None:
    """
    When True, the file is copied to translated/ unchanged (no API).
    Heuristics: only resource paths, or only font-face style entries.
    """
    if not isinstance(data, list):
        return None
    msgs = _yuris_nonempty_messages(data)
    if not msgs:
        return None
    if all(_message_looks_like_asset_path(m) for m in msgs):
        return "path-only resource strings"
    if _yuris_font_face_table(msgs):
        return "font face list"
    return None


def _message_looks_like_asset_path(message: str) -> bool:
    """Skip resource-like strings: paths, URLs, and any line containing '_' (engine IDs / filenames)."""
    s = message.strip()
    if not s:
        return True
    if "://" in s:
        return True
    if re.match(r"^[A-Za-z]:[/\\]", s):
        return True
    if "\\" in s or "/" in s:
        norm = s.replace("\\", "/")
        tail = norm.rsplit("/", 1)[-1]
        if _ASSET_EXT.search(s):
            return True
        if re.fullmatch(r"[A-Za-z0-9_.-]+", tail):
            return True
    if "_" in s:
        return True
    # Common JP UI font face names (no underscores) — keep short to avoid snagging real prose.
    if len(s) <= 80 and any(t in s for t in ("ゴシック", "ゴチック", "明朝")):
        return True
    return False


def yuris_message_is_translatable(message: str) -> bool:
    return isinstance(message, str) and bool(message.strip()) and not _message_looks_like_asset_path(message)


def replace_yuris_problem_dashes(text: str) -> str:
    """Replace characters the Yuris runtime mishandles (e.g. ― U+2015 HORIZONTAL BAR)."""
    return text.replace("\u2015", "-")


def _yuris_pulse_progress_complete(filename: str) -> None:
    """
    GUI/ subprocess_runner polls modules.yuris.PBAR. Skipped files and 0-line files
    never touched tqdm otherwise, so the monitor never emits PROGRESS:...:n:total and
    rows sit at 0% or odd states until completion.
    """
    global PBAR
    with tqdm(
        total=1,
        bar_format=BAR_FORMAT,
        position=POSITION,
        leave=LEAVE,
        desc=filename,
    ) as pbar:
        PBAR = pbar
        pbar.update(1)
    PBAR = None


def handleYuris(filename, estimate):
    global ESTIMATE, FILENAME, TOKENS
    ESTIMATE = estimate
    FILENAME = filename

    start = time.time()
    with open("files/" + filename, "r", encoding="UTF-8-sig") as readFile:
        data = json.load(readFile)

    pass_reason = yuris_whole_file_pass_through_reason(data)
    if pass_reason:
        if not estimate:
            write_output(filename, json.dumps(data, ensure_ascii=False, indent=4), newline="\n")
        end = time.time()
        # Machine-readable line so the GUI can apply totals row state (same as other modules).
        figures = {"input": 0, "output": 0, "cost": calculateCost(0, 0, MODEL), "seconds": end - start}
        tqdm.write(format_receipt(filename, figures, f"[skipped] {pass_reason}"))
        _yuris_pulse_progress_complete(filename)
    else:
        translatedData = parseYuris(data, filename)
        fail_on_parser_error(translatedData)

        if not estimate:
            write_output(filename, json.dumps(translatedData[0], ensure_ascii=False, indent=4), newline="\n")

        end = time.time()
        tqdm.write(module_receipt(filename, translatedData[1], end - start, MODEL))
        with LOCK:
            TOKENS[0] += translatedData[1][0]
            TOKENS[1] += translatedData[1][1]

    totalString = module_receipt("TOTAL", TOKENS, end - start, MODEL)
    if MISMATCH:
        return totalString + Fore.RED + f"\nMismatch Errors: {MISMATCH}" + Fore.RESET
    return totalString


def parseYuris(data, filename):
    totalTokens = [0, 0]
    global PBAR

    if not isinstance(data, list):
        return [data, totalTokens, TypeError(f"{filename} must be a JSON array")]

    totalLines = sum(
        1
        for item in data
        if isinstance(item, dict) and yuris_message_is_translatable(item.get("message", ""))
    )

    # total=0 breaks tqdm + GUI progress monitor; still pulse 1/1 when nothing to translate.
    pbar_total = max(1, totalLines)
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=pbar_total, leave=LEAVE) as pbar:
        pbar.desc = filename
        PBAR = pbar
        try:
            if totalLines == 0:
                pbar.update(1)
            result = translateYuris(data, filename)
            totalTokens[0] += result[0]
            totalTokens[1] += result[1]
        except run_stop_errors():
            raise
        except Exception as e:
            traceback.print_exc()
            return [data, totalTokens, e]
        finally:
            PBAR = None

    return [data, totalTokens, None]


def translateYuris(data, filename):
    global PBAR
    tokens = [0, 0]
    entries = []
    stringList = []

    for index, item in enumerate(data):
        if not isinstance(item, dict):
            continue

        speaker = ""
        if isinstance(item.get("name"), str) and item["name"].strip():
            speakerData = getSpeaker(item["name"].strip())
            speaker = speakerData[0]
            tokens[0] += speakerData[1][0]
            tokens[1] += speakerData[1][1]
            item["name"] = speaker

        message = item.get("message")
        if not yuris_message_is_translatable(message):
            continue

        cleanMessage = message.replace("\r\n", " ").replace("\n", " ").strip()
        cleanMessage = replace_yuris_problem_dashes(cleanMessage)
        hasSpeaker = bool(speaker)
        stringList.append(f"[{speaker}]: {cleanMessage}" if hasSpeaker else cleanMessage)
        entries.append((index, message, hasSpeaker))

    if not stringList:
        return tokens

    PBAR.total = len(stringList)
    PBAR.refresh()

    response = translateAI(stringList, "Reply with the English Translation")
    tokens[0] += response[1][0]
    tokens[1] += response[1][1]
    translatedList = response[0]

    if len(stringList) != len(translatedList):
        with LOCK:
            found_mismatch(MISMATCH, FILENAME)
        return tokens

    for (index, originalMessage, hasSpeaker), translatedText in zip(entries, translatedList):
        if hasSpeaker:
            translatedText = stripSpeakerPrefix(translatedText)
        translatedText = replace_yuris_problem_dashes(translatedText)
        translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)
        translatedText = translatedText.replace("\n", "\r\n")
        data[index]["message"] = originalMessage.replace(originalMessage, translatedText)
        if PBAR is not None:
            PBAR.update(1)

    return tokens


def stripSpeakerPrefix(translated_text):
    """Same behavior as modules/json.translateJSON: strip [Name]: prefix from TL lines."""
    return strip_echoed_speaker(translated_text, LANGUAGE).strip()


def getSpeaker(speaker):
    return translate_speaker(speaker, NAMESLIST, LANGUAGE, translateAI)


def translateAI(text, history, history_ctx=None):
    global PBAR, MISMATCH, FILENAME
    TRANSLATION_CONFIG.estimateMode = bool(ESTIMATE)
    return sharedtranslateAI(
        text=text,
        history=history,
        config=TRANSLATION_CONFIG,
        filename=FILENAME,
        pbar=PBAR,
        lock=LOCK,
        mismatchList=MISMATCH,
    )
