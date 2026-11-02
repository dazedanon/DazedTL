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
from util.translation import TranslationConfig, translateAI as sharedtranslateAI, getPricingConfig, calculateCost, getPricingConfig, calculateCost, run_stop_errors
from util.translation_task import fail_on_parser_error, module_receipt, write_output
from util.sent_lines import SentLines
from util.speakers import find_speaker
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
PBAR = None
FILENAME = None

# tqdm Globals
BAR_FORMAT = "{l_bar}{bar:10}{r_bar}{bar:-10b}"
POSITION = 0
LEAVE = False

# Flags
SPEAKERS = True
CHOICES = True
DIALOGUE = True

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

def handleKirikiri(filename, estimate):
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
        end = time.time()
        fail_on_parser_error(translatedData)

        # A line the encoding can't write, or a write that fails, fails the
        # file (util/game_encoding). An empty file is not written.
        if translatedData[0]:
            lines = writable(translatedData[0], "cp932", filename)
            write_output(filename, "".join(lines), encoding="cp932", errors="ignore", newline="\n")

        tqdm.write(module_receipt(filename, translatedData[1], end - start, MODEL))
        with LOCK:
            TOKENS[0] += translatedData[1][0]
            TOKENS[1] += translatedData[1][1]

    return module_receipt("TOTAL", TOKENS, end - start, MODEL)


def openFiles(filename):
    with open("files/" + filename, "r", encoding="cp932") as readFile:
        translatedData = parseKiriKiri(readFile, filename)
    return translatedData


def parseKiriKiri(readFile, filename):
    global PBAR
    totalTokens = [0, 0]

    # Read File into data
    data = readFile.readlines()

    # Create Progress Bar
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE) as PBAR:
        PBAR.desc = filename

        try:
            result = translateKiriKiri(data, PBAR, filename)
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


