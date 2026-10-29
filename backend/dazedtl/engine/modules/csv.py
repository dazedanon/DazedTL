# Libraries
import json
import os
import re
from util.speakers import translate_speaker
import util.dazedwrap as dazedwrap
import threading
import time
import traceback
import tiktoken
import csv
import io
from functools import partial
from pathlib import Path
from colorama import Fore
from dotenv import load_dotenv
from retry import retry
from tqdm import tqdm
from util.languages import source_pattern
from util.translation import TranslationConfig, translateAI as sharedtranslateAI, getPricingConfig, calculateCost, found_mismatch, run_stop_errors
from util.translation_task import fail_on_parser_error, module_receipt, write_output
from util.sent_lines import SentLines
from util.speakers import find_speaker

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
NOTEWIDTH = int(os.getenv("noteWidth"))
MAXHISTORY = 10
ESTIMATE = ""
TOKENS = [0, 0]
NAMESLIST = []
NAMES = False  # Output a list of all the character names found
BRFLAG = False  # If the game uses <br> instead
FIXTEXTWRAP = True  # Overwrites textwrap
IGNORETLTEXT = True  # Ignores all translated text.
MISMATCH = []  # Lists files that thdata a mismatch error (Length of GPT list response is wrong)
FILENAME = None
BRACKETNAMES = False

# CSV Configuration Settings (configurable via GUI)
CSV_DELIMITER = ","  # CSV delimiter character (comma, semicolon, tab)
SOURCE_COLUMN = 0  # Which column has the source text to translate (0-indexed)
TARGET_COLUMN = 1  # Which column to write translations to
SPEAKER_COLUMN = -1  # Which column has speaker names (-1 = none)
SKIP_HEADER_ROW = True  # Skip the first row (header)
USE_TARGET_IF_NOT_EMPTY = False  # Use target column text if not empty (T++ style)
SKIP_IF_TARGET_TRANSLATED = True  # Skip batches whose targets are already translated
WRITE_TO_NEXT_COLUMN = False  # Write to column after target instead of overwriting
PARSE_NAME_TAGS = False  # Parse :name[] tags in text
PARSE_M_MARKERS = False  # Parse \M markers in text
REMOVE_FURIGANA = True  # Remove furigana annotations ＜＝＞
SKIP_COMMENT_ROWS = False  # Skip rows starting with 'comment'

# Regex - Need to change this if you want to translate from/to other languages. Default is Japanese Regex
LANGREGEX = source_pattern()

# Get pricing configuration based on the model
PRICING_CONFIG = getPricingConfig(MODEL)
INPUTAPICOST = PRICING_CONFIG["inputAPICost"]
OUTPUTAPICOST = PRICING_CONFIG["outputAPICost"]
BATCHSIZE = PRICING_CONFIG["batchSize"]
FREQUENCY_PENALTY = PRICING_CONFIG["frequencyPenalty"]

# tqdm Globals
BAR_FORMAT = "{l_bar}{bar:10}{r_bar}{bar:-10b}"
POSITION = 0
LEAVE = False
PBAR = None
ENCODING = "utf8"

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

def handleCSV(filename, estimate):
    global ESTIMATE, TOKENS, FILENAME
    ESTIMATE = estimate
    FILENAME = filename

    if not ESTIMATE:
        # Translate
        start = time.time()
        translatedData = openFiles(filename)
        fail_on_parser_error(translatedData)
        rows = io.StringIO()
        csv.writer(rows, delimiter=CSV_DELIMITER).writerows(translatedData[0])
        write_output(filename, rows.getvalue(), encoding=ENCODING, errors="xmlcharrefreplace", newline="")

        # Print Result
        end = time.time()
        tqdm.write(module_receipt(filename, translatedData[1], end - start, MODEL))
        with LOCK:
            TOKENS[0] += translatedData[1][0]
            TOKENS[1] += translatedData[1][1]
    else:
        # Translate
        start = time.time()
        translatedData = openFilesEstimate(filename)
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


def openFiles(filename):
    with open("files/" + filename, "r", encoding=ENCODING) as readFile:
        translatedData = parseCSV(readFile, filename)

    return translatedData


def openFilesEstimate(filename):
    with open("files/" + filename, "r", encoding="utf8") as readFile:
        translatedData = parseCSV(readFile, filename)

    return translatedData


