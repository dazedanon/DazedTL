"""Read-only, bounded text views of the project's actual working JSON."""
from .files import digest, read_json

PAGE_SIZE = 80
TEXT_LIMIT = 8000


def text_fields(value, source=None, path=""):
    if isinstance(value, dict):
        original = value.get("_original")
        original = original if isinstance(original, dict) else {}
        for key, item in value.items():
            if key == "_original":
                continue
            before = original.get(key, source.get(key) if isinstance(source, dict) else None)
            escaped = str(key).replace("~", "~0").replace("/", "~1")
            yield from text_fields(item, before, path + "/" + escaped)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            before = source[index] if isinstance(source, list) and index < len(source) else None
            yield from text_fields(item, before, path + "/" + str(index))
    elif isinstance(value, str) and (value.strip() or isinstance(source, str) and source.strip()):
        before = source if isinstance(source, str) and source != value else None
        yield {"location": path or "/", "text": value, "source": before}


def preview(inputs, name, runtime, offset=0, query=""):
    if type(offset) is not int or offset < 0 or not isinstance(query, str) or len(query) > 256:
        raise ValueError("Choose a valid text page and search of at most 256 characters.")
    working, output = inputs.path("files", name), inputs.path("translated", name)
    base = working if working.is_file() else runtime
    path = output if output.is_file() else base
    origin = "translated" if path == output else "working" if path == working else "game"
    # The parser is for display only. It never decides which fields the engine
    # will translate and does not create working copies, estimates or receipts.
    value = read_json(path, limit=32_000_000)
    source = read_json(base, limit=32_000_000) if path != base and base.is_file() else None
    rows, total, size = [], 0, 0
    needle = query.casefold().strip()
    for row in text_fields(value, source):
        if needle and needle not in " ".join([row["location"], row["text"], row["source"] or ""]).casefold():
            continue
        index = total
        total += 1
        if index < offset or len(rows) >= PAGE_SIZE or size >= 64_000:
            continue
        clipped = len(row["text"]) > TEXT_LIMIT or len(row["source"] or "") > TEXT_LIMIT
        row = {**row, "text": row["text"][:TEXT_LIMIT], "source": row["source"][:TEXT_LIMIT] if row["source"] is not None else None, "truncated": clipped}
        size += len(row["text"]) + len(row["source"] or "")
        rows.append(row)
    return {"file": name, "origin": origin, "revision": digest(value), "rows": rows, "offset": offset, "total": total,
            "nextOffset": offset + len(rows) if offset + len(rows) < total else None}
