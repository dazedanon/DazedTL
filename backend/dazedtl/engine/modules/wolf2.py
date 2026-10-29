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
from util.speakers import strip_speaker_prefix
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
    # Use a robust reader to handle cp932/Shift_JIS variants and occasional bad bytes
    def read_file_lines_with_fallback(path: str):
        encodings = ["cp932", "shift_jis", "utf-8-sig", "utf-8"]
        for enc in encodings:
            try:
                with open(path, "r", encoding=enc) as f:
                    return f.readlines()
            except UnicodeDecodeError:
                continue
        # Last resort: ignore undecodable bytes under cp932
        with open(path, "rb") as f:
            raw = f.read()
        try:
            text = raw.decode("cp932", errors="ignore")
        except Exception:
            text = raw.decode("latin-1", errors="ignore")
        return text.splitlines(keepends=True)

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
            result = translateWOLF(data, [], pbar, filename)
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


def translateWOLF(data, translatedList, pbar, filename):
    stringList = []
    currentGroup = []
    tokens = [0, 0]
    speaker = ""
    global LOCK, ESTIMATE, PBAR
    PBAR = pbar
    i = 0

    while i < len(data):
        # Speaker
        matchList = re.findall(r"^([^/]*)：", data[i])
        if len(matchList) != 0:
            response = getSpeaker(matchList[0])
            speaker = response[0]
            tokens[0] += response[1][0]
            tokens[1] += response[1][1]
            data[i] = data[i].replace(matchList[0], f"{speaker}")
            checkLine(data, i, filename)
            i += 1
        else:
            speaker = ""

        # Options
        if "//選択肢" in data[i]:
            i += 1
            choiceList = []
            initialIndex = i
            while "//" in data[i] and "の場合" not in data[i]:
                choiceList.append(re.search(r"\/\/(.*)", data[i]).group(1))
                i += 1

            # Translate
            response = translateAI(choiceList, "This will be a dialogue option")
            tokens[0] += response[1][0]
            tokens[1] += response[1][1]
            choiceListTL = response[0]

            # Set Data
            if len(choiceList) == len(choiceListTL):
                # Set Data
                i = initialIndex
                while "//" in data[i] and "の場合" not in data[i]:
                    choiceListTL[0] = choiceListTL[0].replace(", ", "、")
                    data[i] = f"//{choiceListTL[0]}\n"
                    checkLine(data, i, filename)
                    choiceListTL.pop(0)
                    i += 1

            # Mismatch
            else:
                with LOCK:
                    found_mismatch(MISMATCH, filename)

        # Lines
        if r"/" not in data[i] and "@" not in data[i] and data[i] != "\n":
            # Pass 1
            if translatedList == []:
                # Grab Consecutive Strings
                currentGroup.append(data[i])
                i += 1
                while i < len(data) and r"/" not in data[i] and "@" not in data[i] and data[i] != "\n":
                    currentGroup.append(data[i])
                    i += 1

                # Join up 401 groups for better translation.
                if len(currentGroup) > 0:
                    jaString = "".join(currentGroup)
                    currentGroup = []

                # Remove any textwrap
                jaString = jaString.replace("\n", " ")

                # Add Speaker (If there is one)
                if speaker != "":
                    jaString = f"[{speaker}]: {jaString}"

                # Add String
                stringList.append(jaString)
                i += 1

            # Pass 2
            else:
                # Insert Strings
                while i < len(data) and r"/" not in data[i] and "@" not in data[i] and data[i] != "\n":
                    data.pop(i)

                # Get Text
                translatedText = translatedList[0]
                translatedList.pop(0)

                if len(translatedList) <= 0:
                    translatedList = None

                # Remove speaker
                translatedText = strip_speaker_prefix(translatedText)

                # Textwrap
                translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)

                # Set Data
                data.insert(i, f"{translatedText}\n")
                checkLine(data, i, filename)
                i += 1

        # Nothing relevant. Skip Line.
        else:
            i += 1

    # EOF
    if len(stringList) > 0:
        # Set Progress
        pbar.total = len(stringList)
        pbar.refresh()

        # Translate
        response = translateAI(stringList, "")
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        translatedList = response[0]

        # Set Strings
        if len(stringList) == len(translatedList):
            translateWOLF(data, translatedList, pbar, filename)

        # Mismatch
        else:
            with LOCK:
                found_mismatch(MISMATCH, filename)
    return tokens

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
