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
from functools import partial
from util.translation import TranslationConfig, translateAI as sharedtranslateAI, getPricingConfig, calculateCost, run_stop_errors
from util.translation_task import fail_on_parser_error, module_receipt, write_output
from util.sent_lines import SentLines
from util.speakers import find_speaker

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

def handleTyrano(filename, estimate):
    global ESTIMATE, TOKENS, FILENAME
    ESTIMATE = estimate
    FILENAME = filename

    # Translate
    start = time.time()
    translatedData = openFiles(filename)
    fail_on_parser_error(translatedData)

    # Translate
    if not estimate:
        write_output(filename, "".join(translatedData[0]), newline="\n")

    # Print File
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
    with open("files/" + filename, "r", encoding="utf8") as readFile:
        translatedData = parseTyrano(readFile, filename)

        # Delete lines marked for deletion
        finalData = []
        for line in translatedData[0]:
            if line != "\\d\n":
                finalData.append(line)
        translatedData[0] = finalData

    return translatedData


def parseTyrano(readFile, filename):
    global PBAR
    totalTokens = [0, 0]

    # Read File into data
    data = readFile.readlines()

    # Create Progress Bar
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE) as pbar:
        pbar.desc = filename
        PBAR = pbar

        try:
            result = translateTyrano(data, filename)
            totalTokens[0] += result[0]
            totalTokens[1] += result[1]
        except run_stop_errors():
            raise
        except Exception as e:
            traceback.print_exc()
            return [data, totalTokens, e]
    return [data, totalTokens, None]


def translateTyrano(data, filename):
    """Walks the lines once, joining each message's furigana and the lines it
    goes on over, and sends each message and choice with the place its reply
    goes (util/sent_lines), then writes each reply there."""
    tokens = [0, 0]
    speaker = ""
    dialogue = SentLines()
    choices = SentLines(unlabel=None)
    i = 0

    while i < len(data):
        lineRegexNoSpeaker = r"^([^\[#;*@\n]+)\[p\]|^([^\[#;*@\n]+)\[l\]\[[rp]\]|^([^\[#;*@\n]+)\[[rpl]\]|^([^\[#;*@_\n]+)\n$"
        # "#name", or "#name:face" with a face to show, which stays
        lineRegexSpeaker = r"^#([^:\n]*)"
        furiganaRegex = r"(\[ruby\stext=(.*?)\])"
        choiceRegex = r'\[glink.+?text="(.*?)"'

        # Speaker (util/speakers): "#" alone ends one
        found = find_speaker(lineRegexSpeaker, data[i])
        if found:
            response = getSpeaker(found.name)
            speaker = response[0]
            tokens[0] += response[1][0]
            tokens[1] += response[1][1]
            data[i] = found.written(speaker)

        # Furigana
        match = re.search(r"^\[ruby\stext", data[i])
        furiganaList = []
        if match:
            # Check next line and combine
            while match:
                furiganaList.append(data[i].replace("\n", ""))
                del data[i]
                match = re.search(r"^\[ruby\stext", data[i])
            jaString = "".join(furiganaList)

            # Ruby Text
            furiganaList = re.findall(furiganaRegex, jaString)
            for furigana in furiganaList:
                jaString = jaString.replace(furigana[0], furigana[1])

            data.insert(i, f"{jaString}[r]")

        # Dialogue
        match = re.search(lineRegexNoSpeaker, data[i])
        jaString = None
        if match:
            # Find which group matched
            for group_num in range(1, 5):
                try:
                    if match.group(group_num):
                        jaString = match.group(group_num)
                        break
                except IndexError:
                    break

            # Skip if no valid string found
            if not jaString:
                i += 1
                continue

            # Combine w/ next line if necessary
            repeatRegex = r"(.+?)\[[rpl]\]"
            if i + 1 < len(data):
                match = re.search(repeatRegex, data[i + 1])
                while match and "[p]" not in data[i]:
                    jaString = jaString + match.group(1)
                    jaString = jaString.replace("_　", "")
                    if "[p]" in data[i + 1]:
                        data[i] = f"{jaString}[p]\n"
                    else:
                        data[i] = jaString
                    del data[i + 1]
                    if i + 1 < len(data):
                        match = re.search(repeatRegex, data[i + 1])
                    else:
                        break

            originalString = jaString

            # The text sent: no textwrap, commands, ruby or spaces around it.
            # A line of spaces alone sends nothing (util/sent_lines).
            jaString = jaString.replace("[r]", " ")
            jaString = jaString.replace("[l]", "")
            furiganaList = re.findall(furiganaRegex, jaString)
            for furigana in furiganaList:
                jaString = jaString.replace(furigana[0], furigana[1])
            dialogue.send(jaString.strip(), partial(_write_dialogue, data, i, originalString), speaker)

        # Choices
        match = re.search(choiceRegex, data[i])
        if match:
            choices.send(match.group(1), partial(_write_choice, data, i, match.group(1)))
        i += 1

    # EOF
    if dialogue:
        PBAR.total = len(dialogue)
        PBAR.refresh()
    replies = [
        (lines, _translate(lines, history, tokens))
        for lines, history in (
            (dialogue, "Reply with the English Translation"),
            (choices, "Reply with the English TL of the Dialogue Choice"),
        )
        if lines
    ]
    for lines, translated in replies:
        lines.write(translated, MISMATCH, LOCK, FILENAME)
    return tokens


def _translate(lines, history, tokens):
    """The replies to *lines*, sent as one list with *history*; adds the
    request's tokens to *tokens*."""
    response = translateAI(lines.lines, history)
    tokens[0] += response[1][0]
    tokens[1] += response[1][1]
    return response[0]


def _write_dialogue(data, i, originalString, translatedText):
    """Writes a message's reply over its text, *originalString*, on line *i*."""
    # Avoid Crashes
    translatedText = translatedText.replace("[", "(")
    translatedText = translatedText.replace("]", ")")

    # Textwrap
    translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)
    translatedText = translatedText.replace("\n", "[r]")
    data[i] = data[i].replace(originalString, translatedText)


def _write_choice(data, i, sent, translatedText):
    """Writes a choice's reply over its text, *sent*, on line *i*."""
    translatedText = translatedText.replace(" ", "　")
    data[i] = data[i].replace(sent, translatedText)


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
