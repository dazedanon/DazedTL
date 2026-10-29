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
# Removed concurrent.futures usage for simplicity; running synchronously
from pathlib import Path
from colorama import Fore
from dotenv import load_dotenv
from retry import retry
from tqdm import tqdm
from util.languages import source_pattern
from util.translation import TranslationConfig, translateAI as sharedtranslateAI, getPricingConfig, calculateCost, found_mismatch, last_translation_had_mismatch, run_stop_errors
from util.translation_task import fail_on_parser_error, module_receipt
from util.speakers import strip_speaker_prefix
from util import system

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
NOTEWIDTH = int(os.getenv("noteWidth"))
MAXHISTORY = 10
ESTIMATE = ""
TOKENS = [0, 0]
NAMESLIST = []  # Keep list for consistency
TERMSLIST = []  # Keep list for consistency
NAMES = False  # Output a list of all the character names found
BRFLAG = False  # If the game uses <br> instead
FIXTEXTWRAP = True  # Overwrites textwrap
IGNORETLTEXT = False  # Ignores all translated text.
MISMATCH = []  # Lists files that throw a mismatch error (Length of GPT list response is wrong)
FILENAME = None
BRACKETNAMES = False

# Regex - Need to change this if you want to translate from/to other languages. Default is Japanese Regex
LANGREGEX = source_pattern()

# Get pricing configuration based on the model
PRICING_CONFIG = getPricingConfig(MODEL)
INPUTAPICOST = PRICING_CONFIG["inputAPICost"]
OUTPUTAPICOST = PRICING_CONFIG["outputAPICost"]
BATCHSIZE = PRICING_CONFIG["batchSize"]
FREQUENCY_PENALTY = PRICING_CONFIG["frequencyPenalty"]

# tqdm Globals
BAR_FORMAT = "{l_bar}{bar:10}{r_bar}{bar:-10b}"
POSITION = 0
LEAVE = False
PBAR = None
FILENAME = None

# Dialogue / Choices
CODE101 = False
CODE102 = False

# Picture
CODE150 = False

# Set String (Fragile but necessary)
CODE122 = False

# Other
CODE210 = False
CODE300 = False
CODE250 = False

# Database
SCENARIOFLAG = False
OPTIONSFLAG = True
NPCFLAG = False
DBNAMEFLAG = False
DBVALUEFLAG = False
ITEMFLAG = False
STATEFLAG = False
ENEMYFLAG = False
ARMORFLAG = False
WEAPONFLAG = False
SKILLFLAG = False

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

def handleWOLF(filename, estimate):
    global ESTIMATE, TOKENS, FILENAME
    ESTIMATE = estimate
    FILENAME = filename

    # Translate
    start = time.time()
    translatedData = openFiles(filename)

    fail_on_parser_error(translatedData)

    # The file is written once, whole, and only when it finished; a write
    # that fails leaves an earlier translation as it was. Nothing read a
    # page's progress back (a run translates files/ again, its finished lines
    # from the translation cache), and a partial translated/ file replaced an
    # earlier complete one or, after a stop, counted as finished
    # (desktop/backend/manual.py).
    if not estimate:
        output = json.dumps(translatedData[0], ensure_ascii=False, indent=4)
        system.write_bytes("translated/" + filename, output.encode("utf-8"), 0o644)

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
    with open("files/" + filename, "r", encoding="utf-8-sig") as f:
        data = json.load(f)

    # A file's kind is its top-level key, never text found anywhere in it
    keys = data if isinstance(data, dict) else {}

    # Map Files
    if "events" in keys:
        if len(data["events"]) > 0:
            return parseMap(data, filename)
        return [data, [0, 0], None]

    # DataBase Files
    if "types" in keys:
        return parseWhole(data, filename, searchDB, "types")

    # CommonEvent Files
    if "commands" in keys:
        return parseWhole(data, filename, searchCodes, "commands")

    raise NameError(filename + " Not Supported")


def translatePage(search, page, pbar, filename, totalTokens):
    """Translate one *page* with *search* (searchCodes or searchDB); None
    when it finished, else its error, which a run's stop is not: that goes
    through unchanged. A finished page adds its tokens to *totalTokens*; the
    caller ends the file with a failing page's error."""
    try:
        tokens = search(page, pbar, [], filename)
    except run_stop_errors():
        raise
    except Exception as e:
        return e
    totalTokens[0] += tokens[0]
    totalTokens[1] += tokens[1]
    return None


def parseWhole(data, filename, search, key):
    """A file that is one page: a CommonEvent's "commands" or a DataBase's
    "types", translated with *search*."""
    totalTokens = [0, 0]
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE) as pbar:
        pbar.desc = filename
        pbar.total = 0
        error = translatePage(search, data[key], pbar, filename, totalTokens)
    return [data, totalTokens, error]


def parseMap(data, filename):
    totalTokens = [0, 0]
    totalLines = 0
    events = data["events"]
    global LOCK

    # Get total for progress bar
    for event in events:
        if event is not None:
            for page in event["pages"]:
                totalLines += len(page["list"])

    # Process pages synchronously; the first page that fails ends the file.
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
        pbar.desc = filename
        pbar.total = totalLines
        for event in events:
            if event is not None:
                for page in event["pages"]:
                    if page is not None:
                        error = translatePage(searchCodes, page["list"], pbar, filename, totalTokens)
                        if error is not None:
                            return [data, totalTokens, error]
    return [data, totalTokens, None]


def replyFits(translated, lines, filename):
    """Whether the reply translateAI just returned has one translation per
    line sent and no chunk of it kept its source text. One that does not is
    never written, so its lines keep their source text exactly, line breaks
    included, and the file joins MISMATCH, as RPG Maker's _reply_fits. A
    chunk translateAI kept is already counted; a reply of the wrong length is
    counted here."""
    if len(translated) != len(lines):
        with LOCK:
            found_mismatch(MISMATCH, filename)
        return False
    return not last_translation_had_mismatch()


def translateLists(lists, contexts, pbar, totalTokens, filename):
    """One DataBase category's *lists*, each sent with its context, adding
    their tokens to *totalTokens*: their translations, or None when a reply
    did not fit (replyFits), and then the set-data pass skips the category,
    which keeps its source text, and its other lists are not sent. A
    category without lines sends nothing."""
    if not any(lists):
        return [[] for _ in lists]
    pbar.total = sum(len(lines) for lines in lists)
    pbar.refresh()
    translated = []
    for lines, context in zip(lists, contexts, strict=True):
        response = translateAI(lines, context)
        totalTokens[0] += response[1][0]
        totalTokens[1] += response[1][1]
        if not replyFits(response[0], lines, filename):
            return None
        translated.append(response[0])
    return translated


