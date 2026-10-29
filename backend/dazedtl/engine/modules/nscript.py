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
from pathlib import Path
from colorama import Fore
from dotenv import load_dotenv
from retry import retry
from tqdm import tqdm
from util.languages import source_pattern
from util.translation import TranslationConfig, translateAI as sharedtranslateAI, getPricingConfig, calculateCost, found_mismatch, run_stop_errors
from util.translation_task import fail_on_parser_error, module_receipt, write_output
from util.game_encoding import check_line, writable

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
CONVERTTOWIDE = False # Default (False)

# tqdm Globals
BAR_FORMAT = "{l_bar}{bar:10}{r_bar}{bar:-10b}"
POSITION = 0
LEAVE = False
PBAR = None
FILENAME = None

# Full Width
ascii_to_wide = dict((i, chr(i + 0xFEE0)) for i in range(0x21, 0x7F))
ascii_to_wide.update({0x20: "\u3000", 0x2D: "\u2212"})  # space and minus
wide_to_ascii = dict((i, chr(i - 0xFEE0)) for i in range(0xFF01, 0xFF5F))
wide_to_ascii.update({0x3000: " ", 0x2212: "-"})  # space and minus

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

def handleOnscripter(filename, estimate):
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
        lines = writable(translatedData[0], "cp932", filename)
        write_output(filename, "".join(lines), encoding="cp932", errors="ignore")
        tqdm.write(module_receipt(filename, translatedData[1], end - start, MODEL))

    return module_receipt("TOTAL", TOKENS, end - start, MODEL)


def openFiles(filename):
    with open("files/" + filename, "r", encoding="cp932") as readFile:
        translatedData = parseOnscripter(readFile, filename)

        # Delete lines marked for deletion
        finalData = []
        for line in translatedData[0]:
            if line != "\\d\n":
                finalData.append(line)
        translatedData[0] = finalData

    return translatedData


def parseOnscripter(readFile, filename):
    totalTokens = [0, 0]

    # Read File into data
    data = readFile.readlines()

    # Create Progress Bar
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE) as pbar:
        pbar.desc = filename

        try:
            result = translateOnscripter(data, pbar, filename, [])
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
    game's cp932 can't write, before its later requests are paid for
    (util/game_encoding). An estimate writes nothing."""
    if not ESTIMATE:
        check_line(data, i, "cp932", filename)


def translateOnscripter(data, pbar, filename, translatedList):
    stringList = []
    currentGroup = []
    tokens = [0, 0]
    speaker = ""
    voice = False
    global LOCK, ESTIMATE, PBAR
    PBAR = pbar
    i = 0

    # Dialogue
    while i < len(data):
        # Lines
        regex = r"^([\u3000「（【[][^\n]+)"
        match = re.search(regex, data[i])
        if match != None and match.group(1) != "":
            originalString = match.group(1)
            # Pass 1
            if translatedList == []:
                # Grab Consecutive Strings
                jaString = match.group(1)
                while len(data) > i + 1 and re.match(regex, data[i + 1]):
                    data[i] = ""
                    i += 1
                    jaString = f"{jaString} {data[i]}"

                # Convert from Wide
                jaString = jaString.translate(wide_to_ascii)

                # Remove any textwrap and \u3000 and \
                jaString = jaString.replace("\n", "")
                jaString = jaString.replace("\u3000", "")
                jaString = jaString.replace("\\", "")
                jaString = jaString.replace("　＞", ")")
                jaString = jaString.replace("＜　", "(")

                # Remove Furigana
                furiMatch = re.findall(r"({(.+?)\/(.+?)})", jaString)
                if furiMatch:
                    for match in furiMatch:
                        jaString = jaString.replace(match[0], match[2])

                # Add String
                stringList.append(jaString.strip())

            # Pass 2
            else:
                # Get Text
                if translatedList:
                    # Grab and Pop
                    translatedText = translatedList[0]
                    translatedList.pop(0)

                    # Set to None if empty list
                    if len(translatedList) <= 0:
                        translatedList = None

                    # Textwrap & Other Text
                    translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)
                    translatedText = translatedText.replace("\n", "\n\u3000")

                    # Split the string into lines
                    lines = translatedText.split("\n")

                    # Add a backslash after every 3rd line
                    j = 0
                    while j < len(lines):
                        if j == 4:
                            lines[j - 1] = f"{lines[j-1]}\\"
                            lines[j] = f"\n{lines[j]}"
                        j += 1

                    # Join the lines back into a single string
                    translatedText = "\n".join(lines)

                    # Remove Double Spaces
                    translatedText = translatedText.replace("  ", " ")

                    # Convert to Wide
                    if CONVERTTOWIDE:
                        translatedText = translatedText.translate(ascii_to_wide)

                    # Fix Formatting
                    translatedText = fixText(translatedText)

                    # Set Data
                    data[i] = data[i].replace(originalString, f"{translatedText}")
                    checkLine(data, i, filename)
            i += 1

        # Choices
        elif "csel" in data[i] and translatedList != []:
            choiceList = []
            jaString = data[i]

            choiceList = re.findall(r"\"(.*?)\"", jaString)
            if len(choiceList) > 0:
                # Translate
                response = translateAI(choiceList, "This will be a dialogue option")
                translatedTextList = response[0]
                tokens[0] += response[1][0]
                tokens[1] += response[1][1]

                # Set Data
                for j in range(len(translatedTextList)):
                    # Convert to Wide
                    if CONVERTTOWIDE:
                        translatedText = translatedTextList[j].translate(ascii_to_wide)

                    # Set
                    data[i] = data[i].replace(choiceList[j], translatedText)
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
            translateOnscripter(data, pbar, filename, translatedList)

        # Mismatch
        else:
            with LOCK:
                found_mismatch(MISMATCH, filename)
    return tokens


def fixText(translatedText):
    # Add Break
    translatedText = translatedText.replace('"', "'")
    translatedText = f"\u3000{translatedText}\\"

    # Unconvert Codes
    matchList = re.findall(r"([＄].+?)[^\w]", translatedText)
    if matchList:
        for match in matchList:
            translatedText = translatedText.replace(match, match.translate(wide_to_ascii))

    # Unconvert Color Codes
    matchList = re.findall(r"([＃][\w\d]{6})", translatedText)
    if matchList:
        for match in matchList:
            translatedText = translatedText.replace(match, match.translate(wide_to_ascii))

    # Unconvert Variables
    matchList = re.findall(r"([％]\w.+?)[^\w＿]", translatedText)
    if matchList:
        for match in matchList:
            translatedText = translatedText.replace(match, match.translate(wide_to_ascii))

    # Unconvert Backslashes
    matchList = re.findall(r"＼", translatedText)
    if matchList:
        for match in matchList:
            translatedText = translatedText.replace(match, match.translate(wide_to_ascii))

    return translatedText

# Save some money and enter the character before translation
def getSpeaker(speaker):
    return translate_speaker(speaker, NAMESLIST, LANGUAGE, translateAI)


def translateAI(text, history, history_ctx=None):
    """
    Translate text using the shared translation utility.
    This function maintains compatibility with existing code while using the new shared implementation.
    """
    return sharedtranslateAI(
        text=text,
        history=history,
        config=TRANSLATION_CONFIG,
        filename=FILENAME,
        pbar=PBAR,
        lock=LOCK,
        mismatchList=MISMATCH
    )
