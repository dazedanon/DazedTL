"""Read-only, bounded text views of the project's actual working JSON."""

from difflib import SequenceMatcher

from .files import digest, read_json

PAGE_SIZE = 80
TEXT_LIMIT = 8000


def text_fields(value, source=None, path=""):
    """Each text in *value* that differs from its *source*, with its
    location."""
    if isinstance(value, list):
        from util import rpgmaker_blocks as blocks

        if blocks.is_command_list(value):
            yield from _command_fields(blocks, value, source, path)
            return
    if isinstance(value, dict):
        original = value.get("_original")
        original = original if isinstance(original, dict) else {}
        for key, item in value.items():
            if key == "_original":
                continue
            before = original.get(
                key, source.get(key) if isinstance(source, dict) else None
            )
            escaped = str(key).replace("~", "~0").replace("/", "~1")
            yield from text_fields(item, before, path + "/" + escaped)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            before = (
                source[index]
                if isinstance(source, list) and index < len(source)
                else None
            )
            yield from text_fields(item, before, path + "/" + str(index))
    elif isinstance(value, str) and (
        value.strip() or isinstance(source, str) and source.strip()
    ):
        if isinstance(source, str) and source == value:
            return
        before = source if isinstance(source, str) else None
        yield {"location": path or "/", "text": value, "source": before}


def _matched(ours, theirs):
    """The positions in *ours* and *theirs* of the longest run of keys they
    share, in order."""
    matcher = SequenceMatcher(None, ours, theirs, autojunk=False)
    return [
        (mine + step, its + step)
        for mine, its, size in matcher.get_matching_blocks()
        for step in range(size)
    ]


def _command_fields(blocks, value, source, path):
    """An event command list beside its source. A text block, as
    util/rpgmaker_blocks defines it, reads as one text beside its source
    block's, since translation writes a message's text over its first row and
    drops the rows after it. Blocks pair by kind in order and the commands
    between them by code, so a command the engine drops or adds, such as the
    lines of a rewrapped script, shifts nothing after it."""
    source = source if isinstance(source, list) else []
    ours, theirs = list(blocks.blocks(value)), list(blocks.blocks(source))
    pairs = _matched([block.kind for block in ours], [block.kind for block in theirs])
    paired = {ours[ours_at].start for ours_at, _theirs_at in pairs}
    unpaired = {block.start: block for block in ours if block.start not in paired}
    inside = {row for block in theirs for row in range(block.start, block.end)}
    at = before = 0
    anchors = [(ours[ours_at], theirs[theirs_at]) for ours_at, theirs_at in pairs]
    for mine, its in [*anchors, (None, None)]:
        stop = mine.start if mine else len(value)
        until = its.start if its else len(source)
        loose = [
            spot
            for spot in range(before, until)
            if spot not in inside and not blocks.emptied(source[spot])
        ]
        # The commands between paired blocks, each beside the source
        # command of the same code in order.
        commands, index = [], at
        while index < stop:
            if index in unpaired:
                commands.append(unpaired[index])
                index = unpaired[index].end
                continue
            if not blocks.emptied(value[index]):
                commands.append(index)
            index += 1
        plain = [index for index in commands if isinstance(index, int)]
        found = {
            plain[ours_at]: loose[theirs_at]
            for ours_at, theirs_at in _matched(
                [blocks.code(value[index]) for index in plain],
                [blocks.code(source[index]) for index in loose],
            )
        }
        for item in commands:
            if isinstance(item, int):
                theirs_at = found.get(item)
                yield from text_fields(
                    value[item],
                    source[theirs_at] if theirs_at is not None else None,
                    f"{path}/{item}",
                )
            else:
                yield from _block_fields(blocks, value, source, path, item, None)
        if mine is not None:
            yield from _block_fields(blocks, value, source, path, mine, its)
            at, before = mine.end, its.end


def _block_fields(blocks, value, source, path, mine, its):
    """A text block's head, and its rows as one text beside *its* rows."""
    if mine.head is not None:
        head = source[its.head] if its is not None and its.head is not None else None
        yield from text_fields(value[mine.head], head, f"{path}/{mine.head}")
    if mine.kind == blocks.CHOICE or not mine.rows:
        return
    text = "\n".join(blocks.text(value[row]) for row in mine.rows)
    was = (
        "\n".join(blocks.text(source[row]) for row in its.rows)
        if its is not None
        else None
    )
    if text != was and (text.strip() or (was or "").strip()):
        yield {
            "location": f"{path}/{mine.rows[0]}/parameters/0",
            "text": text,
            "source": was,
        }


def _check(offset, query):
    if (
        type(offset) is not int
        or offset < 0
        or not isinstance(query, str)
        or len(query) > 256
    ):
        raise ValueError(
            "Choose a valid text page and search of at most 256 characters."
        )


def _page(name, origin, value, found, offset, query):
    """One page of rows matching the search."""
    rows, total, size = [], 0, 0
    needle = query.casefold().strip()
    for row in found:
        if (
            needle
            and needle
            not in " ".join(
                [row["location"], row["text"], row["source"] or ""]
            ).casefold()
        ):
            continue
        index = total
        total += 1
        if index < offset or len(rows) >= PAGE_SIZE or size >= 64_000:
            continue
        clipped = len(row["text"]) > TEXT_LIMIT or len(row["source"] or "") > TEXT_LIMIT
        row = {
            **row,
            "text": row["text"][:TEXT_LIMIT],
            "source": row["source"][:TEXT_LIMIT] if row["source"] is not None else None,
            "truncated": clipped,
        }
        size += len(row["text"]) + len(row["source"] or "")
        rows.append(row)
    return {
        "file": name,
        "origin": origin,
        "revision": digest(value),
        "rows": rows,
        "offset": offset,
        "total": total,
        "nextOffset": offset + len(rows) if offset + len(rows) < total else None,
    }


def _origin(inputs, name, runtime):
    working, output = inputs.path("files", name), inputs.path("translated", name)
    base = working if working.is_file() else runtime
    path = output if output.is_file() else base
    return (
        path,
        base,
        "translated" if path == output else "working" if path == working else "game",
    )


def preview(inputs, name, runtime, offset=0, query=""):
    _check(offset, query)
    path, base, origin = _origin(inputs, name, runtime)
    # The parser is for display only. It never decides which fields the engine
    # will translate and does not create working copies, estimates or receipts.
    value = read_json(path, limit=32_000_000)
    source = (
        read_json(base, limit=32_000_000) if path != base and base.is_file() else None
    )
    return _page(name, origin, value, text_fields(value, source), offset, query)


def lines_left(inputs, name, runtime, phase, markers, offset=0, query=""):
    """The lines still left in the file's newest copy, as its Lines count
    reads them (file_lines.left)."""
    from dazedtl.languages import reading_game

    from .file_lines import left

    _check(offset, query)
    path, _base, origin = _origin(inputs, name, runtime)
    value = read_json(path, limit=32_000_000)
    with reading_game(inputs.source):
        found = [
            {**row, "source": row["source"] or None}
            for row in left(
                name, value, phase, markers, lambda: inputs.original_document(name)
            )
        ]
    return _page(name, origin, value, found, offset, query)