def searchCodes(events, pbar, jobList, filename):
    """Translate one page of event commands; returns its [input, output] tokens.

    The first pass translates choices and names on the spot and gathers the
    rest into six lists, which are translated at the end of the page; the
    set-data pass (*jobList* holds those translations) only writes them, so
    it never sends what the first pass already translated. A list whose
    reply did not fit (replyFits) reaches it as None and is not written, and
    a page whose passes did not read the same lines fails."""
    # Lists, in the order they are sent
    if jobList:
        stringList, list210, list250, list300, list150, list122 = jobList
        setData = True
    else:
        stringList = []
        list210 = []
        list300 = []
        list150 = []
        list250 = []
        list122 = []
        setData = False

    # Other
    codeList = events
    textHistory = []
    totalTokens = [0, 0]
    translatedText = ""
    speaker = ""
    nametag = ""
    initialJAString = ""
    global LOCK, NAMESLIST, MISMATCH, PBAR, FILENAME
    FILENAME = filename
    PBAR = pbar

    # Calculate Total Length
    code_flags = {102: CODE102, 122: CODE122, 300: CODE300, 250: CODE250}
    totalList = 0
    for code_item in codeList:
        if code_flags.get(code_item["code"], False):
            totalList += 1
    pbar.total = totalList
    pbar.refresh()

    # Begin Parsing File
    try:
        # Iterate through events
        i = 0
        while i < len(codeList):
            ### Event Code: 101 Message
            if codeList[i]["code"] == 101 and CODE101 == True:
                speakerRegex = r"@\d+\r?\n(.*?)：?\r?\n" # Default: r"@\d+\r?\n(.*)：?\r?\n""
                textRegex = r"@\d+\r?\n.*?：?\r?\n(.*)" # Default: r"@\d+\r?\n.*：?\r?\n(.*)"
                # Alternative patterns for messages without @\d+ prefix
                speakerRegexAlt = r"^(.*?)：\r?\n" # Matches "Name：\n"
                textRegexAlt = r"^.*?：\r?\n(.*)" # Matches text after "Name：\n"

                # Grab String
                jaString = codeList[i]["stringArgs"][0]
                speaker = ""

                # Grab Speaker
                if "\n" in jaString and not setData:
                    match = re.search(speakerRegex, jaString)
                    if not match:
                        # Try alternative pattern without @\d+ prefix
                        match = re.search(speakerRegexAlt, jaString)
                    if match:
                        # TL Speaker
                        response = getSpeaker(match.group(1))
                        speaker = response[0]
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]

                        # Set Name
                        codeList[i]["stringArgs"][0] = codeList[i]["stringArgs"][0].replace(match.group(1), speaker)

                # Grab Only Text
                match = re.search(textRegex, jaString, flags=re.DOTALL)
                if not match:
                    # Try alternative pattern without @\d+ prefix
                    match = re.search(textRegexAlt, jaString, flags=re.DOTALL)
                if not match and re.search(LANGREGEX, jaString):
                    # No speaker pattern found, treat entire string as text to translate
                    jaString = jaString
                    initialJAString = jaString
                elif match:
                    jaString = match.group(1)
                    initialJAString = jaString
                else:
                    jaString = None  # Skip non-translatable text
                
                if jaString is not None:

                    # Remove Textwrap
                    jaString = jaString.replace("\r", "")
                    jaString = jaString.replace("\n", " ")

                    # 1st Pass (Save Text to List)
                    if not setData:
                        if speaker == "":
                            stringList.append(jaString)
                        else:
                            stringList.append(f"[{speaker}]: {jaString}")

                    # 2nd Pass (Set Text)
                    elif stringList is not None:
                        # Grab Translated String
                        translatedText = stringList[0]

                        # Remove speaker
                        translatedText = strip_speaker_prefix(translatedText)

                        # Textwrap
                        if FIXTEXTWRAP is True:
                            translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)

                        # Set Data
                        codeList[i]["stringArgs"][0] = codeList[i]["stringArgs"][0].replace(initialJAString, translatedText)

                        # Reset Data and Pop Item
                        stringList.pop(0)

            ### Event Code: 102 Choices
            if codeList[i]["code"] == 102 and CODE102 == True and not setData:
                # Grab Choice List
                choiceList = []
                jaChoiceList = codeList[i]["stringArgs"]

                # Filter Empty
                for j in range(len(jaChoiceList)):
                    if jaChoiceList[j]:
                        choiceList.append(jaChoiceList[j])

                # Translate
                choiceInstruction = (
                    f"Reply with the {LANGUAGE} translation of the dialogue choice"
                )
                if 'jaString' in locals() and jaString:
                    choiceContext = {
                        "instructions": [choiceInstruction],
                        "source_items": [jaString],
                    }
                else:
                    choiceContext = choiceInstruction
                response = translateAI(
                    choiceList,
                    choiceContext,
                    True,
                )
                translatedChoiceList = response[0]
                totalTokens[0] += response[1][0]
                totalTokens[1] += response[1][1]

                # Validate and Set Data
                if replyFits(translatedChoiceList, choiceList, filename):
                    for j in range(len(jaChoiceList)):
                        if jaChoiceList[j]:
                            codeList[i]["stringArgs"][j] = translatedChoiceList[0]
                            translatedChoiceList.pop(0)

            ### Event Code: 210 Common Event
            if codeList[i]["code"] == 210 and CODE210 == True:
                # Speaker Event
                if "stringArgs" in codeList[i] and codeList[i]["intArgs"][0] == None and len(codeList[i]["stringArgs"]) == 2 and not setData:
                    response = getSpeaker(codeList[i]["stringArgs"][1])
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]

                    # Set Data
                    codeList[i]["stringArgs"][1] = response[0]

                # Logs
                elif "stringArgs" in codeList[i] and codeList[i]["intArgs"][0] == 500725 and len(codeList[i]["stringArgs"]) == 2:
                    # Grab String
                    jaString = codeList[i]["stringArgs"][1]
                    initialJAString = jaString

                    # Remove Textwrap
                    jaString = jaString.replace("\r", "")
                    jaString = jaString.replace("\n", " ")

                    # 1st Pass (Save Text to List)
                    if not setData:
                        list210.append(jaString)

                    # 2nd Pass (Set Text)
                    elif list210 is not None:
                        # Grab Translated String
                        translatedText = list210[0]

                        # Textwrap
                        if FIXTEXTWRAP is True:
                            translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)

                        # Set Data
                        codeList[i]["stringArgs"][1] = translatedText

                        # Pop Item
                        list210.pop(0)

            ### Event Code: 122 SetString
            if codeList[i]["code"] == 122 and CODE122 == True:
                if "stringArgs" in codeList[i] and len(codeList[i]["stringArgs"]) > 0:
                    # Grab String
                    jaString = re.search(r"^\n?(.*)\n?$", codeList[i]["stringArgs"][0])
                    if jaString:
                        jaString = jaString.group(1)
                    else:
                        jaString = codeList[i]["stringArgs"][0]
    
                    originalString = jaString

                    # Remove Textwrap
                    jaString = jaString.replace("\r", "")
                    jaString = jaString.replace("\n", " ")

                    # Check if this is a translatable string
                    if (
                        not re.search(r"\.[\w]+$", jaString)
                        and jaString != ""
                        and "_" not in jaString
                        and '",' not in jaString
                        and "/" not in jaString
                        and re.search(LANGREGEX, jaString)
                    ):
                        # 1st Pass (Save Text to List)
                        if not setData:
                            list122.append(jaString)

                        # 2nd Pass (Set Text)
                        elif list122 is not None:
                            # Grab Translated String
                            translatedText = list122[0]

                            # Textwrap
                            if FIXTEXTWRAP is True:
                                translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)

                            # Set Data
                            codeList[i]["stringArgs"][0] = codeList[i]["stringArgs"][0].replace(originalString, translatedText)

                            # Pop Item
                            list122.pop(0)

            ### Event Code: 150 Picture String
            if codeList[i]["code"] == 150 and CODE150 == True:
                if "stringArgs" in codeList[i] and len(codeList[i]["stringArgs"]) > 0:                    
                    font150 = "\\f[8]"
                    # Grab String
                    jaString = codeList[i]["stringArgs"][0]

                    # Source Text Only
                    if not re.search(source_pattern("wolf_strings"), jaString):
                        i += 1
                        continue

                    # Remove Textwrap
                    # jaString = jaString.replace("\n", " ")
                    # jaString = jaString.replace("\r", "")

                    # Translate Other Strings [Specific Files Only]
                    if (
                        not re.search(r"\.[\w]+$", jaString)
                        and jaString != ""
                        and "_" not in jaString
                        and '",' not in jaString
                        # and ">" not in jaString
                        # and "<" not in jaString
                    ):
                        # Pass 1 (Save Text to List)
                        if not setData:
                            list150.append(jaString)

                        # Pass 2 (Set Text)
                        elif list150 is not None:
                            translatedText = list150[0]

                            # Textwrap
                            # translatedText = dazedwrap.wrapText(translatedText, WIDTH)

                            # Set String with font formatting
                            codeList[i]["stringArgs"][0] = re.sub(r'\\f\[(\d+)\]', lambda x: f'\\f[{int(x.group(1))-2}]', translatedText)

                            # Pop processed item
                            list150.pop(0)

            ### Event Code: 300 Common Events
            if codeList[i]["code"] == 300 and CODE300 == True and "stringArgs" in codeList[i] and len(codeList[i]["stringArgs"]) > 1:
                # Choices
                if (codeList[i]["stringArgs"][0] == "[共]汎用ウィンドウ生成" or codeList[i]["stringArgs"][0] == "選択肢/確認") and not setData:
                    # Grab String
                    choiceList = codeList[i]["stringArgs"][1].split(",")
                    choiceContext = f"Reply with the {LANGUAGE} translation of the dialogue choice"

                    # Translate the Question, which a 選択肢/確認 may leave
                    # out, then the choices with the original Japanese
                    # question as context, never the model's translated output.
                    question = codeList[i]["stringArgs"][2] if len(codeList[i]["stringArgs"]) > 2 else ""
                    if question:
                        response = translateAI(question, f"Reply with the {LANGUAGE} translation")
                        translatedQuestion = response[0]
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]
                        choiceContext = {"instructions": [choiceContext], "source_items": [question]}
                    response = translateAI(choiceList, choiceContext)
                    choiceListTL = response[0]
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]

                    # The window is written whole, once its choices fit
                    if replyFits(choiceListTL, choiceList, filename):
                        if question:
                            codeList[i]["stringArgs"][2] = translatedQuestion

                        # Replace Commas, Convert to String and Set
                        choiceListTL = [choice.replace(", ", "、") for choice in choiceListTL]
                        codeList[i]["stringArgs"][1] = ",".join(choiceListTL)

                # Dialogue
                elif codeList[i]["stringArgs"][0] == "BTLメッセージ" or codeList[i]["stringArgs"][0] == "X[移]メニュー時文章表示":
                    jaString = codeList[i]["stringArgs"][1]

                    # Pass 1
                    if not setData:
                        # Remove Textwrap
                        jaString = jaString.replace("\n", " ")
                        jaString = jaString.replace("\r", "")

                        # Append
                        list300.append(jaString)

                    # Pass 2
                    elif list300 is not None:
                        # Add Textwrap and Font
                        translatedText = dazedwrap.wrapText(list300[0], WIDTH)
                        list300.pop(0)

                        # Write to File
                        codeList[i]["stringArgs"][1] = translatedText
                
                # Dialogue
                elif codeList[i]["stringArgs"][0] == "援護文章":
                    speakerRegex = r"@\d+\r?\n(.*)：\r?\n" # Default: r"@\d+\r?\n(.*)：\r?\n"
                    textRegex = r"@?\d*\r?\n?\u3000*([\w\W]+)\r?\n?" # Default: r"@?\d*\r?\n?\u3000*([\w\W]+)\r?\n?"

                    # Grab String
                    jaString = codeList[i]["stringArgs"][1]
                    speaker = ""

                    # Grab Speaker
                    if "：\n" in jaString or "：\r\n" in jaString:
                        match = re.search(speakerRegex, jaString)
                        if match:
                            if not setData:
                                # TL Speaker
                                response = getSpeaker(match.group(1))
                                speaker = response[0]
                                totalTokens[0] += response[1][0]
                                totalTokens[1] += response[1][1]

                                # Set nametag
                                codeList[i]["stringArgs"][1] = codeList[i]["stringArgs"][1].replace(match.group(1), speaker)

                            # Remove nametag from string
                            jaString = jaString.replace(match.group(0), "")

                    # Grab Only Text
                    match = re.search(textRegex, jaString)
                    if match:
                        jaString = match.group(1)
                        initialJAString = jaString

                        # Remove Textwrap
                        jaString = jaString.replace("\r", "")
                        jaString = jaString.replace("\n", " ")

                        # 1st Pass (Save Text to List)
                        if not setData:
                            if speaker == "":
                                list300.append(jaString)
                            else:
                                list300.append(f"[{speaker}]: {jaString}")

                        # 2nd Pass (Set Text)
                        elif list300 is not None:
                            # Grab Translated String
                            translatedText = list300[0]

                            # Remove speaker
                            translatedText = strip_speaker_prefix(translatedText)

                            # Textwrap
                            if FIXTEXTWRAP is True:
                                translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)

                            # Set Data
                            codeList[i]["stringArgs"][1] = codeList[i]["stringArgs"][1].replace(initialJAString, translatedText)

                            # Reset Data and Pop Item
                            list300.pop(0)

            ### Event Code: 250 DB Read/Writes
            if codeList[i]["code"] == 250 and CODE250 == True:
                # Validate size
                stringArg = 0
                if len(codeList[i]["stringArgs"]) == 4:
                    if codeList[i]["stringArgs"][1] == "万能ｳｨﾝﾄﾞｳ一時DB"\
                        and codeList[i]["stringArgs"][stringArg] != "":
                        # Font Size
                        fontSize = 0

                        # Grab String
                        jaString = codeList[i]["stringArgs"][stringArg]

                        # Remove Textwrap
                        # jaString = jaString.replace("\r", "")
                        # jaString = jaString.replace("\n", " ")

                        # Pass 1 (Save Text to List)
                        if not setData:
                            list250.append(jaString)

                        # Pass 2 (Set Text)
                        elif list250 is not None:
                            translatedText = list250[0]
                            list250.pop(0)

                            # Textwrap
                            # translatedText = dazedwrap.wrapText(translatedText, WIDTH)

                            # Add/Replace font formatting
                            # Remove existing font command if present
                            translatedText = re.sub(r'\\f\[\d+\]', '', translatedText)
                            if fontSize:
                                # Add new font command if fontSize is not 0
                                if fontSize != "0" and fontSize != 0:
                                    translatedText = f"\\f[{fontSize}]{translatedText}"

                            # Set Data
                            codeList[i]["stringArgs"][stringArg] = translatedText

            ### Iterate
            i += 1

        # The set-data pass ends here, having written every line it was
        # given; a line left over means the passes read the page differently,
        # and the page fails rather than write text out of its place.
        if setData:
            if any(jobList):
                raise ValueError("The set-data pass left translations unwritten. ")
            return totalTokens

        # EOF: translate each list; the set-data pass writes each reply that
        # fits and gets None for one that does not (replyFits)
        jobList = []
        for lines in (stringList, list210, list250, list300, list150, list122):
            translated = []
            if len(lines) > 0:
                pbar.total = len(lines)
                pbar.refresh()
                response = translateAI(lines, textHistory)
                totalTokens[0] += response[1][0]
                totalTokens[1] += response[1][1]
                translated = response[0] if replyFits(response[0], lines, filename) else None
            jobList.append(translated)

        # Set Data
        if any(jobList):
            tokens = searchCodes(events, pbar, jobList, filename)
            totalTokens[0] += tokens[0]
            totalTokens[1] += tokens[1]

    except run_stop_errors():
        raise
    except IndexError as e:
        traceback.print_exc()
        raise Exception(str(e) + "Failed to translate: " + initialJAString) from None
    except Exception as e:
        traceback.print_exc()
        raise Exception(str(e) + "Failed to translate: " + initialJAString) from None

    return totalTokens