def parseCSV(readFile, filename):
    totalTokens = [0, 0]
    totalLines = 0
    global LOCK

    # Get total for progress bar
    totalLines = len(readFile.readlines())
    readFile.seek(0)

    reader = csv.reader(readFile, delimiter=CSV_DELIMITER)

    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
        pbar.desc = filename
        pbar.total = totalLines

        # Grab All Rows
        data = []
        for row in reader:
            data.append(row)

        try:
            response = translateCSV(data, pbar, filename)
            totalTokens[0] = response[0]
            totalTokens[1] = response[1]
        except run_stop_errors():
            raise
        except Exception as e:
            traceback.print_exc()
            return [data, totalTokens, e]
    return [data, totalTokens, None]


def _actual_target_column():
    """Column index translations are written to."""
    return TARGET_COLUMN + 1 if WRITE_TO_NEXT_COLUMN else TARGET_COLUMN


def _target_is_translated(row):
    """True when the write-target cell is non-empty and has no Japanese left."""
    actual_target = _actual_target_column()
    if len(row) <= actual_target:
        return False
    target = row[actual_target]
    if not isinstance(target, str) or not target.strip():
        return False
    return not re.search(LANGREGEX, target)


def _row_source_text(row):
    """Source text for a row, honoring USE_TARGET_IF_NOT_EMPTY."""
    if USE_TARGET_IF_NOT_EMPTY and len(row) > TARGET_COLUMN and row[TARGET_COLUMN]:
        return row[TARGET_COLUMN]
    if len(row) > SOURCE_COLUMN and row[SOURCE_COLUMN]:
        return row[SOURCE_COLUMN]
    return ""


def _is_candidate_row(data, i):
    """True when this row would normally be collected for translation."""
    if SKIP_HEADER_ROW and i == 0:
        return False
    if SKIP_COMMENT_ROWS and len(data[i]) > 0 and "comment" in str(data[i][0]).lower():
        return False
    if len(data[i]) <= SOURCE_COLUMN:
        return False
    return bool(_row_source_text(data[i]))


def _collect_process_indices(data):
    """Row indices to translate.

    When SKIP_IF_TARGET_TRANSLATED is on, candidates are checked in groups of
    BATCHSIZE (same as the translation batch size):
    - If every target in the group is already translated, skip the group.
    - If any row still needs work, keep the group but only queue the
      untranslated rows so finished targets are left alone.
    """
    candidates = [i for i in range(len(data)) if _is_candidate_row(data, i)]
    if not SKIP_IF_TARGET_TRANSLATED:
        return candidates

    process = []
    batch_size = max(1, int(BATCHSIZE))
    for start in range(0, len(candidates), batch_size):
        batch = candidates[start:start + batch_size]
        if all(_target_is_translated(data[i]) for i in batch):
            continue
        process.extend(i for i in batch if not _target_is_translated(data[i]))
    return process


