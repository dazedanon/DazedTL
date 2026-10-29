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
from util.translation import TranslationConfig, translateAI as sharedtranslateAI, getPricingConfig, calculateCost, report_mismatch, run_stop_errors
from util.translation_task import fail_on_parser_error, module_receipt
import tempfile
from util import system

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
PBAR = None
FILENAME = None

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

def handleLune(filename, estimate):
    global FILENAME, ESTIMATE, totalTokens
    ESTIMATE = estimate
    FILENAME = filename

    if estimate:
        start = time.time()
        translatedData = openFiles(filename)
        fail_on_parser_error(translatedData)

        # Print Result
        end = time.time()
        tqdm.write(module_receipt(filename, translatedData[1], end - start, MODEL))
        with LOCK:
            TOKENS[0] += translatedData[1][0]
            TOKENS[1] += translatedData[1][1]

        return module_receipt("TOTAL", TOKENS, end - start, MODEL)

    else:
        with open("translated/" + filename, "w", encoding="utf-8", newline="\n") as outFile:
            start = time.time()
            translatedData = openFiles(filename)
            fail_on_parser_error(translatedData)

            # Print Result
            end = time.time()
            json.dump(translatedData[0], outFile, ensure_ascii=False, indent=4)
            tqdm.write(module_receipt(filename, translatedData[1], end - start, MODEL))
            with LOCK:
                TOKENS[0] += translatedData[1][0]
                TOKENS[1] += translatedData[1][1]

    return module_receipt("TOTAL", TOKENS, end - start, MODEL)


def openFiles(filename):
    with open("files/" + filename, "r", encoding="UTF-8-sig") as f:
        data = json.load(f)

        # Map Files
        if ".json" in filename:
            translatedData = parseJSON(data, filename)

        else:
            raise NameError(filename + " Not Supported")

    return translatedData


def parseJSON(data, filename):
    totalTokens = [0, 0]
    totalLines = 0
    totalLines = len(data)
    global LOCK

    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
        pbar.desc = filename
        pbar.total = totalLines
        try:
            result = translateJSON(data, pbar)
            totalTokens[0] += result[0]
            totalTokens[1] += result[1]
        except run_stop_errors():
            raise
        except Exception as e:
            return [data, totalTokens, e]
    return [data, totalTokens, None]


def save_progress_json(data, filename):
    """Atomically save current JSON translation progress."""
    try:
        if ESTIMATE:
            return
        os.makedirs("translated", exist_ok=True)
        tmp_fd, tmp_path = tempfile.mkstemp(prefix=f"{filename}.", suffix=".tmp", dir="translated")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8", newline="\n") as tmp_file:
                json.dump(data, tmp_file, ensure_ascii=False, indent=4)
            system.replace(tmp_path, os.path.join("translated", filename))
        finally:
            if os.path.exists(tmp_path):
                system.unlink(tmp_path, ignore_errors=True)
    except Exception:
        traceback.print_exc()


def translateJSON(data, pbar):
    global PBAR
    PBAR = pbar
    textHistory = []
    batch = []
    maxHistory = MAXHISTORY
    tokens = [0, 0]
    speaker = "None"
    insertBool = False
    i = 0
    batchStartIndex = 0

    while i < len(data):
        item = data[i]
        # Speaker
        if "name" in item:
            if item["name"] not in [None, "-"]:
                response = getSpeaker(item["name"])
                speaker = response[0]
                tokens[0] += response[1][0]
                tokens[1] += response[1][1]
                item["name"] = speaker
                save_progress_json(data, FILENAME or "output.json")
            else:
                speaker = "None"

        # Text
        if "message" in item:
            for text in [
                "text",
                "text2",
                "help1",
                "help2",
                "help3",
                "like",
                "message",
                "me",
            ]:
                if text in item:
                    if item[text] != None:
                        jaString = item[text]

                        # Remove any textwrap
                        if FIXTEXTWRAP == True:
                            finalJAString = jaString.replace("\n", " ")

                        # [Passthrough 1] Pulling From File
                        if insertBool is False:
                            # Append to List and Clear Values
                            batch.append(finalJAString)
                            speaker = ""

                            # Translate Batch if Full
                            if len(batch) == BATCHSIZE:
                                # Translate
                                response = translateAI(batch, textHistory)
                                tokens[0] += response[1][0]
                                tokens[1] += response[1][1]
                                translatedBatch = response[0]
                                textHistory = batch[-10:]

                                # Set Values
                                if len(batch) == len(translatedBatch):
                                    i = batchStartIndex
                                    insertBool = True

                                # Mismatch
                                else:
                                    pbar.write(f"Mismatch: {batchStartIndex} - {i}")
                                    MISMATCH.append(batch)
                                    report_mismatch(FILENAME)
                                    batchStartIndex = i
                                    batch.clear()

                            if insertBool is False:
                                i += 1

                            currentGroup = []

                        # [Passthrough 2] Setting Data
                        else:
                            # Get Text
                            translatedText = translatedBatch[0]

                            # Remove added speaker
                            translatedText = re.sub(r"^.+?:\s", "", translatedText)

                            # Textwrap
                            translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)

                            # Set Text
                            item[text] = translatedText
                            save_progress_json(data, FILENAME or "output.json")
                            translatedBatch.pop(0)
                            speaker = ""
                            currentGroup = []
                            i += 1

                            # If Batch is empty. Move on.
                            if len(translatedBatch) == 0:
                                insertBool = False
                                batchStartIndex = i
                                batch.clear()
        else:
            i += 1

        # Translate Batch if not empty and EOF
        if len(batch) != 0 and i >= len(data):
            # Translate
            response = translateAI(batch, textHistory)
            tokens[0] += response[1][0]
            tokens[1] += response[1][1]
            translatedBatch = response[0]
            textHistory = batch[-10:]

            # Set Values
            if len(batch) == len(translatedBatch):
                i = batchStartIndex
                insertBool = True

            # Mismatch
            else:
                pbar.write(f"Mismatch: {batchStartIndex} - {i}")
                MISMATCH.append(batch)
                report_mismatch(FILENAME)
                batchStartIndex = i
                batch.clear()

            currentGroup = []
            # After applying a batch, persist progress
            save_progress_json(data, FILENAME or "output.json")
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