def translateKiriKiri(data, pbar, filename):
    """Walks the lines once, translating each speaker on the spot and
    sending each choice and line of dialogue with the place its reply goes
    (util/sent_lines), then writes each reply there."""
    tokens = [0, 0]
    speaker = ""
    dialogue = SentLines()
    choices = SentLines(unlabel=None)
    i = 0

    # Regex
    speakerRegex = r"【(.*)】\[CR\]"
    dialogueRegex = r"^\[text\](.*).*\[KeyWait\]|\[\w+\](.*)\[\/\w+\].*\[KeyWait\]"
    furiganaRegex = r'(\[eruby\sstr="(.*?)"\stext.*?\])'
    choicesRegex = r"^\s*\[button\d\sclickse=sys_decide.*text='(.*?)'.*"
    taggedDialogueRegex = r"^\[(?P<tag>[^\s\]/]+)(?:\s[^\]]*)?\](?P<text>.*?)\[/\1\]"

    while i < len(data):
        speaker = ""
        # Speaker (util/speakers), saying the line after it
        found = find_speaker(speakerRegex, data[i]) if SPEAKERS else None
        if found:
            response = getSpeaker(found.name)
            speaker = response[0]
            tokens[0] += response[1][0]
            tokens[1] += response[1][1]
            data[i] = found.written(speaker)
            checkLine(data, i, filename)
            i += 1
            # A speaker right after it says the line instead
            if i == len(data) or find_speaker(speakerRegex, data[i]):
                continue

        # Choices
        match = re.search(choicesRegex, data[i])
        if match and CHOICES:
            jaString = match.group(1)
            choices.send(jaString, partial(_write_choice, data, i, jaString, filename))

        # Tagged dialogue lines e.g., [思考 storage="..."]text[/思考]
        tagged = re.match(taggedDialogueRegex, data[i])
        if tagged and DIALOGUE:
            tag_name = tagged.group('tag')
            jaString = tagged.group('text')

            # The tag names the speaker; the tag itself stays
            resolved = getSpeaker(tag_name)
            tag_speaker = resolved[0]
            tokens[0] += resolved[1][0]
            tokens[1] += resolved[1][1]

            # Remove inline wrapping
            jaString_clean = jaString.replace("[r]", " ")
            # Remove furigana
            matchList = re.findall(furiganaRegex, jaString_clean)
            if matchList:
                for fm in matchList:
                    jaString_clean = jaString_clean.replace(fm[0], fm[1])

            # The reply goes between the tags
            dialogue.send(
                jaString_clean.strip(),
                partial(_write_text, data, i, jaString, filename),
                tag_speaker,
            )

        # Simple narrative line handling: translate each whitespace-led, non-tag, non-command line independently.
        # This avoids reflowing or merging blocks, preventing misplaced text.
        if not re.match(r"^\[", data[i]) and not data[i].lstrip().startswith("@"):
            if re.match(r"^[ \t　]+", data[i]):
                # Skip standalone markers like [▼]
                if data[i].strip() == "[▼]":
                    pass
                else:
                    # The text sent: no wrapping, glyph markers or furigana.
                    # A line of spaces alone sends nothing (util/sent_lines).
                    line_content = data[i].rstrip("\n")
                    line_content = line_content.replace("[r]", " ")
                    line_content = re.sub(r"\[▼\]", "", line_content)
                    matchList = re.findall(furiganaRegex, line_content)
                    if matchList:
                        for fm in matchList:
                            line_content = line_content.replace(fm[0], fm[1])
                    dialogue.send(line_content.strip(), partial(_write_narration, data, i, filename))

        # Dialogue
        match = re.search(dialogueRegex, data[i])
        if match and DIALOGUE:
            jaString = match.group(1)
            if not jaString:
                jaString = match.group(2)

            # Remove any textwrap
            jaString_clean = jaString.replace("[r]", " ")

            # Remove Furigana
            matchList = re.findall(furiganaRegex, jaString_clean)
            if matchList:
                for fm in matchList:
                    jaString_clean = jaString_clean.replace(fm[0], fm[1])

            dialogue.send(
                jaString_clean.strip(),
                partial(_write_text, data, i, jaString, filename),
                speaker,
            )

        # Next Line
        i += 1

    # EOF
    replies = []
    for lines in (dialogue, choices):
        if lines:
            # Set Progress
            pbar.total = len(lines)
            pbar.refresh()

            # Translate
            response = translateAI(lines.lines, "", True)
            tokens[0] += response[1][0]
            tokens[1] += response[1][1]
            replies.append((lines, response[0]))

    # A line's choice is written before its other text, as the walk reads
    # its choice first
    for lines, translated in reversed(replies):
        lines.write(translated, MISMATCH, LOCK, filename)
    return tokens


def _write_choice(data, i, jaString, filename, translatedText):
    """Writes a choice's reply over its text, *jaString*, on line *i*."""
    # Replace Quotes
    data[i] = data[i].replace("'", '"')
    translatedText = translatedText.replace('"', "'")
    data[i] = data[i].replace(jaString, translatedText)
    checkLine(data, i, filename)


def _write_text(data, i, jaString, filename, translatedText):
    """Writes a reply over the text it was sent for, *jaString*, on line *i*,
    such as a [text] line's dialogue or the text between a tag's pair."""
    # Textwrap
    translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)
    translatedText = translatedText.replace("\n", "[r]")

    # Replace Quotes
    data[i] = data[i].replace("'", '"')
    translatedText = translatedText.replace('"', "'")
    data[i] = data[i].replace(jaString, translatedText)
    checkLine(data, i, filename)


def _write_narration(data, i, filename, translatedText):
    """Writes a reply as narration line *i*, after the line's indent."""
    translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)
    translatedText = translatedText.replace("\n", "[r]")
    indent_match = re.match(r"^([ \t　]+)", data[i])
    indent = indent_match.group(1) if indent_match else ""
    data[i] = f"{indent}{translatedText}\n"
    checkLine(data, i, filename)


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