def formatDramon(jaString):
    imageRegex = r"(\r?\n?_[a-zA-Z_\d/.]+\r?\n?)|(@-?\d?\r\n)|(@-?\d?)([^\r]\d?-?\d?[^\r]+?)(\r\n|$)|(_PDC)|(>\r\n)|(^[#])|(\r\n@$)|(/)|(_SS_)|(\r\n[@/]\s?-?\d?\r\n)"

    jaString = jaString.replace("\u3000", " ")
    jaString = jaString.replace("#", "")
    jaString = re.sub(r"([^\r])\n", r"\1\r\n", jaString)

    # Grab and Split
    jaStringList = re.split(imageRegex, jaString)

    # Clean List
    cleanedList = [x for x in jaStringList if x is not None and x != "" and x != "\r\n" and x != "_SS_"]

    # Iterate Through List
    j = 0
    translatedText = ""
    while j < len(cleanedList):
        if (
            ("@" in cleanedList[j] or "/" in cleanedList[j])
            and j < len(cleanedList) - 1
            and re.search(r"([@/]-?\d?\r\n)", cleanedList[j]) is None
            and ".ogg" not in cleanedList[j]
        ):
            # Setup @
            if j > 0 and "@" not in cleanedList[j - 1] and "/" not in cleanedList[j - 1] and "_" not in cleanedList[j - 1]:
                cleanedList[j - 1] = cleanedList[j - 1] + cleanedList[j + 1]
            else:
                cleanedList.insert(j, cleanedList[j + 1])
                j += 1
            cleanedList[j] = f"\r\n{cleanedList[j]}\r\n"
            cleanedList.pop(j + 1)
        j += 1

    return cleanedList

