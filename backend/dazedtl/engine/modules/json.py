# Libraries
import json
import os
import re
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
from util.translation import TranslationConfig, translateAI as sharedtranslateAI, getPricingConfig, calculateCost, getPricingConfig, calculateCost, found_mismatch, run_stop_errors
from util.translation_task import fail_on_parser_error, module_receipt, write_output
from util.sent_lines import SentLines
from util.speakers import strip_echoed_speaker, translate_speaker

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
FILENAME = None
NAMES = False  # Output a list of all the character names found
BRFLAG = False  # If the game uses <br> instead
FIXTEXTWRAP = True  # Overwrites textwrap
IGNORETLTEXT = False  # Ignores all translated text.
MISMATCH = []  # Lists files that throw a mismatch error (Length of GPT list response is wrong)

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

def handleJSON(filename, estimate):
    global ESTIMATE, totalTokens, FILENAME
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

        write_output(filename, json.dumps(translatedData[0], ensure_ascii=False, indent=4), newline="\n")

        # Print Result
        end = time.time()
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
    global LOCK, PBAR

    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
        pbar.desc = filename
        PBAR = pbar
        try:
            # Check if data is a simple key-value dict (not a list)
            if isinstance(data, dict) and not isinstance(data, list):
                # Check if it's a simple key-value format (all values are strings, not nested objects)
                if all(isinstance(v, str) for v in data.values()):
                    result = translateSimpleKeyValueJSON(data, filename)
                # PSData format (Nupu_PSData.json - MailDatas, MemoryData, ShopDatas, hStData)
                elif any(k in data for k in ["MailDatas", "MemoryData", "ShopDatas", "hStData"]):
                    result = translatePSData(data, filename)
                # RdData format (RdData.json - dgnDatas with dungeon/dialogue data)
                elif "dgnDatas" in data:
                    result = translateRdData(data, filename)
                # GameSetting format (Nupu_GameSetting.json - fzCardDatas, fzDeckDatas, rentalDecks)
                elif any(k in data for k in ["fzCardDatas", "fzDeckDatas", "rentalDecks"]):
                    result = translateGameSetting(data, filename)
                # Src/Tl dialogue format (numeric-keyed entries with src and tl fields)
                elif data and all(isinstance(v, dict) and "src" in v for v in data.values()):
                    result = translateDialogueSrcTl(data, filename)
                else:
                    result = translateJSON(data, filename)
            else:
                result = translateJSON(data, filename)
            totalTokens[0] += result[0]
            totalTokens[1] += result[1]
        except run_stop_errors():
            raise
        except Exception as e:
            traceback.print_exc()
            return [data, totalTokens, e]
    return [data, totalTokens, None]


def translateSimpleKeyValueJSON(data, filename):
    """
    Translate simple key-value JSON format where keys contain Japanese text
    and values are placeholder strings like "TODO".
    
    Format example:
    {
        "\\r\\nスタビライザー": "TODO",
        "\\r\\nプラグインなし": "TODO"
    }
    """
    global LOCK, ESTIMATE, FILENAME, PBAR, MISMATCH
    tokens = [0, 0]
    stringList = []
    keyList = []
    
    # Pass 1: Collect all keys that need translation
    for key, value in data.items():
        # Check if the key contains text matching the language regex
        if re.search(LANGREGEX, key):
            # Strip whitespace and newline characters for translation
            # cleanKey = key.strip().replace("\r\n", "").replace("\n", "").replace("\r", "")
            # if cleanKey:
            stringList.append(key)
            keyList.append(key)  # Store original key for reference
    
    # Translate all keys if any were found
    if stringList:
        PBAR.total = len(stringList)
        PBAR.refresh()
        
        response = translateAI(stringList, "Reply with the English Translation")
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        translatedList = response[0]
        
        # Check for mismatch
        if len(stringList) != len(translatedList):
            with LOCK:
                found_mismatch(MISMATCH, FILENAME)
        
        # Pass 2: Update the values with translations
        for i, key in enumerate(keyList):
            if i < len(translatedList):
                translatedText = translatedList[i]
                # Set the translated text as the value
                data[key] = translatedText
    
    return tokens


