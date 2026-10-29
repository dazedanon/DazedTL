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
from util.speakers import strip_speaker_prefix

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
            result = translateTyrano(data, filename, [])
            totalTokens[0] += result[0]
            totalTokens[1] += result[1]
        except run_stop_errors():
            raise
        except Exception as e:
            traceback.print_exc()
            return [data, totalTokens, e]
    return [data, totalTokens, None]


def translateTyrano(data, filename, translatedList):
    if translatedList:
        stringList = translatedList[0]
        choiceList = translatedList[1]
    else:
        stringList = []
        choiceList = []
    tokens = [0, 0]
    speaker = ""
    stringListTL = []
    choiceListTL = []
    global LOCK, ESTIMATE, FILENAME, PBAR, MISMATCH
    i = 0

    while i < len(data):
        voice = False
        lineRegexNoSpeaker = r"^([^\[#;*@\n]+)\[p\]|^([^\[#;*@\n]+)\[l\]\[[rp]\]|^([^\[#;*@\n]+)\[[rpl]\]|^([^\[#;*@_\n]+)\n$"
        lineRegexSpeaker = r"^#(.*)"
        furiganaRegex = r"(\[ruby\stext=(.*?)\])"
        choiceRegex = r'\[glink.+?text="(.*?)"'

        # Speaker, translated in pass 1 only: pass 2 finds the name it wrote
        match = re.search(lineRegexSpeaker, data[i])
        if match and not translatedList:
            if match.group(1):
                response = getSpeaker(match.group(1))
                speaker = response[0]
                tokens[0] += response[1][0]
                tokens[1] += response[1][1]
                data[i] = data[i].replace(match.group(1), speaker)
            else:
                speaker = None

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

            # Pass 1
            if not translatedList:
                # Remove any textwrap and commands
                jaString = jaString.replace("[r]", " ")
                jaString = jaString.replace("[l]", "")

                # Ruby Text
                furiganaList = re.findall(furiganaRegex, jaString)
                for furigana in furiganaList:
                    jaString = jaString.replace(furigana[0], furigana[1])

                # Strip Spaces
                jaString = jaString.strip()

                if jaString:
                    if speaker:
                        stringList.append(f"[{speaker}]: {jaString}")
                    else:
                        stringList.append(jaString)

            # Pass 2
            else:
                # Get Text
                if stringList:
                    # Grab and Pop
                    translatedText = stringList[0]
                    stringList.pop(0)

                    # Set to None if empty list
                    if len(stringList) <= 0:
                        stringList = None

                    # Remove speaker
                    translatedText = strip_speaker_prefix(translatedText)

                    # Avoid Crashes
                    translatedText = translatedText.replace("[", "(")
                    translatedText = translatedText.replace("]", ")")

                    # Textwrap
                    translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)
                    translatedText = translatedText.replace("\n", "[r]")

                    # Set Data
                    data[i] = data[i].replace(originalString, translatedText)

        # Choices
        match = re.search(choiceRegex, data[i])
        if match:
            # Pass 1
            if not translatedList:
                choiceList.append(match.group(1))
                match = re.search(choiceRegex, data[i + 1])

            # Pass 2
            else:
                # Grab and Pop
                translatedText = choiceList[0]
                choiceList.pop(0)

                # Replace Spaces
                translatedText = translatedText.replace(" ", "\u3000")

                # Set
                data[i] = data[i].replace(match.group(1), translatedText)

            i += 1
        else:
            i += 1

    # EOF
    if not translatedList:
        # String List
        if stringList:
            PBAR.total = len(stringList)
            PBAR.refresh()
            response = translateAI(stringList, "Reply with the English Translation")
            tokens[0] += response[1][0]
            tokens[1] += response[1][1]
            stringListTL = response[0]

            if len(stringList) != len(stringListTL):
                # Mismatch
                with LOCK:
                    found_mismatch(MISMATCH, FILENAME)

        # Choice List
        if choiceList:
            response = translateAI(choiceList, "Reply with the English TL of the Dialogue Choice")
            tokens[0] += response[1][0]
            tokens[1] += response[1][1]
            choiceListTL = response[0]

            if len(choiceList) != len(choiceListTL):
                # Mismatch
                with LOCK:
                    found_mismatch(MISMATCH, FILENAME)

        # Recursive call for Pass 2 with translated strings
        result = translateTyrano(data, filename, [stringListTL, choiceListTL])
        tokens[0] += result[0]
        tokens[1] += result[1]
    
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