def translateCSV(data, pbar, filename):
    """
    Unified CSV translation function using configurable settings.

    Uses global settings:
    - SOURCE_COLUMN: column index for source text
    - TARGET_COLUMN: column index to write translations
    - SPEAKER_COLUMN: column index for speaker names (-1 = none)
    - SKIP_HEADER_ROW: whether to skip first row
    - USE_TARGET_IF_NOT_EMPTY: use existing target text if present (T++ style)
    - SKIP_IF_TARGET_TRANSLATED: skip fully-translated candidate batches
    - WRITE_TO_NEXT_COLUMN: write to column after target
    - PARSE_NAME_TAGS: parse :name[] tags
    - PARSE_M_MARKERS: parse \\M markers
    - REMOVE_FURIGANA: remove furigana
    - SKIP_COMMENT_ROWS: skip rows with 'comment' in first column

    Translates each speaker on the spot and writes its name back, sends
    each row's text (util/sent_lines), then writes each translation to the
    row it came from, over the text as the cell holds it. The rows and their
    text are kept from the walk, since a name written back can change a cell
    that decides them, such as a speaker column that is also the target or a
    :name[] tag.
    """
    global LOCK, ESTIMATE, PBAR
    PBAR = pbar
    totalTokens = [0, 0]
    lines = SentLines()

    # Translate
    for i in _collect_process_indices(data):
        # Get source text
        jaString = _row_source_text(data[i])
        speaker = ""

        # Handle speaker column if configured
        if SPEAKER_COLUMN >= 0 and len(data[i]) > SPEAKER_COLUMN and data[i][SPEAKER_COLUMN]:
            speakerResponse = getSpeaker(data[i][SPEAKER_COLUMN])
            totalTokens[0] += speakerResponse[1][0]
            totalTokens[1] += speakerResponse[1][1]
            speaker = speakerResponse[0]
            data[i][SPEAKER_COLUMN] = speaker

        # Parse :name[] tags if configured
        if PARSE_NAME_TAGS and ':name' in jaString:
            match = re.search(NAME_TAG, jaString)
            if match:
                # Translate speaker name, written to the tags alone: the
                # dialogue after it can hold the same name
                response = getSpeaker(match.group(1))
                speaker = response[0]
                totalTokens[0] += response[1][0]
                totalTokens[1] += response[1][1]
                _write_name(data[i], match.group(1), speaker)

                # Extract text portion
                jaString = match.group(2)
                # Remove voice markers
                voMatch = re.search(r"\\[vfF]+\[.+]", jaString)
                if voMatch:
                    jaString = jaString.replace(voMatch.group(0), "")

        # Parse \M markers if configured
        if PARSE_M_MARKERS and '\\M' in jaString:
            match = re.search(r"\\M.+\n([\w\W]*)", jaString)
            if match:
                jaString = match.group(1)
                voMatch = re.search(r"\\[vfF]+\[.+]", jaString)
                if voMatch:
                    jaString = jaString.replace(voMatch.group(0), "")

        # Remove furigana if configured. The translation replaces the text
        # as a target holds it: as the cell does, or without its furigana.
        cellText = jaString
        if REMOVE_FURIGANA:
            jaString = re.sub(r"＜(.*)＝.*＞", r"\1", jaString)
        held = (cellText, jaString)

        # Remove textwrap
        jaString = jaString.replace("\\n", " ")
        jaString = jaString.replace("\n", " ")

        # A name tag with no line after it sends nothing
        lines.send(jaString, partial(_set_translation, data[i], held), speaker)

    # EOF - Process collected strings
    if len(lines) > 0:
        # Set Progress
        pbar.total = len(lines)
        pbar.refresh()

        # Translate
        response = translateAI(lines.lines, "")
        totalTokens[0] += response[1][0]
        totalTokens[1] += response[1][1]
        translatedList = response[0]

        # Set Strings
        if len(lines) == len(translatedList):
            lines.write(translatedList)
        # Mismatch
        else:
            with LOCK:
                found_mismatch(MISMATCH, filename)

    return totalTokens


# A :name[] tag: the speaker's name, then the line the speaker says
NAME_TAG = r":name\[([^\]]+?)\]\n([\w\W]*)"


def _write_name(row, name, translated):
    """Writes *translated* over the :name[] tag that holds *name* in each cell
    *row* reads its text from (_row_source_text) or writes its translation to
    (util/speakers)."""
    columns = {SOURCE_COLUMN, _actual_target_column()}
    if USE_TARGET_IF_NOT_EMPTY:
        columns.add(TARGET_COLUMN)
    for column in sorted(columns):
        found = find_speaker(NAME_TAG, row[column]) if column < len(row) else None
        if found and found.name == name:
            row[column] = found.written(translated)


def _set_translation(row, held, translatedText):
    """Writes *translatedText* to *row*'s target column, over its text in the
    first form in *held* the cell holds: as the row's cell holds it, then as
    it was sent, without its furigana."""
    # Add wordwrap
    translatedText = dazedwrap.wrapText(translatedText, WIDTH)
    translatedText = translatedText.replace("\n", "\\n")

    # Determine target column
    actual_target = _actual_target_column()

    # Ensure row has enough columns
    while len(row) <= actual_target:
        row.append("")

    # Set data
    if PARSE_NAME_TAGS or PARSE_M_MARKERS:
        # Replace the text the row sent, which ends the cell after its
        # :name[] tag or \M marker, so the tag or marker stays even when it
        # holds the same text; an empty target takes them from the cell the
        # text came from
        cell = row[actual_target] or _row_source_text(row)
        for text in held:
            head, sent, tail = cell.rpartition(text)
            if sent:
                row[actual_target] = head + translatedText + tail
                break
        else:
            # A target holding other text keeps it
            if not row[actual_target]:
                row[actual_target] = translatedText
    else:
        row[actual_target] = translatedText


# Save some money and enter the character before translation
def getSpeaker(speaker):
    return translate_speaker(speaker, NAMESLIST, LANGUAGE, translateAI)


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