def translatePSData(data, filename):
    """Translate PSData JSON format (e.g. Nupu_PSData.json).
    
    Handles four sections:
    - MailDatas: In-game mail/message system
    - MemoryData: Scene/CG gallery memories  
    - ShopDatas: Shop configurations and dialogue
    - hStData: Status rank descriptions
    
    Only translates player-visible text fields.
    """
    global LOCK, ESTIMATE, FILENAME, PBAR, MISMATCH
    tokens = [0, 0]

    def batchTranslate(stringList, context):
        """Translate a list of strings and return translations. Returns [] on mismatch."""
        nonlocal tokens
        if not stringList:
            return []
        response = translateAI(stringList, context)
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        if len(stringList) != len(response[0]):
            with LOCK:
                found_mismatch(MISMATCH, FILENAME)
            return []
        return response[0]

    # ================================================================
    # PASS 1: Collect all translatable strings from every section
    # ================================================================

    # -- MailDatas --
    mailNameS, mailNameI = [], []
    mailTitleS, mailTitleI = [], []
    mailListNameS, mailListNameI = [], []
    mailTextS, mailTextI = [], []

    if "MailDatas" in data:
        for i, m in enumerate(data["MailDatas"]):
            if m.get("Name"):
                mailNameS.append(m["Name"])
                mailNameI.append(i)
            if m.get("Title"):
                mailTitleS.append(m["Title"])
                mailTitleI.append(i)
            if m.get("MailListName"):
                mailListNameS.append(m["MailListName"])
                mailListNameI.append(i)
            if m.get("MailText"):
                mailTextS.append(m["MailText"].replace("\r\n", " ").replace("\n", " ").strip())
                mailTextI.append(i)

    # -- MemoryData --
    memTitleS, memTitleI = [], []
    memSetuS, memSetuI = [], []
    memHintS, memHintI = [], []
    memPtnS, memPtnI = [], []        # indices are (memIdx, ptnIdx)
    memDtlSetuS, memDtlSetuI = [], []  # indices are (memIdx, dtlIdx)

    if "MemoryData" in data:
        for i, mem in enumerate(data["MemoryData"]):
            if mem.get("_Title"):
                memTitleS.append(mem["_Title"])
                memTitleI.append(i)
            if mem.get("_Setu"):
                memSetuS.append(mem["_Setu"].replace("\r\n", " ").replace("\n", " ").strip())
                memSetuI.append(i)
            if mem.get("_Hint"):
                memHintS.append(mem["_Hint"])
                memHintI.append(i)
            if "_Ptn" in mem and isinstance(mem["_Ptn"], list):
                for j, p in enumerate(mem["_Ptn"]):
                    if p:
                        memPtnS.append(p)
                        memPtnI.append((i, j))
            if "_DtlCheck" in mem and isinstance(mem["_DtlCheck"], list):
                for j, dtl in enumerate(mem["_DtlCheck"]):
                    if isinstance(dtl, dict) and dtl.get("_Setu"):
                        memDtlSetuS.append(dtl["_Setu"].replace("\r\n", " ").replace("\n", " ").strip())
                        memDtlSetuI.append((i, j))

    # -- ShopDatas --
    shopNameS, shopNameI = [], []
    shopTextFields = ["buySelf", "emptySelf", "firstSelf", "husokuSelf",
                      "randSelf1", "randSelf2", "randSelf3"]
    shopTextS = {f: [] for f in shopTextFields}
    shopTextI = {f: [] for f in shopTextFields}

    if "ShopDatas" in data:
        for i, shop in enumerate(data["ShopDatas"]):
            if shop.get("name"):
                shopNameS.append(shop["name"])
                shopNameI.append(i)
            for field in shopTextFields:
                if field in shop and isinstance(shop[field], dict):
                    text = shop[field].get("text", "")
                    if text:
                        shopTextS[field].append(text.replace("\r\n", " ").replace("\n", " ").strip())
                        shopTextI[field].append(i)

    # -- hStData --
    rankArrayNames = ["KutiRankDatas", "MuneRankDatas", "SiriRankDatas", "TituRankDatas"]
    rankSetuS, rankSetuI = [], []      # indices are (arrayName, idx)
    rankText1S, rankText1I = [], []
    rankText2S, rankText2I = [], []

    if "hStData" in data:
        hst = data["hStData"]
        for arrName in rankArrayNames:
            if arrName in hst and isinstance(hst[arrName], list):
                for i, rank in enumerate(hst[arrName]):
                    if rank.get("rankSetu"):
                        rankSetuS.append(rank["rankSetu"].replace("\r\n", " ").replace("\n", " ").strip())
                        rankSetuI.append((arrName, i))
                    if rank.get("rankText1"):
                        rankText1S.append(rank["rankText1"])
                        rankText1I.append((arrName, i))
                    if rank.get("rankText2"):
                        rankText2S.append(rank["rankText2"])
                        rankText2I.append((arrName, i))

    # Set progress bar total
    totalItems = (
        len(mailNameS) + len(mailTitleS) + len(mailListNameS) + len(mailTextS)
        + len(memTitleS) + len(memSetuS) + len(memHintS) + len(memPtnS) + len(memDtlSetuS)
        + len(shopNameS) + sum(len(v) for v in shopTextS.values())
        + len(rankSetuS) + len(rankText1S) + len(rankText2S)
    )
    PBAR.total = totalItems
    PBAR.refresh()

    # ================================================================
    # PASS 2: Translate each batch and apply results back to data
    # ================================================================

    # -- MailDatas --
    if "MailDatas" in data:
        mails = data["MailDatas"]

        for tl, idx in zip(batchTranslate(mailNameS, "Character Name"), mailNameI):
            mails[idx]["Name"] = tl

        for tl, idx in zip(batchTranslate(mailTitleS, "Mail Subject"), mailTitleI):
            mails[idx]["Title"] = tl

        for tl, idx in zip(batchTranslate(mailListNameS, "Mail List Entry"), mailListNameI):
            mails[idx]["MailListName"] = tl

        for tl, idx in zip(batchTranslate(mailTextS, "Mail Body Text"), mailTextI):
            mails[idx]["MailText"] = dazedwrap.wrapText(tl, WIDTH)

    # -- MemoryData --
    if "MemoryData" in data:
        memories = data["MemoryData"]

        for tl, idx in zip(batchTranslate(memTitleS, "Scene Title"), memTitleI):
            memories[idx]["_Title"] = tl

        for tl, idx in zip(batchTranslate(memSetuS, "Scene Description"), memSetuI):
            memories[idx]["_Setu"] = tl

        for tl, idx in zip(batchTranslate(memHintS, "Hint Text"), memHintI):
            memories[idx]["_Hint"] = tl

        for tl, (mi, pi) in zip(batchTranslate(memPtnS, "Scene Description"), memPtnI):
            memories[mi]["_Ptn"][pi] = tl

        for tl, (mi, di) in zip(batchTranslate(memDtlSetuS, "Character Commentary"), memDtlSetuI):
            memories[mi]["_DtlCheck"][di]["_Setu"] = dazedwrap.wrapText(tl, LISTWIDTH)

    # -- ShopDatas --
    if "ShopDatas" in data:
        shops = data["ShopDatas"]

        for tl, idx in zip(batchTranslate(shopNameS, "Shop Name"), shopNameI):
            shops[idx]["name"] = tl

        for field in shopTextFields:
            for tl, idx in zip(batchTranslate(shopTextS[field], "Shop Dialogue"), shopTextI[field]):
                shops[idx][field]["text"] = dazedwrap.wrapText(tl, WIDTH)

    # -- hStData --
    if "hStData" in data:
        hst = data["hStData"]

        for tl, (an, idx) in zip(batchTranslate(rankSetuS, "Rank Description"), rankSetuI):
            hst[an][idx]["rankSetu"] = dazedwrap.wrapText(tl, WIDTH)

        for tl, (an, idx) in zip(batchTranslate(rankText1S, "Rank Label"), rankText1I):
            hst[an][idx]["rankText1"] = tl

        for tl, (an, idx) in zip(batchTranslate(rankText2S, "Rank Subtitle"), rankText2I):
            hst[an][idx]["rankText2"] = tl

    return tokens


