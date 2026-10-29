"""Translate ``image_text.json`` - the text found in a game's images.

Step 3 of the image workflow. The user reads the images and confirms the boxes
in the review editor (Images tab -> "Edit text..."), which exports this file
into ``files/``; they then pick the **Image Text** module here and press
Translate like any other engine.

Running it as a normal translation module rather than a one-off button is the
point: progress, the live log, cost accounting, estimate mode, and the project's
prompt and glossary all come for free and behave exactly as they do everywhere
else in the tool.

**One request per image.** See ``_instruction``: batching across images let one
picture's tone and vocabulary bleed into another's, and a single bad line
poisoned strings from unrelated files.

Only ``target`` is written. Boxes and source text belong to the toolkit and are
passed through untouched, so a run here can never move a text box.
"""

# Libraries
import json
import os
import threading
import time
import traceback
from colorama import Fore
from tqdm import tqdm
from util.languages import source_pattern
from util.translation import (
    TranslationConfig,
    translateAI as sharedtranslateAI,
    getPricingConfig,
    calculateCost,
    report_mismatch,
    run_stop_errors,
)
from util.translation_task import fail_on_parser_error, module_receipt, write_output

# Globals
MODEL = os.getenv("model")
LANGUAGE = (os.getenv("language") or "English").capitalize()
from util.paths import PROMPT_PATH, read_active_glossary

PROMPT = PROMPT_PATH.read_text(encoding="utf-8")
VOCAB = read_active_glossary()
LOCK = threading.Lock()
ESTIMATE = ""
TOKENS = [0, 0]
MISMATCH = []
FILENAME = None

# tqdm Globals
BAR_FORMAT = "{l_bar}{bar:10}{r_bar}{bar:-10b}"
POSITION = 0
LEAVE = False
PBAR = None

LANGREGEX = source_pattern("imagetext")

PRICING_CONFIG = getPricingConfig(MODEL)
BATCHSIZE = PRICING_CONFIG["batchSize"]

TRANSLATION_CONFIG = TranslationConfig(
    model=MODEL,
    language=LANGUAGE,
    prompt=PROMPT,
    vocab=VOCAB,
    langRegex=LANGREGEX,
    batchSize=BATCHSIZE,
    maxHistory=10,
    estimateMode=False,
)

# Upper bound on one request. Requests are cut at the image boundary first;
# this only splits a single image that holds an unusual number of blocks, so
# one bad batch stays cheap to retry.
GROUP_SIZE = 20


def _instruction(image_name, count, part=0, parts=1):
    """The context for one image's request.

    Every request covers exactly one image, and says so. Batching across images
    let a dense tutorial diagram bleed into a two-word menu tab - the model
    carried tone and vocabulary from a neighbouring picture it should never
    have seen, and a single bad line poisoned strings from files that had
    nothing to do with each other. Naming the image also gives the model the
    one piece of context it genuinely has no other way to infer.
    """
    where = f" (part {part + 1} of {parts})" if parts > 1 else ""
    return (
        "You are translating text that is baked into a game's artwork - a UI "
        "image, not dialogue from a script.\n"
        f"All {count} line(s) below come from the SAME image: {image_name}{where}. "
        "Treat them as one screen that a player sees at once, and keep names, "
        "tone and terminology consistent across them.\n"
        "Each line is a separate label, button, tab, or short passage, and each "
        "must be translated on its own line, in the same order, with the same "
        "number of lines out as in.\n"
        "Keep every translation as short as the original allows: it has to fit "
        "back inside the space the original occupied, and a menu button is not "
        "a sentence.\n"
        "Preserve numbers, percent signs, and placeholders such as ??? exactly. "
        "Leave symbols that are not language (hearts, stars, arrows, musical "
        "notes) exactly as they appear, including their position in the line."
    )


def translateAI(text, history, history_ctx=None):
    """Legacy-shaped wrapper, matching the other engine modules."""
    global PBAR, MISMATCH, FILENAME

    TRANSLATION_CONFIG.estimateMode = bool(ESTIMATE)
    return sharedtranslateAI(
        text=text,
        history=history,
        config=TRANSLATION_CONFIG,
        filename=FILENAME,
        pbar=PBAR,
        lock=LOCK,
        mismatchList=MISMATCH,
    )


def _pending_by_image(data, retranslate=False):
    """``[(image_name, [region, ...]), ...]`` - never mixing two images.

    Grouping happens here rather than over a flat list so a request can only
    ever contain lines from one picture.
    """
    out = []
    for image in data.get("images") or []:
        if not isinstance(image, dict):
            continue
        regions = []
        for region in image.get("regions") or []:
            if not isinstance(region, dict):
                continue
            if not str(region.get("source") or "").strip():
                continue
            if retranslate or not str(region.get("target") or "").strip():
                regions.append(region)
        if regions:
            out.append((str(image.get("image") or "?"), regions))
    return out


