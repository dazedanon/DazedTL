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

def handleRegex(filename, estimate):
    global ESTIMATE, TOKENS, FILENAME
    ESTIMATE = estimate
    FILENAME = filename

    # Translate
    start = time.time()
    translatedData = openFiles(filename)
    fail_on_parser_error(translatedData)

    # Translate
    if not estimate:
        write_output(filename, "".join(translatedData[0]), encoding="utf-8-sig")

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
    with open("files/" + filename, "r", encoding="utf-8-sig") as readFile:
        translatedData = parseRegex(readFile, filename)

        # Delete lines marked for deletion
        finalData = []
        for line in translatedData[0]:
            if line != "\\d\n":
                finalData.append(line)
        translatedData[0] = finalData

    return translatedData


def parseRegex(readFile, filename):
    global PBAR
    totalTokens = [0, 0]

    # Read File into data
    data = readFile.readlines()

    # Create Progress Bar
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE) as pbar:
        pbar.desc = filename
        PBAR = pbar

        try:
            result = translateRegex(data, filename)
            totalTokens[0] += result[0]
            totalTokens[1] += result[1]
        except run_stop_errors():
            raise
        except Exception as e:
            traceback.print_exc()
            return [data, totalTokens, e]
    return [data, totalTokens, None]


# A chapter title, set as \setgamedatatitle("...") or title '...'
SETGAMEDATATITLE = r'\\setgamedatatitle\("(.+?)"\)'
TITLE = r"title\s'(.*)'$"
# A speaker, said by the dialogue after it (util/speakers)
SPEAKER = r'"name":\s?"(.+)",'
# Dialogue: a JSON "text" field, or the lines of a \text ... \endtext block
DIALOGUE = r'\"text\":\s?\"(.+)\",'
# Choices: the items of \sel(...), and a $menu_item's label
SEL = r'\\sel\((.+)\)'
CHOICE = r"\$menu_item.+?,(.*?),"


def translateRegex(data, filename):
    """Translates titles and speakers on the spot and walks the lines once,
    sending each dialogue line and choice with the place its reply goes
    (util/sent_lines), then writes each reply there."""
    global LOCK, ESTIMATE, FILENAME, PBAR, MISMATCH
    tokens = [0, 0]
    speaker = ""
    dialogue = SentLines()
    choices = SentLines(unlabel=None)
    i = 0

    while i < len(data):
        # Setgamedatatitle - Translate immediately (not batched)
        match = re.search(SETGAMEDATATITLE, data[i])
        if match:
            response = translateAI(
                match.group(1).replace('\\n', '\n'),
                f"Reply with the {LANGUAGE} translation of the chapter title",
                True,
            )
            tokens[0] += response[1][0]
            tokens[1] += response[1][1]

            # Convert newlines back to escape sequences and escape quotes
            title = response[0].replace('\n', '\\n').replace('"', '\\"')
            data[i] = data[i].replace(match.group(1), title)

        # Title - Translate immediately (not batched)
        match = re.search(TITLE, data[i])
        if match:
            response = translateAI(
                match.group(1),
                f"Reply with the {LANGUAGE} translation of the chapter title",
                True,
            )
            tokens[0] += response[1][0]
            tokens[1] += response[1][1]
            title = re.sub(r"(?<!\\)'", r"\\'", response[0])
            data[i] = data[i].replace(match.group(1), title)

        # Speaker (util/speakers)
        found = find_speaker(SPEAKER, data[i])
        if found:
            response = getSpeaker(found.name)
            speaker = response[0]
            tokens[0] += response[1][0]
            tokens[1] += response[1][1]
            data[i] = found.written(speaker)

        # Dialogue (JSON text field), which its speaker says alone
        match = re.search(DIALOGUE, data[i])
        if match:
            jaString = match.group(1).replace('\\n', ' ')
            dialogue.send(jaString, _field_writer(data, i, match.group(1)), speaker)
            speaker = ""

        # Sel (Selection menu)
        match = re.search(SEL, data[i])
        if match:
            items = [item.strip().strip('"') for item in match.group(1).split(',')]
            for item, write in zip(items, _sel_writers(data, i, items)):
                choices.send(item, write)

        # Dialogue: the lines of a \text block, sent as one
        if "\\text" in data[i].strip():
            i += 1
            start = i
            while "\\endtext" not in data[i].strip():
                i += 1
            jaString = "".join(data[start:i]).replace("\n", "").strip()
            dialogue.send(jaString, _block_writer(data, start, i), speaker)

        # Choices
        match = re.search(CHOICE, data[i])
        if match:
            choices.send(match.group(1), _choice_writer(data, i, match.group(1)))
        i += 1

    # EOF
    totalItems = len(dialogue) + len(choices)
    if totalItems > 0:
        PBAR.total = totalItems
        PBAR.refresh()
    replies = []
    for lines, history in (
        (dialogue, "Reply with the English Translation"),
        (choices, "Reply with the English TL of the Dialogue Choice"),
    ):
        if not lines:
            continue
        response = translateAI(lines.lines, history)
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        replies.append((lines, response[0]))
        if len(lines) != len(response[0]):
            with LOCK:
                found_mismatch(MISMATCH, FILENAME)

    # A short reply list still answers the lines it reaches
    for lines, translated in replies:
        lines.write(translated)
    return tokens


def _field_writer(data, i, sent):
    """Writes the reply to a "text" field on line *i* over the *sent* text."""

    def write(translatedText):
        translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)
        translatedText = translatedText.replace('\n', '\\n')

        # Escape Quotes (Required for JSON)
        translatedText = re.sub(r'(?<!\\)"', r'\\"', translatedText)
        data[i] = data[i].replace(sent, translatedText)

    return write


def _block_writer(data, start, end):
    """Writes the reply to a \\text block's lines *start* to *end* as the
    block's one line. Its other lines are emptied, not removed, so the lines
    after them keep their places for the replies written after it."""

    def write(translatedText):
        # Remove quotes and characters that may break scripts
        translatedText = re.sub(r'(?<!\\)"', r"", translatedText)
        translatedText = translatedText.replace("<", "(")
        translatedText = translatedText.replace(">", ")")

        translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)
        data[start:end] = [f"{translatedText}\n"] + [""] * (end - start - 1)

    return write


def _sel_writers(data, i, items):
    """A write for each of the *items* in the \\sel on line *i*. Each writes
    the list between the \\sel's parentheses again with its reply in its
    item's place, every item quoted and separated by "," alone. The list is
    found again on the line, whatever line breaks a reply put in it."""
    parts = [f'"{item}"' for item in items]

    def writer(index):
        def write(translatedText):
            parts[index] = '"' + translatedText.replace('"', '\\"') + '"'
            match = re.search(SEL, data[i], re.DOTALL)
            data[i] = data[i][: match.start(1)] + ",".join(parts) + data[i][match.end(1) :]

        return write

    return [writer(index) for index in range(len(items))]


def _choice_writer(data, i, sent):
    """Writes the reply to the $menu_item label *sent* on line *i*."""

    def write(translatedText):
        translatedText = translatedText.replace("\u3000", " ")

        # Escape Quotes
        translatedText = re.sub(r'(?<!\\)"', r'\\"', translatedText)
        translatedText = re.sub(r"(?<!\\)'", r"\\'", translatedText)
        data[i] = data[i].replace(sent, translatedText)

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