def translateRdData(data, filename):
    """Translate RdData JSON format (e.g. RdData.json).
    
    Handles dungeon data with nested dialogue, choices, and UI text.
    Only translates player-visible text fields.
    """
    global LOCK, ESTIMATE, FILENAME, PBAR, MISMATCH
    tokens = [0, 0]

    def batchTranslate(stringList, context):
        """Translate a list of strings and return translations. Returns [] on mismatch."""
        nonlocal tokens
        if not stringList:
            return []
        response = translateAI(stringList, context)
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        if len(stringList) != len(response[0]):
            with LOCK:
                found_mismatch(MISMATCH, FILENAME)
            return []
        return response[0]

    if "dgnDatas" not in data:
        return tokens

    dgns = data["dgnDatas"]

    # ================================================================
    # PASS 1: Collect all translatable strings
    # ================================================================

    # -- Dungeon-level short fields --
    dgnNameS, dgnNameI = [], []
    clearTxtS, clearTxtI = [], []
    hosyuTxtS, hosyuTxtI = [], []
    firstHosyuTxtS, firstHosyuTxtI = [], []
    memoTxtS, memoTxtI = [], []
    appMemoTxtS, appMemoTxtI = [], []
    areaMemoS, areaMemoI = [], []

    # -- Dungeon-level long text fields --
    naiyoTxtS, naiyoTxtI = [], []
    naiyoTxtExS, naiyoTxtExI = [], []
    johoTxtS, johoTxtI = [], []
    johoTxtExS, johoTxtExI = [], []

    # -- Floor names --
    kaisoNameS, kaisoNameI = [], []  # (dgnIdx, kaisoIdx)

    # -- Dialogue (talkDatas / talkDatasEx) --
    talkNameS, talkNameI = [], []               # (dgnIdx, talkKey, talkIdx)
    speakerNameS, speakerNameI = [], []         # (dgnIdx, talkKey, talkIdx, speechIdx)
    dialogueS, dialogueI = [], []               # (dgnIdx, talkKey, talkIdx, speechIdx)

    # -- Choice events (sijiDatas) --
    sijiNameS, sijiNameI = [], []               # (dgnIdx, sijiIdx)
    sijiChoiceS, sijiChoiceI = [], []           # (dgnIdx, sijiIdx)

    for di, dgn in enumerate(dgns):
        if dgn is None:
            continue

        # Dungeon short fields
        if dgn.get("name"):
            dgnNameS.append(dgn["name"])
            dgnNameI.append(di)
        if dgn.get("clearTxt"):
            clearTxtS.append(dgn["clearTxt"])
            clearTxtI.append(di)
        if dgn.get("hosyuTxt"):
            hosyuTxtS.append(dgn["hosyuTxt"])
            hosyuTxtI.append(di)
        if dgn.get("firstHosyuTxt"):
            firstHosyuTxtS.append(dgn["firstHosyuTxt"])
            firstHosyuTxtI.append(di)
        if dgn.get("memoTxt"):
            memoTxtS.append(dgn["memoTxt"])
            memoTxtI.append(di)
        if dgn.get("appMemoTxt"):
            appMemoTxtS.append(dgn["appMemoTxt"])
            appMemoTxtI.append(di)
        if dgn.get("areaMemo"):
            areaMemoS.append(dgn["areaMemo"])
            areaMemoI.append(di)

        # Dungeon long text fields (strip line breaks for translation)
        if dgn.get("naiyoTxt"):
            naiyoTxtS.append(dgn["naiyoTxt"].replace("\r\n", " ").replace("\n", " ").strip())
            naiyoTxtI.append(di)
        if dgn.get("naiyoTxtEx"):
            naiyoTxtExS.append(dgn["naiyoTxtEx"].replace("\r\n", " ").replace("\n", " ").strip())
            naiyoTxtExI.append(di)
        if dgn.get("johoTxt"):
            johoTxtS.append(dgn["johoTxt"].replace("\r\n", " ").replace("\n", " ").strip())
            johoTxtI.append(di)
        if dgn.get("johoTxtEx"):
            johoTxtExS.append(dgn["johoTxtEx"].replace("\r\n", " ").replace("\n", " ").strip())
            johoTxtExI.append(di)

        # Floor names
        if "kaisoDatas" in dgn and isinstance(dgn["kaisoDatas"], list):
            for ki, kaiso in enumerate(dgn["kaisoDatas"]):
                if isinstance(kaiso, dict) and kaiso.get("kaisoName"):
                    kaisoNameS.append(kaiso["kaisoName"])
                    kaisoNameI.append((di, ki))

        # Dialogue from talkDatas and talkDatasEx
        for talkKey in ["talkDatas", "talkDatasEx"]:
            if talkKey in dgn and isinstance(dgn[talkKey], list):
                for ti, talk in enumerate(dgn[talkKey]):
                    if not isinstance(talk, dict):
                        continue
                    if talk.get("name"):
                        talkNameS.append(talk["name"])
                        talkNameI.append((di, talkKey, ti))
                    if "speachDatas" in talk and isinstance(talk["speachDatas"], list):
                        for si, speech in enumerate(talk["speachDatas"]):
                            if not isinstance(speech, dict):
                                continue
                            if speech.get("name"):
                                speakerNameS.append(speech["name"])
                                speakerNameI.append((di, talkKey, ti, si))
                            if speech.get("text"):
                                dialogueS.append(speech["text"].replace("\r\n", " ").replace("\n", " ").strip())
                                dialogueI.append((di, talkKey, ti, si))

        # Choice events (sijiDatas)
        if "sijiDatas" in dgn and isinstance(dgn["sijiDatas"], list):
            for si, siji in enumerate(dgn["sijiDatas"]):
                if not isinstance(siji, dict):
                    continue
                if siji.get("name"):
                    sijiNameS.append(siji["name"])
                    sijiNameI.append((di, si))
                if siji.get("choiceSijiTxt"):
                    sijiChoiceS.append(siji["choiceSijiTxt"].replace("\r\n", " ").replace("\n", " ").strip())
                    sijiChoiceI.append((di, si))

    # Set progress bar total
    totalItems = (
        len(dgnNameS) + len(clearTxtS) + len(hosyuTxtS) + len(firstHosyuTxtS)
        + len(memoTxtS) + len(appMemoTxtS) + len(areaMemoS)
        + len(naiyoTxtS) + len(naiyoTxtExS) + len(johoTxtS) + len(johoTxtExS)
        + len(kaisoNameS)
        + len(talkNameS) + len(speakerNameS) + len(dialogueS)
        + len(sijiNameS) + len(sijiChoiceS)
    )
    PBAR.total = totalItems
    PBAR.refresh()

    # ================================================================
    # PASS 2: Translate each batch and apply results back to data
    # ================================================================

    # -- Dungeon short fields --
    for tl, idx in zip(batchTranslate(dgnNameS, "Dungeon Name"), dgnNameI):
        dgns[idx]["name"] = tl

    for tl, idx in zip(batchTranslate(clearTxtS, "Clear Condition"), clearTxtI):
        dgns[idx]["clearTxt"] = tl

    for tl, idx in zip(batchTranslate(hosyuTxtS, "Reward Description"), hosyuTxtI):
        dgns[idx]["hosyuTxt"] = tl

    for tl, idx in zip(batchTranslate(firstHosyuTxtS, "First Clear Reward"), firstHosyuTxtI):
        dgns[idx]["firstHosyuTxt"] = tl

    for tl, idx in zip(batchTranslate(memoTxtS, "Memo Label"), memoTxtI):
        dgns[idx]["memoTxt"] = tl

    for tl, idx in zip(batchTranslate(appMemoTxtS, "App Memo"), appMemoTxtI):
        dgns[idx]["appMemoTxt"] = tl

    for tl, idx in zip(batchTranslate(areaMemoS, "Area Label"), areaMemoI):
        dgns[idx]["areaMemo"] = tl

    # -- Dungeon long text fields (with word wrap) --
    for tl, idx in zip(batchTranslate(naiyoTxtS, "Mission Description"), naiyoTxtI):
        dgns[idx]["naiyoTxt"] = dazedwrap.wrapText(tl, WIDTH)

    for tl, idx in zip(batchTranslate(naiyoTxtExS, "Extended Mission Description"), naiyoTxtExI):
        dgns[idx]["naiyoTxtEx"] = dazedwrap.wrapText(tl, WIDTH)

    for tl, idx in zip(batchTranslate(johoTxtS, "Info Text"), johoTxtI):
        dgns[idx]["johoTxt"] = dazedwrap.wrapText(tl, WIDTH)

    for tl, idx in zip(batchTranslate(johoTxtExS, "Extended Info Text"), johoTxtExI):
        dgns[idx]["johoTxtEx"] = dazedwrap.wrapText(tl, WIDTH)

    # -- Floor names --
    for tl, (di, ki) in zip(batchTranslate(kaisoNameS, "Floor Name"), kaisoNameI):
        dgns[di]["kaisoDatas"][ki]["kaisoName"] = tl

    # -- Dialogue event names --
    for tl, (di, tk, ti) in zip(batchTranslate(talkNameS, "Event Label"), talkNameI):
        dgns[di][tk][ti]["name"] = tl

    # -- Speaker names --
    for tl, (di, tk, ti, si) in zip(batchTranslate(speakerNameS, "Character Name"), speakerNameI):
        dgns[di][tk][ti]["speachDatas"][si]["name"] = tl

    # -- Dialogue text (with word wrap) --
    for tl, (di, tk, ti, si) in zip(batchTranslate(dialogueS, "Dialogue"), dialogueI):
        dgns[di][tk][ti]["speachDatas"][si]["text"] = dazedwrap.wrapText(tl, WIDTH)

    # -- Choice event names --
    for tl, (di, si) in zip(batchTranslate(sijiNameS, "Event Name"), sijiNameI):
        dgns[di]["sijiDatas"][si]["name"] = tl

    # -- Choice text (with word wrap) --
    for tl, (di, si) in zip(batchTranslate(sijiChoiceS, "Choice Event Text"), sijiChoiceI):
        dgns[di]["sijiDatas"][si]["choiceSijiTxt"] = dazedwrap.wrapText(tl, WIDTH)

    return tokens