def _pending(data, retranslate=False):
    """Flat count of everything still needing a translation."""
    return [
        region
        for _name, regions in _pending_by_image(data, retranslate)
        for region in regions
    ]


def openFiles(filename):
    global PBAR

    path = os.path.join("files", filename)
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or "images" not in data:
        raise ValueError(
            f"{filename} is not a DazedTL image text file "
            "(expected an object with an 'images' list). "
            "Produce it with 'imgtl export'."
        )

    byImage = _pending_by_image(data)
    total = sum(len(regions) for _name, regions in byImage)
    totalTokens = [0, 0]
    if not total:
        tqdm.write(f"{filename}: every string is already translated.")
        return [data, totalTokens, None]

    with tqdm(
        bar_format=BAR_FORMAT,
        position=POSITION,
        total=total,
        leave=LEAVE,
        desc=filename,
    ) as pbar:
        PBAR = pbar
        try:
            for imageName, regions in byImage:
                # One request per image. A very dense image is split, but only
                # within itself - the boundary between images is never crossed.
                parts = (len(regions) + GROUP_SIZE - 1) // GROUP_SIZE
                imageTokens = [0, 0]
                done = 0
                for part in range(parts):
                    group = regions[part * GROUP_SIZE : (part + 1) * GROUP_SIZE]
                    # Newlines inside a block are the source art's own line
                    # breaks. They are flattened for the request and not
                    # restored: the renderer re-wraps to the region's width, so
                    # keeping Japanese line breaks would force English to break
                    # in the wrong places.
                    sources = [
                        " ".join(str(region["source"]).split()) for region in group
                    ]
                    response = translateAI(
                        sources, _instruction(imageName, len(group), part, parts)
                    )
                    translated = response[0]
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]
                    imageTokens[0] += response[1][0]
                    imageTokens[1] += response[1][1]

                    # The bar is not touched here: the shared translateAI already
                    # advances PBAR for every batch it sends, the same way it does
                    # for every other engine module. Updating it again here counted
                    # each block twice, which filled the bar at half the real
                    # progress and pinned it at 100% for the rest of the run.
                    if not isinstance(translated, list) or len(translated) != len(group):
                        got = len(translated) if isinstance(translated, list) else "?"
                        MISMATCH.append(
                            f"{imageName} (expected {len(group)}, got {got})"
                        )
                        report_mismatch(FILENAME)
                        continue

                    if not ESTIMATE:
                        for region, text in zip(group, translated):
                            region["target"] = str(text).strip()
                    done += len(group)

                # One line per image, written as it finishes rather than only at
                # the end of the whole file, so the log ticks over during the run
                # and shows how far along it is. Cost is deliberately left off: it
                # is computed once per file from thread-local accumulators that
                # calculateCost resets, and calling it here would empty them.
                progress = "estimated" if ESTIMATE else f"{done}/{len(regions)} translated"
                tqdm.write(
                    Fore.GREEN + f"  {imageName}" + Fore.RESET
                    + Fore.YELLOW
                    + f"  [{progress}]"
                    f"[Input: {imageTokens[0]}][Output: {imageTokens[1]}]"
                    + Fore.RESET
                )
        except run_stop_errors():
            raise
        except Exception as error:
            traceback.print_exc()
            return [data, totalTokens, error]
        finally:
            PBAR = None

    return [data, totalTokens, None]


def handleImageText(filename, estimate):
    global ESTIMATE, TOKENS, FILENAME
    ESTIMATE = estimate
    FILENAME = filename

    start = time.time()
    translatedData = openFiles(filename)
    fail_on_parser_error(translatedData)

    if not estimate:
        # Only translated/ is written: the Images task imports the run's
        # output from there. files/ is the run's engine input, a hard link to
        # its frozen inputs/, so writing it changed the run's record of what
        # it sent and stopped the run from resuming.
        payload = json.dumps(translatedData[0], ensure_ascii=False, indent=2)
        write_output(filename, payload, newline="\n")

    end = time.time()
    tqdm.write(module_receipt(filename, translatedData[1], end - start, MODEL))
    with LOCK:
        TOKENS[0] += translatedData[1][0]
        TOKENS[1] += translatedData[1][1]

    totalString = module_receipt("TOTAL", TOKENS, end - start, MODEL)
    if not estimate:
        remaining = len(_pending(translatedData[0]))
        tqdm.write("")
        tqdm.write(
            Fore.GREEN
            + "Image text translated. Reopen the Images tab -> \"Edit text...\" "
            "to pick the translations up."
            + Fore.RESET
        )
        if remaining:
            tqdm.write(
                Fore.YELLOW
                + f"{remaining} string(s) were left blank and still need a "
                "translation; run this again to retry them."
                + Fore.RESET
            )

    if len(MISMATCH) > 0:
        return totalString + Fore.RED + f"\nMismatch Errors: {MISMATCH}" + Fore.RESET
    return totalString