def handleScenarioScript(jaString, scriptString=""):
    # Extract Speaker
    # Updated regex to match speaker names with spaces, hyphens, and other characters
    # [^\n：]+ matches any character except newline and ： (the speaker name)
    scriptRegex = r"\n?(//.*?\n|//.*|/b.*?\n|[^\n：]+：\d*\r?\n)"
    match = re.search(scriptRegex, jaString)
    if match:
        if "//" in match.group(1):
            scriptStringLocal = match.group(1)
            jaString = jaString.replace(scriptStringLocal, "")
            scriptString += scriptStringLocal
            match = re.search(scriptRegex, jaString)
            if not match:
                return None
            else:
                if "//" in jaString:
                    return handleScenarioScript(jaString, scriptString)
        return [jaString, match.group(1), scriptString]
    else:
        return None

# Database
def searchDB(events, pbar, jobList, filename):
    # Set Lists
    if len(jobList) > 0:
        scenarioList = jobList[0]
        npcList = jobList[1]
        itemList = jobList[2]
        stateList = jobList[3]
        armorList = jobList[4]
        enemyList = jobList[5]
        weaponsList = jobList[6]
        skillList = jobList[7]
        optionsList = jobList[8]
        dbNameList = jobList[9]
        dbValueList = jobList[10]
        setData = True
    else:
        scenarioList = [[], [], []]
        npcList = [[], [], [], []]
        itemList = [[], [], [], []]
        armorList = [[], []]
        enemyList = [[], []]
        weaponsList = [[], [], [], []]
        skillList = [[], [], [], [], []]
        stateList = [[], [], [], [], [], [], [], []]
        optionsList = [[], [], []]
        dbNameList = [[]]
        dbValueList = [[]]
        setData = False

    # Vars/Globals
    totalTokens = [0, 0]
    initialJAString = ""
    tableList = events
    font = ""
    global LOCK
    global NAMESLIST
    global MISMATCH
    global PBAR
    PBAR = pbar

    # Begin Parsing File
    try:
        for table in tableList:
            # Grab NPCs
            if table["name"] == "アイドル" and NPCFLAG == True and npcList is not None:
                with open("log/translations.txt", "a", encoding="utf-8") as file:
                    if setData:
                        file.write(f"\n#Actors\n")
                    for npc in table["data"]:
                        dataList = npc["data"]

                        # Parse
                        for j in range(len(dataList)):
                            # Name
                            if dataList[j].get("name") == "出身":
                                # Pass 1 (Grab Data)
                                if setData == False:
                                    if dataList[j].get("value") != "":
                                        npcList[0].append(dataList[j].get("value"))

                                # Pass 2 (Set Data)
                                else:
                                    if dataList[j].get("value") != "":
                                        # Write Name
                                        file.write(f"{dataList[j].get('value')} ({npcList[0][0]})\n")

                                        # Set Data
                                        dataList[j].update({"value": npcList[0][0]})
                                        npcList[0].pop(0)

                            # Description
                            if dataList[j].get("name") == "説明":
                                # Pass 1 (Grab Data)
                                if setData == False:
                                    if dataList[j].get("value") != "":
                                        # Remove Textwrap
                                        jaString = dataList[j].get("value")
                                        jaString = jaString.replace("\n", " ")
                                        jaString = jaString.replace("\r", "")
                                        jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                        # Append Data
                                        npcList[1].append(jaString)
                                # Pass 2 (Set Data)
                                else:
                                    if dataList[j].get("value") != "":
                                        # Textwrap
                                        translatedText = npcList[1][0]
                                        translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)
                                        translatedText = font + translatedText

                                        # Set Data
                                        dataList[j].update({"value": translatedText})
                                        npcList[1].pop(0)

            # Grab Scenario
            if "デートキャラ" in table["name"] and SCENARIOFLAG == True and scenarioList is not None:
                for scenario in table["data"]:
                    dataList = scenario["data"]

                    # Parse
                    for j in range(len(dataList)):
                        # Name
                        if dataList[j].get("name") == "NULL":
                            if dataList[j].get("value"):
                                jaStringList = re.split(r'\r\n\r\n|\n\n', dataList[j].get("value"))
                                for jaString in jaStringList:
                                    speakerNum = None
                                    ogString = jaString
                                    # Extract Speaker
                                    speakerList = handleScenarioScript(jaString)
                                    
                                    # Handle simple names without speaker pattern
                                    if not speakerList:
                                        # Pass 1 (Grab Data) - Simple name
                                        if setData == False:
                                            jaString = jaString.replace("\n", " ")
                                            jaString = jaString.replace("\r", "")
                                            if jaString.strip():
                                                scenarioList[0].append(jaString)
                                        # Pass 2 (Set Data) - Simple name
                                        else:
                                            if ogString.strip():
                                                translatedText = scenarioList[0][0]
                                                scenarioList[0].pop(0)
                                                dataList[j].update({"value": dataList[j].get("value").replace(ogString, translatedText)})
                                        continue
                                        
                                    if speakerList[2]:
                                        jaString = speakerList[0]
                                    speakerNumMatch = re.search(r"：(\d+)", speakerList[1])
                                    if speakerNumMatch:
                                        speakerNum = speakerNumMatch.group(1)
                                    speaker = re.sub(r"：\d*", "", speakerList[1])
                                    speaker = re.sub(r"/b", "NPC", speaker)
                                    speaker = speaker.replace("\r\n", "")
                                    
                                    # Add Speaker
                                    jaString = jaString.replace(speakerList[1], f"[{speaker}]: ")

                                    # Pass 1 (Grab Data)
                                    if setData == False:
                                        jaString = jaString.replace("\n", " ")
                                        jaString = jaString.replace("\r", "")
                                        scenarioList[0].append(jaString)

                                    # Pass 2 (Set Data)
                                    else:
                                        translatedText = scenarioList[0][0]
                                        scenarioList[0].pop(0)

                                        # Remove Speaker before wrapping so WIDTH applies to dialogue only
                                        speakerMatch = re.search(r"\[(.+?)\]\s?[|:]\s?", translatedText)
                                        if speakerMatch:
                                            speaker = speakerMatch.group(1).strip()
                                        match = re.search(r'(^\[.+?\]\s?[|:]\s?)', translatedText)
                                        if match:
                                            translatedText = translatedText.replace(match.group(1), "")

                                        # Wrap text after removing speaker
                                        translatedText = dazedwrap.wrapText(translatedText, WIDTH) 

                                        # Redo Old Speaker Format
                                        speaker = speaker.replace("Speaker", "\b")
                                        if speakerNum:
                                            translatedText = f"{speaker}：{speakerNum}\r\n{translatedText}"
                                        elif speaker == "NPC":
                                            translatedText = f"/b\r\n{translatedText}"
                                        else:
                                            translatedText = f"{speaker}：\r\n{translatedText}"

                                        # Add Script String
                                        if speakerList[2]:
                                            translatedText = f"{speakerList[2]}{translatedText}"

                                        # Set Data
                                        dataList[j].update({"value": dataList[j].get("value").replace(ogString, translatedText)})
                        # Description
                        if dataList[j].get("name") == "不正解会話":
                            if dataList[j].get("value"):
                                jaStringList = re.split(r'\r\n\r\n|\n\n', dataList[j].get("value"))
                                for jaString in jaStringList:
                                    speakerNum = None
                                    ogString = jaString
                                    # Extract Speaker
                                    speakerList = handleScenarioScript(jaString)
                                    
                                    # Handle simple text without speaker pattern
                                    if not speakerList:
                                        # Pass 1 (Grab Data) - Simple text
                                        if setData == False:
                                            jaString = jaString.replace("\n", " ")
                                            jaString = jaString.replace("\r", "")
                                            if jaString.strip():
                                                scenarioList[1].append(jaString)
                                        # Pass 2 (Set Data) - Simple text
                                        else:
                                            if ogString.strip():
                                                translatedText = scenarioList[1][0]
                                                scenarioList[1].pop(0)
                                                translatedText = dazedwrap.wrapText(translatedText, WIDTH)
                                                dataList[j].update({"value": dataList[j].get("value").replace(ogString, translatedText)})
                                        continue
                                        
                                    if speakerList[2]:
                                        jaString = speakerList[0]
                                    speakerNumMatch = re.search(r"：(\d+)", speakerList[1])
                                    if speakerNumMatch:
                                        speakerNum = speakerNumMatch.group(1)
                                    speaker = re.sub(r"：\d*", "", speakerList[1])
                                    speaker = re.sub(r"/b", "NPC", speaker)
                                    speaker = speaker.replace("\r\n", "")
                                    
                                    # Add Speaker
                                    jaString = jaString.replace(speakerList[1], f"[{speaker}]: ")

                                    # Pass 1 (Grab Data)
                                    if setData == False:
                                        jaString = jaString.replace("\n", " ")
                                        jaString = jaString.replace("\r", "")
                                        scenarioList[1].append(jaString)

                                    # Pass 2 (Set Data)
                                    else:
                                        translatedText = scenarioList[1][0]
                                        scenarioList[1].pop(0)

                                        # Remove Speaker before wrapping so WIDTH applies to dialogue only
                                        speakerMatch = re.search(r"\[(.+?)\]\s?[|:]\s?", translatedText)
                                        if speakerMatch:
                                            speaker = speakerMatch.group(1).strip()
                                        match = re.search(r'(^\[.+?\]\s?[|:]\s?)', translatedText)
                                        if match:
                                            translatedText = translatedText.replace(match.group(1), "")

                                        # Wrap text after removing speaker
                                        translatedText = dazedwrap.wrapText(translatedText, WIDTH) 

                                        # Redo Old Speaker Format
                                        speaker = speaker.replace("Speaker", "\b")
                                        if speakerNum:
                                            translatedText = f"{speaker}：{speakerNum}\r\n{translatedText}"
                                        elif speaker == "NPC":
                                            translatedText = f"/b\r\n{translatedText}"
                                        else:
                                            translatedText = f"{speaker}：\r\n{translatedText}"

                                        # Add Script String
                                        if speakerList[2]:
                                            translatedText = f"{speakerList[2]}{translatedText}"

                                        # Set Data
                                        dataList[j].update({"value": dataList[j].get("value").replace(ogString, translatedText)})

                        # Description
                        if dataList[j].get("name") == "正解会話":
                            if dataList[j].get("value"):
                                jaStringList = re.split(r'\r\n\r\n|\n\n', dataList[j].get("value"))
                                for jaString in jaStringList:
                                    speakerNum = None
                                    ogString = jaString
                                    # Extract Speaker
                                    speakerList = handleScenarioScript(jaString)
                                    
                                    # Handle simple text without speaker pattern
                                    if not speakerList:
                                        # Pass 1 (Grab Data) - Simple text
                                        if setData == False:
                                            jaString = jaString.replace("\n", " ")
                                            jaString = jaString.replace("\r", "")
                                            if jaString.strip():
                                                scenarioList[2].append(jaString)
                                        # Pass 2 (Set Data) - Simple text
                                        else:
                                            if ogString.strip():
                                                translatedText = scenarioList[2][0]
                                                scenarioList[2].pop(0)
                                                translatedText = dazedwrap.wrapText(translatedText, WIDTH)
                                                dataList[j].update({"value": dataList[j].get("value").replace(ogString, translatedText)})
                                        continue
                                    if speakerList[2]:
                                        jaString = speakerList[0]
                                    speakerNumMatch = re.search(r"：(\d+)", speakerList[1])
                                    if speakerNumMatch:
                                        speakerNum = speakerNumMatch.group(1)
                                    speaker = re.sub(r"：\d*", "", speakerList[1])
                                    speaker = re.sub(r"/b", "NPC", speaker)
                                    speaker = speaker.replace("\r\n", "")
                                    
                                    # Add Speaker
                                    jaString = jaString.replace(speakerList[1], f"[{speaker}]: ")

                                    # Pass 1 (Grab Data)
                                    if setData == False:
                                        jaString = jaString.replace("\n", " ")
                                        jaString = jaString.replace("\r", "")
                                        scenarioList[2].append(jaString)

                                    # Pass 2 (Set Data)
                                    else:
                                        translatedText = scenarioList[2][0]
                                        scenarioList[2].pop(0)

                                        # Remove Speaker before wrapping so WIDTH applies to dialogue only
                                        speakerMatch = re.search(r"\[(.+?)\]\s?[|:]\s?", translatedText)
                                        if speakerMatch:
                                            speaker = speakerMatch.group(1).strip()
                                        match = re.search(r'(^\[.+?\]\s?[|:]\s?)', translatedText)
                                        if match:
                                            translatedText = translatedText.replace(match.group(1), "")

                                        # Wrap text after removing speaker
                                        translatedText = dazedwrap.wrapText(translatedText, WIDTH)

                                        # Redo Old Speaker Format
                                        speaker = speaker.replace("Speaker", "\b")
                                        if speakerNum:
                                            translatedText = f"{speaker}：{speakerNum}\r\n{translatedText}"
                                        elif speaker == "NPC":
                                            translatedText = f"/b\r\n{translatedText}"
                                        else:
                                            translatedText = f"{speaker}：\r\n{translatedText}"

                                        # Add Script String
                                        if speakerList[2]:
                                            translatedText = f"{speakerList[2]}{translatedText}"

                                        # Set Data
                                        dataList[j].update({"value": dataList[j].get("value").replace(ogString, translatedText)})

            # Grab Options
            if table["name"] == "クイズ" and OPTIONSFLAG == True and optionsList is not None:
                for option in table["data"]:
                    dataList = option["data"]

                    # Parse
                    for j in range(len(dataList)):
                        # Name
                        if dataList[j].get("name") == "問":
                            if dataList[j].get("value"):
                                jaString = dataList[j].get("value")
                                # Pass 1 (Grab Data)
                                if setData == False:
                                    optionsList[0].append(jaString)

                                # Pass 2 (Set Data)
                                else:
                                    translatedText = optionsList[0][0]
                                    optionsList[0].pop(0)
                                    dataList[j].update({"value": dataList[j].get("value").replace(jaString, translatedText)})

                        # Description 1
                        if dataList[j].get("name") == "3":
                            if dataList[j].get("value"):
                                jaString = dataList[j].get("value")
                                # Pass 1 (Grab Data)
                                if setData == False:
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    optionsList[1].append(jaString)

                                # Pass 2 (Set Data)
                                else:
                                    translatedText = optionsList[1][0]
                                    optionsList[1].pop(0)
                                    translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)
                                    dataList[j].update({"value": dataList[j].get("value").replace(jaString, translatedText)})

                        # Description 2
                        if dataList[j].get("name") == "4":
                            if dataList[j].get("value"):
                                jaString = dataList[j].get("value")
                                # Pass 1 (Grab Data)
                                if setData == False:
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    optionsList[2].append(jaString)

                                # Pass 2 (Set Data)
                                else:
                                    translatedText = optionsList[2][0]
                                    optionsList[2].pop(0)
                                    translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)
                                    dataList[j].update({"value": dataList[j].get("value").replace(jaString, translatedText)})

            # Grab DB Names
            if table["name"] == "マップ設定" and DBNAMEFLAG == True and dbNameList is not None:
                font = None
                dbName = table["data"]
                for j in range(len(dbName)):
                    # Pass 1 (Grab Data)
                    if setData == False:
                        if dbName[j].get("name") != "":
                            dbNameList[0].append(dbName[j].get("name"))

                    # Pass 2 (Set Data)
                    else:
                        if dbName[j].get("name") != "":
                            dbName[j].update({"name": dbNameList[0][0]})
                            dbNameList[0].pop(0)

            # Grab DB Values
            if table["name"] == "近況文章" and DBVALUEFLAG == True and dbValueList is not None:
                font = 16
                subject = ""
                for entry in table["data"]:
                    dbValue = entry["data"]
                    for j in range(len(dbValue)):
                        if dbValue[j].get("value"):
                            jaString = dbValue[j].get("value")

                            # Speaker
                            match = re.search(r"(^[\\]+f\[\d+\].+?\r\n).+", jaString)
                            if match:
                                subject = match.group(1)
                                jaString = jaString.replace(subject, "")

                                # Nuke Textwrap & Font
                                jaString = jaString.replace("\r", "")
                                jaString = jaString.replace("\n", " ")
                                jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                # Pass 1 (Grab Data)
                                if setData == False:
                                    # Append
                                    dbValueList[0].append(jaString)

                                # Pass 2 (Set Data)
                                else:
                                    if dbValue[j].get("value"):
                                        translatedText = dbValueList[0][0]

                                        # Textwrap
                                        translatedText = dazedwrap.wrapText(translatedText, 30)
                                        translatedText = translatedText.replace("\n", f"\r\n\\f[{font}]")

                                        # Subject
                                        if subject:
                                            translatedText = f"{subject}{translatedText}"

                                        # Set
                                        dbValue[j].update({"value": translatedText})
                                        dbValueList[0].pop(0)

            # Grab Items
            if table["name"] == "道具" and ITEMFLAG == True and itemList is not None:
                # Write Category
                if setData:
                    with open("log/translations.txt", "a", encoding="utf-8") as file:
                        file.write(f"\n#Items\n")

                # Begin Translation
                for item in table["data"]:
                    dataList = item["data"]

                    # Parse
                    font = 18
                    for j in range(len(dataList)):
                        # Name
                        if dataList[j].get("name") == "名前":
                            jaString = dataList[j].get("value")
                            if jaString != "":
                                # Pass 1 (Grab Data)
                                if setData == False:
                                    if jaString != "":
                                        itemList[0].append(jaString)

                                # Pass 2 (Set Data)
                                else:
                                    # Write to TL File
                                    with open("log/translations.txt", "a", encoding="utf-8") as file:
                                        file.write(f"{jaString} ({itemList[0][0]})\n")

                                    dataList[j].update({"value": itemList[0][0]})
                                    itemList[0].pop(0)

                        # Description
                        if dataList[j].get("name") == "説明":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    # Remove Textwrap & Font
                                    jaString = dataList[j].get("value")
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                    # Append Data
                                    itemList[1].append(jaString)
                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    # Textwrap
                                    translatedText = itemList[1][0]
                                    translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)

                                    # Font
                                    if font:
                                        translatedText = f"\\f[{font}]{translatedText}"

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    itemList[1].pop(0)

                        # Log
                        if dataList[j].get("name") == "使用時文章[戦](人名~":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    # Remove Textwrap
                                    jaString = dataList[j].get("value")
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                    # Skill Action
                                    if jaString[0] in [
                                        "は",
                                        "を",
                                        "の",
                                        "に",
                                        "が",
                                    ]:
                                        jaString = f"Taro{jaString}"

                                    # Append Data
                                    itemList[2].append(jaString)
                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    # Textwrap
                                    translatedText = itemList[2][0]
                                    translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)
                                    # translatedText = font + translatedText

                                    # Remove Taro
                                    translatedText = re.sub(r"\bTaro\b", "", translatedText)

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    itemList[2].pop(0)

                        # Description
                        if dataList[j].get("name") == "使用後文章[移動]":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    # Remove Textwrap
                                    jaString = dataList[j].get("value")
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                    # Append Data
                                    itemList[3].append(jaString)
                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    # Textwrap
                                    translatedText = itemList[3][0]
                                    translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)

                                    # Font
                                    if font:
                                        translatedText = f"\\f[{font}]{translatedText}"

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    itemList[3].pop(0)

            # Grab Armors
            if table["name"] == "防具" and ARMORFLAG == True and armorList is not None:
                font = "24"
                for armor in table["data"]:
                    dataList = armor["data"]

                    # Parse
                    for j in range(len(dataList)):
                        # Name
                        if dataList[j].get("name") == "名前":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    armorList[0].append(dataList[j].get("value"))

                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    dataList[j].update({"value": armorList[0][0]})
                                    armorList[0].pop(0)

                        # Description
                        if dataList[j].get("name") == "説明":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    # Remove Textwrap
                                    jaString = dataList[j].get("value")
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                    # Append Data
                                    armorList[1].append(jaString)
                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    # Textwrap
                                    translatedText = armorList[1][0]
                                    translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)

                                    # Font
                                    if font:
                                        translatedText = f"\\f[{font}]{translatedText}"

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    armorList[1].pop(0)

            # Grab Enemies
            if table["name"] == "敵" and ENEMYFLAG == True and enemyList is not None:
                for enemy in table["data"]:
                    dataList = enemy["data"]

                    # Parse
                    for j in range(len(dataList)):
                        # Name
                        if dataList[j].get("name") == "敵キャラ名":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    enemyList[0].append(dataList[j].get("value"))

                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    dataList[j].update({"value": enemyList[0][0]})
                                    enemyList[0].pop(0)

                        # Description
                        if dataList[j].get("name") == "NULL":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    # Remove Textwrap
                                    jaString = dataList[j].get("value")
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                    # Append Data
                                    enemyList[1].append(jaString)
                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    # Textwrap
                                    translatedText = enemyList[1][0]
                                    translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)

                                    # Font
                                    if font:
                                        translatedText = f"\\f[{font}]{translatedText}"

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    enemyList[1].pop(0)

            # Grab Weapons
            if table["name"] == "武器" and WEAPONFLAG == True and weaponsList is not None:
                font = "24"
                for weapon in table["data"]:
                    dataList = weapon["data"]

                    # Parse
                    for j in range(len(dataList)):
                        # Name
                        if dataList[j].get("name") == "名前":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    weaponsList[0].append(dataList[j].get("value"))

                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    dataList[j].update({"value": weaponsList[0][0]})
                                    weaponsList[0].pop(0)

                        # Description
                        if dataList[j].get("name") == "説明":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    # Remove Textwrap
                                    jaString = dataList[j].get("value")
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                    # Append Data
                                    weaponsList[1].append(jaString)
                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    # Textwrap
                                    translatedText = weaponsList[1][0]
                                    translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)

                                    # Font
                                    if font:
                                        translatedText = f"\\f[{font}]{translatedText}"

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    weaponsList[1].pop(0)

            # Grab Skills
            if table["name"] == "技能" and SKILLFLAG == True and skillList is not None:
                font = "24"
                for skill in table["data"]:
                    dataList = skill["data"]

                    # Parse
                    for j in range(len(dataList)):
                        # Name
                        if dataList[j].get("name") == "名前":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    skillList[0].append(dataList[j].get("value"))

                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    dataList[j].update({"value": skillList[0][0]})
                                    skillList[0].pop(0)

                        # Description
                        if dataList[j].get("name") == "説明":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    # Remove Textwrap
                                    jaString = dataList[j].get("value")
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                    # Append Data
                                    skillList[1].append(jaString)

                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    # Textwrap
                                    translatedText = skillList[1][0]
                                    translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)

                                    # Font
                                    if font:
                                        translatedText = f"\\f[{font}]{translatedText}"

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    skillList[1].pop(0)

                        # Log
                        if dataList[j].get("name") == "発動時文章":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    # Remove Textwrap
                                    jaString = dataList[j].get("value")
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                    # Skill Action
                                    if jaString[0] in [
                                        "は",
                                        "を",
                                        "の",
                                        "に",
                                        "が",
                                    ]:
                                        jaString = f"Taro{jaString}"

                                    # Append Data
                                    skillList[2].append(jaString)
                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    # Textwrap
                                    translatedText = skillList[2][0]
                                    translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)
                                    translatedText = font + translatedText

                                    # Remove Taro
                                    translatedText = re.sub(r"\bTaro\b", "", translatedText)

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    skillList[2].pop(0)

                        # Log
                        if dataList[j].get("name") == "使用時文章[戦闘](人名~":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    # Remove Textwrap
                                    jaString = dataList[j].get("value")
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                    # Skill Action
                                    if jaString[0] in [
                                        "は",
                                        "を",
                                        "の",
                                        "に",
                                        "が",
                                    ]:
                                        jaString = f"Taro{jaString}"

                                    # Append Data
                                    skillList[3].append(jaString)
                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    # Textwrap
                                    translatedText = skillList[3][0]
                                    translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)

                                    # Remove Taro
                                    translatedText = re.sub(r"\bTaro\b", "", translatedText)

                                    # Font
                                    translatedText = font + translatedText

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    skillList[3].pop(0)

                        # Log
                        if dataList[j].get("name") == "失敗時文章[(対象)～]":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    # Remove Textwrap
                                    jaString = dataList[j].get("value")
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                    # Skill Action
                                    if jaString[0] in [
                                        "は",
                                        "を",
                                        "の",
                                        "に",
                                        "が",
                                    ]:
                                        jaString = f"Taro{jaString}"

                                    # Append Data
                                    skillList[4].append(jaString)
                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    # Textwrap
                                    translatedText = skillList[4][0]
                                    translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)
                                    translatedText = font + translatedText

                                    # Remove Taro
                                    translatedText = re.sub(r"\bTaro\b", "", translatedText)

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    skillList[4].pop(0)

            # Grab States
            if table["name"] == "ステート" and STATEFLAG == True and stateList is not None:
                for state in table["data"]:
                    dataList = state["data"]

                    # Parse
                    for j in range(len(dataList)):
                        # Name
                        if dataList[j].get("name") == "名前":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    stateList[0].append(dataList[j].get("value"))

                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    dataList[j].update({"value": stateList[0][0]})
                                    stateList[0].pop(0)

                        # Description
                        if dataList[j].get("name") == "表示名":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    # Remove Textwrap
                                    jaString = dataList[j].get("value")
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                    # Append Data
                                    stateList[1].append(jaString)
                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    # Textwrap
                                    translatedText = stateList[1][0]
                                    translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)
                                    translatedText = font + translatedText

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    stateList[1].pop(0)

                        # Log
                        if dataList[j].get("name") == "付与時文章":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    # Remove Textwrap
                                    jaString = dataList[j].get("value")
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                    # State Action
                                    if jaString[0] in [
                                        "は",
                                        "を",
                                        "の",
                                        "に",
                                        "が",
                                    ]:
                                        jaString = f"Taro{jaString}"

                                    # Append Data
                                    stateList[2].append(jaString)
                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    # Textwrap
                                    translatedText = stateList[2][0]
                                    translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)
                                    translatedText = font + translatedText

                                    # Remove Taro
                                    translatedText = re.sub(r"\bTaro\b", "", translatedText)

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    stateList[2].pop(0)

                        # Log
                        if dataList[j].get("name") == "解除時文章":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    # Remove Textwrap
                                    jaString = dataList[j].get("value")
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                    # State Action
                                    if jaString[0] in [
                                        "は",
                                        "を",
                                        "の",
                                        "に",
                                        "が",
                                    ]:
                                        jaString = f"Taro{jaString}"

                                    # Append Data
                                    stateList[3].append(jaString)
                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    # Textwrap
                                    translatedText = stateList[3][0]
                                    translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)
                                    translatedText = font + translatedText

                                    # Remove Taro
                                    translatedText = re.sub(r"\bTaro\b", "", translatedText)

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    stateList[3].pop(0)

                        # Log
                        if dataList[j].get("name") == "回復時の文章[(人名)～]":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    # Remove Textwrap
                                    jaString = dataList[j].get("value")
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                    # State Action
                                    if jaString[0] in [
                                        "は",
                                        "を",
                                        "の",
                                        "に",
                                        "が",
                                    ]:
                                        jaString = f"Taro{jaString}"

                                    # Append Data
                                    stateList[4].append(jaString)
                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    # Textwrap
                                    translatedText = stateList[4][0]
                                    translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)
                                    translatedText = font + translatedText

                                    # Remove Taro
                                    translatedText = re.sub(r"\bTaro\b", "", translatedText)

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    stateList[4].pop(0)
                        # Log
                        if dataList[j].get("name") == "┣ ｶｳﾝﾀｰ発動文[対象～":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    # Remove Textwrap
                                    jaString = dataList[j].get("value")
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                    # State Action
                                    if jaString[0] in [
                                        "は",
                                        "を",
                                        "の",
                                        "に",
                                        "が",
                                    ]:
                                        jaString = f"Taro{jaString}"

                                    # Append Data
                                    stateList[5].append(jaString)
                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    # Textwrap
                                    translatedText = stateList[5][0]
                                    translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)
                                    translatedText = font + translatedText

                                    # Remove Taro
                                    translatedText = re.sub(r"\bTaro\b", "", translatedText)

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    stateList[5].pop(0)

                        # Log
                        if dataList[j].get("name") == "尻もち　行動不能　持続3ターン":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    # Remove Textwrap
                                    jaString = dataList[j].get("value")
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                    # State Action
                                    if jaString[0] in [
                                        "は",
                                        "を",
                                        "の",
                                        "に",
                                        "が",
                                    ]:
                                        jaString = f"Taro{jaString}"

                                    # Append Data
                                    stateList[6].append(jaString)
                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    # Textwrap
                                    translatedText = stateList[6][0]
                                    translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)
                                    translatedText = font + translatedText

                                    # Remove Taro
                                    translatedText = re.sub(r"\bTaro\b", "", translatedText)

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    stateList[6].pop(0)

                        # Log
                        if dataList[j].get("name") == "状態異常の説明":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    # Remove Textwrap
                                    jaString = dataList[j].get("value")
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                    # State Action
                                    if jaString[0] in [
                                        "は",
                                        "を",
                                        "の",
                                        "に",
                                        "が",
                                    ]:
                                        jaString = f"Taro{jaString}"

                                    # Append Data
                                    stateList[7].append(jaString)
                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    # Textwrap
                                    translatedText = stateList[7][0]
                                    translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)
                                    translatedText = font + translatedText

                                    # Remove Taro
                                    translatedText = re.sub(r"\bTaro\b", "", translatedText)

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    stateList[7].pop(0)

        # EOF. The set-data pass ends here, having written every line it was
        # given; a line left over means the passes read the file differently,
        # and the file fails rather than write text out of its place.
        if setData:
            if any(lists and any(lists) for lists in jobList):
                raise ValueError("The set-data pass left translations unwritten. ")
            return totalTokens

        # Translate each category's lists, in this order, each with its
        # context; the set-data pass writes a category whose replies all fit
        # and gets None for one that does not (translateLists)
        only = "Reply with only the " + LANGUAGE + " translation"
        npcName = "reply with only the gender neutral " + LANGUAGE + " translation of the NPC name"
        actionLog = (
            "reply with only the gender neutral "
            + LANGUAGE
            + " translation of the action log. Always start the sentence with Taro. For example, Translate 'Taroを倒した！' as 'Taro was defeated!'"
        )
        statusEffect = f"Reply with the {LANGUAGE} translation of the status effect."
        categories = {
            "npc": (npcList, [only + " of the RPG enemy name", only, only, only]),
            "scenario": (scenarioList, [only, npcName, npcName]),
            "options": (optionsList, [only, npcName, npcName]),
            "item": (itemList, [only, only, only, only]),
            "armor": (armorList, [only + " of the NPC name", only]),
            "enemy": (enemyList, [only + " of the enemy NPC name", only]),
            "weapons": (weaponsList, [only + " of the RPG weapon name", "", "", ""]),
            "skill": (
                skillList,
                [
                    only + " of the RPG skill name",
                    only + " of the RPG skill description",
                    actionLog,
                    actionLog,
                    actionLog,
                ],
            ),
            "state": (
                stateList,
                [statusEffect, "", statusEffect, actionLog, actionLog, actionLog, actionLog, actionLog],
            ),
            "dbName": (dbNameList, [only]),
            "dbValue": (dbValueList, [only]),
        }
        translated = {
            name: translateLists(lists, contexts, pbar, totalTokens, filename)
            for name, (lists, contexts) in categories.items()
        }

        # Set Data, in the order searchDB reads jobList
        if any(lists and any(lists) for lists in translated.values()):
            jobList = [
                translated[name]
                for name in (
                    "scenario",
                    "npc",
                    "item",
                    "state",
                    "armor",
                    "enemy",
                    "weapons",
                    "skill",
                    "options",
                    "dbName",
                    "dbValue",
                )
            ]
            tokens = searchDB(events, pbar, jobList, filename)
            totalTokens[0] += tokens[0]
            totalTokens[1] += tokens[1]

    except run_stop_errors():
        raise
    except IndexError as e:
        traceback.print_exc()
        raise Exception(str(e) + "Failed to translate: " + initialJAString) from None
    except Exception as e:
        traceback.print_exc()
        raise Exception(str(e) + "Failed to translate: " + initialJAString) from None

    return totalTokens

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
        mismatchList=MISMATCH,
    )