def translateGameSetting(data, filename):
    """Translate GameSetting JSON format (e.g. Nupu_GameSetting.json).
    
    Handles card data, deck definitions, and rental decks.
    Only translates player-visible text fields.
    """
    global LOCK, ESTIMATE, FILENAME, PBAR, MISMATCH
    tokens = [0, 0]

    def batchTranslate(stringList, context):
        """Translate a list of strings and return translations. Returns [] on mismatch."""
        nonlocal tokens
        if not stringList:
            return []
        response = translateAI(stringList, context)
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        if len(stringList) != len(response[0]):
            with LOCK:
                found_mismatch(MISMATCH, FILENAME)
            return []
        return response[0]

    # ================================================================
    # PASS 1: Collect all translatable strings
    # ================================================================

    # -- fzCardDatas: card descriptions --
    desc1S, desc1I = [], []
    desc2S, desc2I = [], []

    if "fzCardDatas" in data:
        for i, card in enumerate(data["fzCardDatas"]):
            if card.get("desc1"):
                desc1S.append(card["desc1"].replace("\r\n", " ").replace("\n", " ").strip())
                desc1I.append(i)
            if card.get("desc2"):
                desc2S.append(card["desc2"].replace("\r\n", " ").replace("\n", " ").strip())
                desc2I.append(i)

    # -- fzDeckDatas: deck name and description --
    deckNameS, deckNameI = [], []
    deckDescS, deckDescI = [], []

    if "fzDeckDatas" in data:
        for i, deck in enumerate(data["fzDeckDatas"]):
            if deck.get("name"):
                deckNameS.append(deck["name"])
                deckNameI.append(i)
            if deck.get("desc"):
                deckDescS.append(deck["desc"].replace("\r\n", " ").replace("\n", " ").strip())
                deckDescI.append(i)

    # -- rentalDecks: memo label --
    rentalMemoS, rentalMemoI = [], []

    if "rentalDecks" in data:
        for i, rental in enumerate(data["rentalDecks"]):
            if rental.get("memo"):
                rentalMemoS.append(rental["memo"])
                rentalMemoI.append(i)

    # Set progress bar total
    totalItems = (
        len(desc1S) + len(desc2S)
        + len(deckNameS) + len(deckDescS)
        + len(rentalMemoS)
    )
    PBAR.total = totalItems
    PBAR.refresh()

    # ================================================================
    # PASS 2: Translate each batch and apply results back to data
    # ================================================================

    # -- fzCardDatas --
    if "fzCardDatas" in data:
        cards = data["fzCardDatas"]

        for tl, idx in zip(batchTranslate(desc1S, "Card Description"), desc1I):
            cards[idx]["desc1"] = dazedwrap.wrapText(tl, WIDTH)

        for tl, idx in zip(batchTranslate(desc2S, "Card Description"), desc2I):
            cards[idx]["desc2"] = dazedwrap.wrapText(tl, WIDTH)

    # -- fzDeckDatas --
    if "fzDeckDatas" in data:
        decks = data["fzDeckDatas"]

        for tl, idx in zip(batchTranslate(deckNameS, "Deck Name"), deckNameI):
            decks[idx]["name"] = tl

        for tl, idx in zip(batchTranslate(deckDescS, "Deck Description"), deckDescI):
            decks[idx]["desc"] = dazedwrap.wrapText(tl, WIDTH)

    # -- rentalDecks --
    if "rentalDecks" in data:
        rentals = data["rentalDecks"]

        for tl, idx in zip(batchTranslate(rentalMemoS, "Deck Label"), rentalMemoI):
            rentals[idx]["memo"] = tl

    return tokens


