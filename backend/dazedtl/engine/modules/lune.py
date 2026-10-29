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
        start = time.time()
        translatedData = openFiles(filename)
        fail_on_parser_error(translatedData)

        # Print Result
        end = time.time()
        write_output(filename, json.dumps(translatedData[0], ensure_ascii=False, indent=4), newline="\n")
        tqdm.write(module_receipt(filename, translatedData[1], end - start, MODEL))
        with LOCK:
            TOKENS[0] += translatedData[1][0]
            TOKENS[1] += translatedData[1][1]

    return module_receipt("TOTAL", TOKENS, end - start, MODEL)


def openFiles(filename):
    """Reads a Lune file, a JSON list of name and message entries, whatever
    its name: the engine offers ``.l`` files (util/translation_task)."""
    with open("files/" + filename, "r", encoding="UTF-8-sig") as f:
        data = json.load(f)
    return parseJSON(data, filename)


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


# The text fields of an entry with a message, in the order they are sent
TEXT_FIELDS = ("text", "text2", "help1", "help2", "help3", "like", "message", "me")


def translateJSON(data, pbar):
    """Walks the entries once: translates each name on the spot and sends
    the text fields in batches of BATCHSIZE, writing each reply line to the
    entry and field its source line came from."""
    global PBAR
    PBAR = pbar
    tokens = [0, 0]
    history = []
    batch = []  # Source lines waiting to be sent
    slots = []  # The (entry index, field) each line in batch came from

    def send():
        nonlocal history, batch, slots
        response = translateAI(batch, history)
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        translatedBatch = response[0]
        history = batch[-10:]

        if len(batch) == len(translatedBatch):
            for (index, field), translatedText in zip(slots, translatedBatch):
                # Remove added speaker
                translatedText = re.sub(r"^.+?:\s", "", translatedText)
                data[index][field] = dazedwrap.wrapText(translatedText, width=WIDTH)

        # Mismatch: the batch keeps its source text
        else:
            pbar.write(f"Mismatch: {slots[0][0]} - {slots[-1][0]}")
            MISMATCH.append(batch)
            report_mismatch(FILENAME)
        batch, slots = [], []

    for index, item in enumerate(data):
        # Speaker
        if "name" in item and item["name"] not in [None, "-"]:
            response = getSpeaker(item["name"])
            tokens[0] += response[1][0]
            tokens[1] += response[1][1]
            item["name"] = response[0]

        # Text
        if "message" not in item:
            continue
        for field in TEXT_FIELDS:
            if item.get(field) is None:
                continue
            jaString = item[field]

            # Remove any textwrap
            if FIXTEXTWRAP:
                jaString = jaString.replace("\n", " ")

            batch.append(jaString)
            slots.append((index, field))
            if len(batch) == BATCHSIZE:
                send()

    # The last batch
    if batch:
        send()
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
