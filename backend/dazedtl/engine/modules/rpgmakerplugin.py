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

def handlePlugin(filename, estimate):
    global ESTIMATE, PBAR, FILENAME
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
        write_output(filename, "".join(translatedData[0]), encoding="utf_8", errors="ignore", newline="\n")

        # Print Result
        end = time.time()
        tqdm.write(module_receipt(filename, translatedData[1], end - start, MODEL))
        with LOCK:
            TOKENS[0] += translatedData[1][0]
            TOKENS[1] += translatedData[1][1]

    return module_receipt("TOTAL", TOKENS, end - start, MODEL)


def openFiles(filename):
    with open("files/" + filename, "r", encoding="utf_8") as readFile:
        translatedData = parsePlugin(readFile, filename)

        # Delete lines marked for deletion
        finalData = []
        for line in translatedData[0]:
            if line != "\\d\n":
                finalData.append(line)
        translatedData[0] = finalData

    return translatedData


def parsePlugin(readFile, filename):
    global PBAR
    totalTokens = [0, 0]

    # Read File into data
    data = readFile.readlines()

    # Create Progress Bar
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE) as pbar:
        pbar.desc = filename
        PBAR = pbar

        try:
            result = translatePlugin(data, pbar, filename, [])
            totalTokens[0] += result[0]
            totalTokens[1] += result[1]
        except run_stop_errors():
            raise
        except Exception as e:
            traceback.print_exc()
            return [data, totalTokens, e]
    return [data, totalTokens, None]


# An escaped line break: a backslash run and n, one more level of escaping per
# level of nesting. Before [ and a number or code it is the actor name code
# \n[1] or \n[\v[1]], and before < a name box \n<Alice>, which stay.
ESCAPED_NEWLINE = re.compile(r"\\+n(?!\[[\d\\]|<)")


def escapedNewline(text):
    """The escaped line break a plugin string uses, as its backslashes and n,
    or None."""
    found = ESCAPED_NEWLINE.search(text)
    return found.group(0) if found else None


def unwrapped(text):
    """The text with each escaped line break read as a space."""
    return ESCAPED_NEWLINE.sub(" ", text)


# A color code \c[2] or \C[2]: a backslash run before c or C and [, with the
# same depth of escaping as an escaped line break. It is sent with one
# backslash and written back at the depth its source uses.
ESCAPED_COLOR = re.compile(r"\\+(?=[cC]\[)")


def colorDepth(text):
    """The backslashes a plugin string's color codes use, or None."""
    found = ESCAPED_COLOR.search(text)
    return found.group(0) if found else None


def atColorDepth(text, backslashes):
    """The text with each color code's backslashes set to backslashes."""
    return ESCAPED_COLOR.sub(lambda _found: backslashes, text)