def translateDialogueSrcTl(data, filename):
    """Translate src/tl dialogue JSON format.

    Format:
    {
        "0": {"type": "dialogue", "src": "Japanese text", "tl": ""},
        "4": {"type": "dialogue", "speaker": "琴音", "src": "「...」", "tl": ""}
    }

    Translates 'src' into 'tl'. Also translates Japanese 'speaker' fields.
    Skips entries where 'tl' is already populated.
    """
    global LOCK, ESTIMATE, FILENAME, PBAR, MISMATCH
    tokens = [0, 0]
    lines = SentLines(unlabel=_unlabel)

    # Send each entry with translatable content (util/sent_lines)
    for key, entry in data.items():
        if not isinstance(entry, dict):
            continue
        src = entry.get("src", "")
        if not src:
            continue
        tl = entry.get("tl", "")

        if tl:
            # Already has a translation — send tl so the module can decide to skip it
            lines.send(tl, _field_writer(entry, "tl"))
        else:
            if not re.search(LANGREGEX, src):
                continue
            srcClean = src.replace("\r\n", " ").replace("\n", " ").strip()
            lines.send(srcClean, _field_writer(entry, "tl"), entry.get("speaker", ""))

    if len(lines) > 0:
        PBAR.total = len(lines)
        PBAR.refresh()

        response = translateAI(lines.lines, "Reply with the English Translation")
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        translatedList = response[0]

        if len(lines) != len(translatedList):
            with LOCK:
                found_mismatch(MISMATCH, FILENAME)

        # A short reply list still answers the entries it reaches
        lines.write(translatedList)

    # Translate any Japanese speaker names found in the data
    seen_speakers = {}
    for key, entry in data.items():
        if not isinstance(entry, dict):
            continue
        speaker = entry.get("speaker", "")
        if not speaker or not re.search(LANGREGEX, speaker):
            continue
        if speaker not in seen_speakers:
            response = getSpeaker(speaker)
            tokens[0] += response[1][0]
            tokens[1] += response[1][1]
            seen_speakers[speaker] = response[0]
        data[key]["speaker"] = seen_speakers[speaker]

    return tokens


