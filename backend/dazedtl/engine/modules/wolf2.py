# Libraries
import json
import io
import os
import re
from util.speakers import translate_speaker
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
from util.translation import TranslationConfig, translateAI as sharedtranslateAI, getPricingConfig, calculateCost, found_mismatch, run_stop_errors
from util.translation_task import fail_on_parser_error, module_receipt, write_output
from util.sent_lines import SentLines
from util.speakers import find_speaker
from util.game_encoding import check_line, writable

# OpenAI initialization centralized in util/translation.py

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
NAMESLIST = []
NAMES = False  # Output a list of all the character names found
BRFLAG = False  # If the game uses <br> instead
FIXTEXTWRAP = True  # Overwrites textwrap
IGNORETLTEXT = False  # Ignores all translated text.
MISMATCH = []  # Lists files that throw a mismatch error (Length of GPT list response is wrong)
FILENAME = ""  # Current file being processed, used by translateAI wrapper

# tqdm Globals
BAR_FORMAT = "{l_bar}{bar:10}{r_bar}{bar:-10b}"
POSITION = 0
LEAVE = False

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

def handleWOLF2(filename, estimate):
    global ESTIMATE, FILENAME
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

        # Print Result
        end = time.time()
        with LOCK:
            TOKENS[0] += translatedData[1][0]
            TOKENS[1] += translatedData[1][1]
        # A line the encoding can't write fails the file (util/game_encoding).
        lines = writable(translatedData[0], "shift_jis", filename)
        write_output(filename, "".join(lines), encoding="shift_jis", errors="ignore")
        tqdm.write(module_receipt(filename, translatedData[1], end - start, MODEL))

    return module_receipt("TOTAL", TOKENS, end - start, MODEL)


def openFiles(filename):
    # Use a robust reader to handle cp932/Shift_JIS variants and occasional
    # bad bytes. Each reads with universal newlines, so every line ends in
    # "\n" alone, as the parser and write_output expect.
    def read_file_lines_with_fallback(path: str):
        encodings = ["cp932", "shift_jis", "utf-8-sig", "utf-8"]
        for enc in encodings:
            try:
                with open(path, "r", encoding=enc) as f:
                    return f.readlines()
            except UnicodeDecodeError:
                continue
        # Last resort: ignore undecodable bytes under cp932
        with open(path, "r", encoding="cp932", errors="ignore") as f:
            return f.readlines()

    path = os.path.join("files", filename)
    lines = read_file_lines_with_fallback(path)

    # Keep parseWOLF API by wrapping lines in a file-like object
    with io.StringIO("".join(lines)) as readFile:
        translatedData = parseWOLF(readFile, filename)

    # Delete lines marked for deletion
    finalData = []
    for line in translatedData[0]:
        if line != "\\d\n":
            finalData.append(line)
    translatedData[0] = finalData

    return translatedData


def parseWOLF(readFile, filename):
    totalTokens = [0, 0]

    # Read File into data
    data = readFile.readlines()

    # Create Progress Bar
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE) as pbar:
        pbar.desc = filename

        try:
            result = translateWOLF(data, pbar, filename)
            totalTokens[0] += result[0]
            totalTokens[1] += result[1]
        except run_stop_errors():
            raise
        except Exception as e:
            traceback.print_exc()
            return [data, totalTokens, e]
    return [data, totalTokens, None]


def checkLine(data, i, filename):
    """Fails the file at once when line i, just set, holds a letter the
    game's shift_jis can't write, before its later requests are paid for
    (util/game_encoding). An estimate writes nothing."""
    if not ESTIMATE:
        check_line(data, i, "shift_jis", filename)


def isText(line):
    """Whether *line* is a line of text: not blank, a "//" comment or choice,
    or an "@" command."""
    return "/" not in line and "@" not in line and line != "\n"


# A speaker: the first line of a message, of its own and ending in "：", the
# name before it, as WOLF writes a message's nameplate (Name：, then the
# message). A message is a run of text lines, so it starts at the file's
# start or after a blank line, a "//" line or an "@" command; any later line
# of the run, "：" or not, is the message's text.
SPEAKER = r"^([^/@\n]+)：\s*$"


def translateWOLF(data, pbar, filename):
    """Translates speakers and choices on the spot and sends each message,
    a run of consecutive text lines, as one line (util/sent_lines), then
    writes each translation over its run. The runs are kept by position, so
    a translated speaker holding the parser's own marks, such as "/", cannot
    move a translation to another run."""
    lines = SentLines()
    tokens = [0, 0]
    global LOCK, ESTIMATE, PBAR
    PBAR = pbar
    i = 0

    while i < len(data):
        # Options, up to the "の場合" line that starts the first one's branch
        if "//選択肢" in data[i]:
            i += 1
            choiceList = []
            initialIndex = i
            while i < len(data) and "//" in data[i] and "の場合" not in data[i]:
                choiceList.append(re.search(r"\/\/(.*)", data[i]).group(1))
                i += 1

            # Translate
            response = translateAI(choiceList, "This will be a dialogue option")
            tokens[0] += response[1][0]
            tokens[1] += response[1][1]
            choiceListTL = response[0]

            # Set Data
            if len(choiceList) == len(choiceListTL):
                for index, choice in enumerate(choiceListTL, start=initialIndex):
                    data[index] = f"//{choice.replace(', ', '、')}\n"
                    checkLine(data, index, filename)

            # Mismatch
            else:
                with LOCK:
                    found_mismatch(MISMATCH, filename)

            # The line that ends the options, such as a message, is read next
            continue

        # A message, its speaker first if it names one
        if isText(data[i]):
            speaker = ""
            found = find_speaker(SPEAKER, data[i])
            if found:
                response = getSpeaker(found.name)
                speaker = response[0]
                tokens[0] += response[1][0]
                tokens[1] += response[1][1]
                data[i] = found.written(speaker)
                checkLine(data, i, filename)
                i += 1

            # Its lines, joined up for better translation and without textwrap
            start = i
            while i < len(data) and isText(data[i]):
                i += 1
            jaString = "".join(data[start:i]).replace("\n", " ")
            lines.send(jaString, _run_writer(data, start, i, filename), speaker)

        # Nothing relevant. Skip Line.
        else:
            i += 1

    # EOF
    if len(lines) > 0:
        # Set Progress
        pbar.total = len(lines)
        pbar.refresh()

        # Translate
        response = translateAI(lines.lines, "")
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        translatedList = response[0]

        # Set Strings
        if len(lines) == len(translatedList):
            lines.write(translatedList)

        # Mismatch
        else:
            with LOCK:
                found_mismatch(MISMATCH, filename)
    return tokens


def _run_writer(data, start, end, filename):
    """Writes the translation of the run of lines *start* to *end* as its one
    line. The run's other lines are emptied, not removed, so the runs after
    it keep their places."""

    def write(translatedText):
        translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)
        data[start:end] = [f"{translatedText}\n"] + [""] * (end - start - 1)
        checkLine(data, start, filename)

    return write


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