def translatePlugin(data, pbar, filename, translatedList):
    if len(translatedList) > 0:
        questList = translatedList[0]
        custom = translatedList[1]
        sceneMenuText = translatedList[2] if len(translatedList) > 2 else []
        sceneMenuCommonHelpText = translatedList[3] if len(translatedList) > 3 else []
        sceneMenuHelpText = translatedList[4] if len(translatedList) > 4 else []
        sceneMenuDrawText = translatedList[5] if len(translatedList) > 5 else []
        sceneMenuStatLabel = translatedList[6] if len(translatedList) > 6 else []
        saveParamName = translatedList[7] if len(translatedList) > 7 else []
        setData = True
    else:
        questList = [[], [], [], [], [], []]
        custom = []
        sceneMenuText = []
        sceneMenuCommonHelpText = []
        sceneMenuHelpText = []
        sceneMenuDrawText = []
        sceneMenuStatLabel = []
        saveParamName = []
        setData = False
    currentGroup = []
    tokens = [0, 0]
    speaker = ""
    voice = False
    global LOCK, ESTIMATE
    i = 0
    in_disp_list = False
    brace_count = 0
    _pending_drawtext = {}   # Deferred drawTextEx brace label replacements (longest-first)
    _pending_statlabel = {}  # Deferred drawTextEx stat label replacements (longest-first)

    # Category
    with open("log/translations.txt", "a+", encoding="utf-8") as tlFile:
                tlFile.write(f"\nCustom:\n")
                tlFile.close()

    while i < len(data):
        voice = False
        speaker = ""

        # Track if we're inside CBR_travel_data block
        if 'data_map_name_list' in data[i]:
            in_disp_list = True
            brace_count = 0
        
        if in_disp_list:
            # Count braces to know when we exit the object
            brace_count += data[i].count('{') - data[i].count('}')
            if brace_count < 0:
                in_disp_list = False

        # Nested array strings (e.g., this.disp_list = { key: { subkey: ["string1", "string2"] } })
        # Matches strings inside arrays within object literals
        if in_disp_list:
            regex_nested = source_pattern("disp_list")
            matchList = re.findall(regex_nested, data[i])
            if len(matchList) > 0:
                for match in matchList:
                    # Save Original String
                    jaString = match
                    originalString = jaString

                    # Replace \n for translation
                    jaStringClean = unwrapped(jaString)

                    if jaStringClean.strip():
                        # Pass 1
                        if setData == False:
                            custom.append(jaStringClean.strip())

                        # Pass 2
                        else:
                            if custom:
                                # Grab and Pop
                                translatedText = custom[0]
                                custom.pop(0)

                                # Set to None if empty list
                                if len(custom) <= 0:
                                    custom = []

                                # Restore original newlines but keep translated text
                                newline = escapedNewline(jaString)
                                if newline:
                                    # Textwrap the translation
                                    translatedText = dazedwrap.wrapText(translatedText, 50)
                                    translatedText = translatedText.replace("\n", newline)

                                # Escape quotes in translation
                                translatedText = translatedText.replace('"', '\\"')

                                # Set Data
                                data[i] = data[i].replace(f'"{originalString}"', f'"{translatedText}"')

        # Custom
        # Useful Regex's
        # r'"Text[\\]+":[\\]+"(.+?)[\\]+",'
        # r'"HelpText[\\]+":[\\]+"(.+?)[\\]+",'
        # r"this.drawTextEx\(\\'(.+?)\',"
        # r'txtSubject.+?"(.+)"'
        regex = r'txtSubject.+?"(.+)"'
        matchList = re.findall(regex, data[i])
        if len(matchList) > 0:
            for match in matchList:
                # Save Original String
                jaString = match
                originalString = jaString

                # Make sure it contains Japanese
                if not re.search(LANGREGEX, jaString):
                    continue

                # Make sure didn't grab \\
                if re.search(r"^[\\]+$", jaString):
                    continue

                # Replace \n and \c
                newline = escapedNewline(jaString)
                colors = colorDepth(jaString)
                jaString = atColorDepth(jaString, "\\")

                # Remove any textwrap
                jaString = unwrapped(jaString)

                if jaString.replace("\u3000", "") and jaString:
                    # Pass 1
                    if setData == False and jaString.strip():
                        custom.append(jaString.strip())

                    # Pass 2
                    else:
                        if custom:
                            # Grab and Pop
                            translatedText = custom[0]
                            custom.pop(0)

                            # Replace Single Quotes
                            translatedText = re.sub(r"([^\\'])'", r"\1՚", translatedText)
                            translatedText = re.sub(r"([^\\'])\"", r"\1՚", translatedText)

                            # Replace \n and \c
                            if newline:
                                # Textwrap
                                # translatedText = dazedwrap.wrapText(translatedText, WIDTH)
                                translatedText = re.sub(r"\n", re.escape(newline), translatedText)
                            else:
                                # A raw line break would end the JS string
                                translatedText = translatedText.replace("\n", " ")
                            if colors:
                                translatedText = atColorDepth(translatedText, colors)

                            # Set Data
                            with open("log/translations.txt", "a+", encoding="utf-8") as tlFile:
                                tlFile.write(f"{originalString} ({translatedText})\n")
                            data[i] = data[i].replace(originalString, translatedText)

        # Quest Name
        regex = r'[\\]+"QuestName[\\]+":[\\]+"(.*?)[\\]+"'
        matchList = re.findall(regex, data[i])
        if len(matchList) > 0:
            for match in matchList:
                if match:
                    # Save Original String
                    originalString = match

                    # Remove any textwrap
                    match = unwrapped(match)

                    # Pass 1
                    if setData == False:
                        # Add String
                        if match != "\\\\\\\\":
                            questList[0].append(match.strip())

                    # Pass 2
                    else:
                        if questList[0]:
                            # Grab and Pop
                            translatedText = questList[0][0]
                            questList[0].pop(0)

                            # Replace Single Quotes
                            translatedText = translatedText.replace('"', "'")
                            translatedText = re.sub(r"([^\\'])'", r"\1\\'", translatedText)

                            # Set Data
                            data[i] = data[i].replace(originalString, translatedText)

        # Quest Client
        regex = r'QuestClientName[\\]+":[\\]+"(.*?)[\\]+"'
        matchList = re.findall(regex, data[i])
        if len(matchList) > 0:
            for match in matchList:
                if match:
                    # Save Original String
                    originalString = match

                    # Remove any textwrap
                    match = unwrapped(match)

                    # Pass 1
                    if setData == False:
                        # Add String
                        if match != "\\\\\\\\":
                            questList[1].append(match.strip())

                    # Pass 2
                    else:
                        if questList[1]:
                            # Grab and Pop
                            translatedText = questList[1][0]
                            questList[1].pop(0)

                            # Replace Single Quotes
                            translatedText = translatedText.replace('"', "'")
                            translatedText = re.sub(r"([^\\'])'", r"\1\\'", translatedText)

                            # Set Data
                            data[i] = data[i].replace(originalString, translatedText)

        # Quest Location
        regex = r'QuestLocation[\\]+":[\\]+"(.*?)[\\]+"'
        matchList = re.findall(regex, data[i])
        if len(matchList) > 0:
            for match in matchList:
                if match:
                    # Save Original String
                    originalString = match

                    # Remove any textwrap
                    match = unwrapped(match)

                    # Pass 1
                    if setData == False:
                        # Add String
                        if match != "\\\\\\\\":
                            questList[2].append(match.strip())

                    # Pass 2
                    else:
                        if questList[2]:
                            # Grab and Pop
                            translatedText = questList[2][0]
                            questList[2].pop(0)

                            # Replace Single Quotes
                            translatedText = translatedText.replace('"', "'")
                            translatedText = re.sub(r"([^\\'])'", r"\1\\'", translatedText)

                            # Set Data
                            data[i] = data[i].replace(originalString, translatedText)

        # Quest Target
        regex = r'PlaceInformation[\\]+":[\\]+"(.*?)[\\]+"'
        matchList = re.findall(regex, data[i])
        if len(matchList) > 0:
            for match in matchList:
                if match:
                    # Save Original String
                    originalString = match

                    # Remove any textwrap
                    match = unwrapped(match)

                    # Pass 1
                    if setData == False:
                        # Add String
                        if match != "\\\\\\\\":
                            questList[3].append(match.strip())

                    # Pass 2
                    else:
                        if questList[3]:
                            # Grab and Pop
                            translatedText = questList[3][0]
                            questList[3].pop(0)

                            # Replace Single Quotes
                            translatedText = translatedText.replace('"', "'")
                            translatedText = re.sub(r"([^\\'])'", r"\1\\'", translatedText)

                            # Set Data
                            data[i] = data[i].replace(originalString, translatedText)

        # Quest Summary
        regex = r'[\\]+"QuestContent[\\]+":[\\]+"[\\]+"(.*?)[\\]+"[\\]+"'
        matchList = re.findall(regex, data[i])
        if len(matchList) > 0:
            for match in matchList:
                if match:
                    # Save Original String
                    originalString = match

                    # Remove any textwrap
                    match = atColorDepth(unwrapped(match), "\\")

                    # Pass 1
                    if setData == False:
                        # Add String
                        if match != "\\\\\\\\":
                            questList[4].append(match.strip())

                    # Pass 2
                    else:
                        if questList[4]:
                            # Grab and Pop
                            translatedText = questList[4][0]
                            questList[4].pop(0)

                            # Textwrap
                            translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)
                            newline = escapedNewline(originalString) or r"\\\\\\\\n"
                            translatedText = translatedText.replace("\n", newline)
                            colors = colorDepth(originalString)
                            if colors:
                                translatedText = atColorDepth(translatedText, colors)

                            # Replace Single Quotes
                            translatedText = translatedText.replace('"', "'")
                            translatedText = re.sub(r"([^\\'])'", r"\1\\'", translatedText)

                            # Set Data
                            data[i] = data[i].replace(originalString, translatedText)

        # Quest Goal 1
        regex = r'ObjectiveContent[\\]+":[\\]+"[\\]+"(.*?)[\\]+"'
        matchList = re.findall(regex, data[i])
        if len(matchList) > 0:
            for match in matchList:
                if match:
                    # Save Original String
                    originalString = match

                    # Remove any textwrap
                    match = unwrapped(match)

                    # Pass 1
                    if setData == False:
                        # Add String
                        if match != "\\\\\\\\":
                            questList[5].append(match.strip())

                    # Pass 2
                    else:
                        if questList[5]:
                            # Grab and Pop
                            translatedText = questList[5][0]
                            questList[5].pop(0)

                            # Textwrap
                            translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)
                            newline = escapedNewline(originalString) or (
                                r"\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\n"
                            )
                            translatedText = translatedText.replace("\n", newline)

                            # Replace Single Quotes
                            translatedText = translatedText.replace('"', "'")
                            translatedText = re.sub(r"([^\\'])'", r"\1\\'", translatedText)

                            # Set Data
                            data[i] = data[i].replace(originalString, translatedText)

        # SceneCustomMenu - Text (Command Labels)
        regex = r'[\\]+"Text[\\]+":[\\]+"(.+?)[\\]+"'
        matchList = re.findall(regex, data[i])
        if len(matchList) > 0:
            for match in matchList:
                if match:
                    jaString = match
                    originalString = jaString

                    # Make sure it contains Japanese
                    if not re.search(LANGREGEX, jaString):
                        continue

                    # Make sure didn't grab only backslashes
                    if re.search(r"^[\\]+$", jaString):
                        continue

                    if jaString.replace("\u3000", "").strip():
                        # Pass 1
                        if setData == False:
                            sceneMenuText.append(jaString.strip())

                        # Pass 2
                        else:
                            if sceneMenuText:
                                # Grab and Pop
                                translatedText = sceneMenuText[0]
                                sceneMenuText.pop(0)

                                # Replace quotes
                                translatedText = translatedText.replace('"', "'")
                                translatedText = re.sub(r"([^\\'])'" , r"\1\\'", translatedText)

                                # Set Data
                                data[i] = data[i].replace(originalString, translatedText)

        # SceneCustomMenu - CommonHelpText
        regex = r'[\\]+"CommonHelpText[\\]+":[\\]+"(.+?)[\\]+"'
        matchList = re.findall(regex, data[i])
        if len(matchList) > 0:
            for match in matchList:
                if match:
                    jaString = match
                    originalString = jaString

                    # Make sure it contains Japanese
                    if not re.search(LANGREGEX, jaString):
                        continue

                    # Make sure didn't grab only backslashes
                    if re.search(r"^[\\]+$", jaString):
                        continue

                    if jaString.replace("\u3000", "").strip():
                        # Pass 1
                        if setData == False:
                            sceneMenuCommonHelpText.append(jaString.strip())

                        # Pass 2
                        else:
                            if sceneMenuCommonHelpText:
                                # Grab and Pop
                                translatedText = sceneMenuCommonHelpText[0]
                                sceneMenuCommonHelpText.pop(0)

                                # Replace quotes
                                translatedText = translatedText.replace('"', "'")
                                translatedText = re.sub(r"([^\\'])'" , r"\1\\'", translatedText)

                                # Set Data
                                data[i] = data[i].replace(originalString, translatedText)

        # SceneCustomMenu - HelpText (Command Help)
        regex = r'[\\]+"HelpText[\\]+":[\\]+"(.+?)[\\]+"'
        matchList = re.findall(regex, data[i])
        if len(matchList) > 0:
            for match in matchList:
                if match:
                    jaString = match
                    originalString = jaString

                    # Make sure it contains Japanese
                    if not re.search(LANGREGEX, jaString):
                        continue

                    # Make sure didn't grab only backslashes
                    if re.search(r"^[\\]+$", jaString):
                        continue

                    if jaString.replace("\u3000", "").strip():
                        # Pass 1
                        if setData == False:
                            sceneMenuHelpText.append(jaString.strip())

                        # Pass 2
                        else:
                            if sceneMenuHelpText:
                                # Grab and Pop
                                translatedText = sceneMenuHelpText[0]
                                sceneMenuHelpText.pop(0)

                                # Replace quotes
                                translatedText = translatedText.replace('"', "'")
                                translatedText = re.sub(r"([^\\'])'" , r"\1\\'", translatedText)

                                # Set Data
                                data[i] = data[i].replace(originalString, translatedText)

        # NUUN_SaveScreen - ParamName (save screen labels like 現在地, プレイ時間, 所持金)
        regex = r'[\\]+"ParamName[\\]+":[\\]+"(.+?)[\\]+"'
        matchList = re.findall(regex, data[i])
        if len(matchList) > 0:
            for match in matchList:
                if match:
                    jaString = match
                    originalString = jaString

                    # Make sure it contains Japanese
                    if not re.search(LANGREGEX, jaString):
                        continue

                    # Make sure didn't grab only backslashes
                    if re.search(r"^[\\]+$", jaString):
                        continue

                    if jaString.replace("\u3000", "").strip():
                        # Pass 1
                        if setData == False:
                            saveParamName.append(jaString.strip())

                        # Pass 2
                        else:
                            if saveParamName:
                                # Grab and Pop
                                translatedText = saveParamName[0]
                                saveParamName.pop(0)

                                # Replace quotes
                                translatedText = translatedText.replace('"', "'")
                                translatedText = re.sub(r"([^\\'])'" , r"\1\\'", translatedText)

                                # Set Data
                                data[i] = data[i].replace(originalString, translatedText)

        # DrawTextEx - Brace-delimited labels (e.g., \}【口づけ】\{, \}回数：\{)
        # Only process lines containing drawTextEx calls
        if 'drawTextEx' in data[i]:
            regex = r'[\\]+\}(.+?)[\\]+\{'
            matchList = re.findall(regex, data[i])
            if len(matchList) > 0:
                for match in matchList:
                    if match:
                        jaString = match
                        originalString = jaString

                        # Skip game variable references (handled separately)
                        if '$gameVariables' in jaString:
                            continue

                        # Make sure it contains Japanese
                        if not re.search(LANGREGEX, jaString):
                            continue

                        if jaString.replace("\u3000", "").strip():
                            # Pass 1 (deduplicated)
                            if setData == False:
                                if jaString.strip() not in sceneMenuDrawText:
                                    sceneMenuDrawText.append(jaString.strip())

                            # Pass 2 (collect mapping, skip duplicates)
                            else:
                                if sceneMenuDrawText and originalString not in _pending_drawtext:
                                    # Grab and Pop
                                    translatedText = sceneMenuDrawText[0]
                                    sceneMenuDrawText.pop(0)

                                    # Replace quotes
                                    translatedText = translatedText.replace('"', "'")

                                    # Queue for deferred replacement
                                    _pending_drawtext[originalString] = translatedText

            # Apply deferred replacements longest-first to avoid substring collisions
            # (e.g., replacing 回数： before 使用回数： would corrupt the longer string)
            if setData and _pending_drawtext:
                for orig in sorted(_pending_drawtext, key=len, reverse=True):
                    data[i] = data[i].replace(orig, _pending_drawtext[orig])
                _pending_drawtext.clear()

        # DrawTextEx - Stat labels (e.g., C[16]攻撃力\\...C[0])
        if 'drawTextEx' in data[i]:
            regex = r'C\[\d+\]([^C\\,`\[\]]+?)[\\]+C\[0\]'
            matchList = re.findall(regex, data[i])
            if len(matchList) > 0:
                for match in matchList:
                    if match:
                        jaString = match
                        originalString = jaString

                        # Make sure it contains Japanese
                        if not re.search(LANGREGEX, jaString):
                            continue

                        if jaString.replace("\u3000", "").strip():
                            # Pass 1 (deduplicated)
                            if setData == False:
                                if jaString.strip() not in sceneMenuStatLabel:
                                    sceneMenuStatLabel.append(jaString.strip())

                            # Pass 2 (collect mapping, skip duplicates)
                            else:
                                if sceneMenuStatLabel and originalString not in _pending_statlabel:
                                    # Grab and Pop
                                    translatedText = sceneMenuStatLabel[0]
                                    sceneMenuStatLabel.pop(0)

                                    # Queue for deferred replacement
                                    _pending_statlabel[originalString] = translatedText

            # Apply deferred replacements longest-first to avoid substring collisions
            if setData and _pending_statlabel:
                for orig in sorted(_pending_statlabel, key=len, reverse=True):
                    data[i] = data[i].replace(orig, _pending_statlabel[orig])
                _pending_statlabel.clear()

        # DrawTextEx - Game variable counter word (hardcoded: 回 → time(s))
        if setData and 'drawTextEx' in data[i] and '$gameVariables' in data[i]:
            data[i] = re.sub(
                r'(\$\{\$gameVariables\.value\(\d+\)\}\s*)回',
                r'\1x',
                data[i]
            )

        # Next Line
        i += 1

    # EOF
    translate = False
    questListTL = [[], [], [], [], [], []]
    customTL = []

    # Compute combined total for progress bar across all categories
    combinedTotal = (
        sum(len(quest) for quest in questList)
        + len(custom)
        + len(sceneMenuText)
        + len(sceneMenuCommonHelpText)
        + len(sceneMenuHelpText)
        + len(sceneMenuDrawText)
        + len(sceneMenuStatLabel)
        + len(saveParamName)
    )
    if combinedTotal > 0:
        pbar.total = combinedTotal
        pbar.refresh()

    # Quest
    if len(questList) > 0:
        # Quest Name
        response = translateAI(questList[0], "Quest Name")
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        questName = response[0]

        # Quest Client
        response = translateAI(questList[1], "Quest Client")
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        questClient = response[0]

        # Quest Location
        response = translateAI(questList[2], "Quest Location")
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        questLocation = response[0]

        # Quest Target
        response = translateAI(questList[3], "Quest Location")
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        questTarget = response[0]

        # Quest Summary
        response = translateAI(questList[4], "Quest Summary")
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        questSummary = response[0]

        # Quest Goal 1
        response = translateAI(questList[5], "Quest Goal")
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        questGoal1 = response[0]

        # Check Mismatch
        if (
            len(questName) == len(questList[0])
            or len(questClient) == len(questList[1])
            or len(questLocation) == len(questList[2])
            or len(questTarget) == len(questList[3])
            or len(questSummary) == len(questList[4])
            or len(questGoal1) == len(questList[5])
        ):
            # Set Strings
            questListTL = [questName, questClient, questLocation, questTarget, questSummary, questGoal1]
            translate = True

        # Mismatch
        else:
            with LOCK:
                found_mismatch(MISMATCH, filename)

    # Custom
    if custom:
        # TL
        response = translateAI(custom, "Relic Name")
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        customResponse = response[0]

        # Check Mismatch
        if len(custom) == len(customResponse):
            customTL = customResponse
            translate = True

        # Mismatch
        else:
            with LOCK:
                found_mismatch(MISMATCH, filename)

    # SceneCustomMenu Text
    sceneMenuTextTL = []
    sceneMenuCommonHelpTextTL = []
    sceneMenuHelpTextTL = []
    sceneMenuDrawTextTL = []
    sceneMenuStatLabelTL = []
    saveParamNameTL = []

    if sceneMenuText:
        # TL
        response = translateAI(sceneMenuText, "Menu Item")
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        sceneMenuTextResponse = response[0]

        # Check Mismatch
        if len(sceneMenuText) == len(sceneMenuTextResponse):
            sceneMenuTextTL = sceneMenuTextResponse
            translate = True

        # Mismatch
        else:
            with LOCK:
                found_mismatch(MISMATCH, filename)

    # SceneCustomMenu CommonHelpText
    if sceneMenuCommonHelpText:
        # TL
        response = translateAI(sceneMenuCommonHelpText, "Menu Help Text")
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        sceneMenuCommonHelpTextResponse = response[0]

        # Check Mismatch
        if len(sceneMenuCommonHelpText) == len(sceneMenuCommonHelpTextResponse):
            sceneMenuCommonHelpTextTL = sceneMenuCommonHelpTextResponse
            translate = True

        # Mismatch
        else:
            with LOCK:
                found_mismatch(MISMATCH, filename)

    # SceneCustomMenu HelpText
    if sceneMenuHelpText:
        # TL
        response = translateAI(sceneMenuHelpText, "Menu Help Text")
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        sceneMenuHelpTextResponse = response[0]

        # Check Mismatch
        if len(sceneMenuHelpText) == len(sceneMenuHelpTextResponse):
            sceneMenuHelpTextTL = sceneMenuHelpTextResponse
            translate = True

        # Mismatch
        else:
            with LOCK:
                found_mismatch(MISMATCH, filename)

    # DrawTextEx - Brace-delimited labels (tracker section headers and field labels)
    if sceneMenuDrawText:
        # TL
        response = translateAI(sceneMenuDrawText, "Status Tracker Label")
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        sceneMenuDrawTextResponse = response[0]

        # Check Mismatch
        if len(sceneMenuDrawText) == len(sceneMenuDrawTextResponse):
            sceneMenuDrawTextTL = sceneMenuDrawTextResponse
            translate = True

        # Mismatch
        else:
            with LOCK:
                found_mismatch(MISMATCH, filename)

    # DrawTextEx - Stat labels (e.g., 攻撃力, 魔力, etc.)
    if sceneMenuStatLabel:
        # TL
        response = translateAI(sceneMenuStatLabel, "Character Stat Name")
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        sceneMenuStatLabelResponse = response[0]

        # Check Mismatch
        if len(sceneMenuStatLabel) == len(sceneMenuStatLabelResponse):
            sceneMenuStatLabelTL = sceneMenuStatLabelResponse
            translate = True

        # Mismatch
        else:
            with LOCK:
                found_mismatch(MISMATCH, filename)

    # NUUN_SaveScreen ParamName
    if saveParamName:
        # TL
        response = translateAI(saveParamName, "Save Screen Label")
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        saveParamNameResponse = response[0]

        # Check Mismatch
        if len(saveParamName) == len(saveParamNameResponse):
            saveParamNameTL = saveParamNameResponse
            translate = True

        # Mismatch
        else:
            with LOCK:
                found_mismatch(MISMATCH, filename)

    # Pass 2
    if translate and not setData:
        translatePlugin(data, pbar, filename, [questListTL, customTL, sceneMenuTextTL, sceneMenuCommonHelpTextTL, sceneMenuHelpTextTL, sceneMenuDrawTextTL, sceneMenuStatLabelTL, saveParamNameTL])
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