# The event list format's fields, each sent as its own list with this history
EVENT_FIELDS = (
    ("title", "Event Title"),
    ("process", "Event Process"),
    ("text", "Event Description"),
    ("key", "Event Key"),
    ("target", "Character Name"),
    ("job", "Job/Occupation"),
    ("place", "Location Name"),
)


def translateJSON(data, filename):
    """Translates a list of entries: the event list format's fields, and the
    dialogue list format's messages with the speaker each entry names. Walks
    the entries once, translating speakers on the spot and sending each
    field and message with the place its reply goes (util/sent_lines), then
    writes each reply there."""
    global LOCK, ESTIMATE, FILENAME, PBAR, MISMATCH
    tokens = [0, 0]
    speakerKey = "character_nameText"
    messageKey = "m_text"
    events = {field: SentLines(unlabel=None) for field, _history in EVENT_FIELDS}
    dialogue = SentLines(unlabel=_unlabel)

    for i in range(len(data)):
        entry = data[i]

        # Event List Format
        for field, _history in EVENT_FIELDS:
            if field in entry and entry[field]:
                jaString = entry[field]
                if field == "text":
                    # Replace \n with space for translation
                    jaString = jaString.replace("\n", " ")
                events[field].send(jaString.strip(), _field_writer(entry, field))

        # Speaker: the entry's own, so an entry without one has none, as
        # speakers come only from the game's own nameplates
        speaker = ""
        if speakerKey in entry and entry[speakerKey]:
            # Grab and TL
            response = getSpeaker(entry[speakerKey])
            speaker = response[0]
            tokens[0] += response[1][0]
            tokens[1] += response[1][1]

            # Set Speaker
            entry[speakerKey] = speaker

        # Dialogue, unless it holds no Japanese
        if messageKey in entry\
            and entry[messageKey].strip()\
            and entry[messageKey] != "a"\
            and entry[messageKey].replace("\u3000", "").strip() != ""\
            and re.search(LANGREGEX, entry[messageKey]):
            dialogue.send(entry[messageKey].strip(), _message_writer(entry, messageKey), speaker)

    # EOF
    lists = [(events[field], history) for field, history in EVENT_FIELDS]
    lists.append((dialogue, "Reply with the English Translation"))
    totalItems = sum(len(lines) for lines, _history in lists)
    if totalItems > 0:
        PBAR.total = totalItems
        PBAR.refresh()
    replies = [
        (lines, _translate(lines, history, tokens)) for lines, history in lists if lines
    ]

    # A short reply list still answers the entries it reaches
    for lines, translated in replies:
        lines.write(translated)
    return tokens


