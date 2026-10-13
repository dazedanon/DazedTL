"""RPG Maker helpers shared by manual runs: imported guidance and offline
completions."""

from __future__ import annotations

import json
import re
from pathlib import Path


def import_context(source: Path, destination: Path):
    """Copy portable guidance without invoking migration helpers on the game."""
    metadata = source / ".dazedtl"
    if metadata.is_symlink():
        raise ValueError("Project guidance cannot be imported through a symbolic link.")
    destination.mkdir(parents=True, exist_ok=True)
    candidates = [metadata / "glossary.txt", metadata / "settings.json"]
    if (metadata / "skills").is_symlink():
        raise ValueError("Project skills cannot be imported through a symbolic link.")
    candidates.extend((metadata / "skills").glob("*.md"))
    for path in candidates:
        if not path.exists():
            continue
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1_000_000:
            raise ValueError("A project guidance file is not a regular file below 1 MB.")
        target = destination / path.relative_to(metadata)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())


def offline_completion(params):
    """Valid, visibly synthetic output exercises the actual parser/validator."""
    raw = params["messages"][-1]["content"]
    decoder = json.JSONDecoder()
    values = None
    for match in re.finditer(r"\{", raw):
        try:
            candidate, _end = decoder.raw_decode(raw[match.start():])
            if isinstance(candidate, dict) and candidate and all(re.fullmatch(r"Line\d+", key) for key in candidate):
                values = candidate
                break
        except (ValueError, TypeError):
            continue
    if values is None:
        raise ValueError("The engine sent an unrecognized text payload.")
    translated = []
    for value in values.values():
        # Retain placeholders, numbers and Latin actor substitutions. The engine
        # restores runtime codes and performs line wrapping.
        speaker = re.match(r"^(\[[^\n]*?\]:\s*)(.*)", str(value), re.DOTALL)
        prefix, body = (speaker.group(1), speaker.group(2)) if speaker else ("", str(value))
        retained = re.sub(r"[\u3000-\u303f\u3040-\u30ff\u3400-\u9fff\uff61-\uff9f]", "", body)
        translated.append(prefix + "Offline test text" + (" " + retained.strip() if retained.strip() else ""))
    return {"text": json.dumps({"translations": translated}, ensure_ascii=False), "prompt_tokens": 0, "completion_tokens": 0}