def _translate(lines, history, tokens):
    """The replies to *lines*, sent as one list with *history*; adds the
    request's tokens to *tokens* and reports a reply list of another length."""
    response = translateAI(lines.lines, history)
    tokens[0] += response[1][0]
    tokens[1] += response[1][1]
    if len(lines) != len(response[0]):
        with LOCK:
            found_mismatch(MISMATCH, FILENAME)
    return response[0]


def _unlabel(translatedText, speaker):
    """A dialogue reply without the speaker it was sent with, or one the model
    echoed: [Name]: / Name: / CJK(text) (util/speakers)."""
    return strip_echoed_speaker(translatedText, LANGUAGE, speaker)


def _field_writer(entry, field):
    """Writes a reply to *entry*'s *field*, an event description wrapped."""

    def write(translatedText):
        if field == "text":
            # Apply text wrapping and restore linebreaks
            translatedText = dazedwrap.wrapText(translatedText, 70)
        entry[field] = translatedText

    return write


def _message_writer(entry, messageKey):
    """Writes a dialogue reply over *entry*'s message."""
    originalString = entry[messageKey]

    def write(translatedText):
        # Escape Quotes
        translatedText = re.sub(r'(?<!\\)"', r"", translatedText)

        # Remove characters that may break scripts
        translatedText = translatedText.replace("『", "")
        translatedText = translatedText.replace("』", "")

        # Remove GPT ' Quotes
        if translatedText:
            if translatedText[0] == "'":
                translatedText = translatedText[1:]
            if translatedText[-1] == "'":
                translatedText = translatedText[:-1]
        else:
            print("Warning: Empty Translation for", originalString)

        # Set Data
        if "『" in entry[messageKey] and "』" not in translatedText:
            entry[messageKey] = entry[messageKey].replace(originalString, f"『{translatedText}』")
        else:
            entry[messageKey] = entry[messageKey].replace(originalString, f"{translatedText}")

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
