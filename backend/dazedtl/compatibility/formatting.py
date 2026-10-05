"""Platform-independent preparation without changing saved engine signatures."""

import json
import os
from pathlib import Path


def format_json_files(directory, log=None):
    directory = Path(directory)
    formatted, errors = 0, []
    for root, _, files in os.walk(directory):
        for name in files:
            if not name.lower().endswith(".json"):
                continue
            path = Path(root) / name
            try:
                original = path.read_bytes()
                document = json.loads(original.decode("utf-8-sig"))
                output = json.dumps(document, indent=4, ensure_ascii=False).encode(
                    "utf-8"
                )
                # Compare and write bytes: universal-newline reads hide CRLF,
                # and platform text writes can reintroduce it on Windows.
                if output != original:
                    path.write_bytes(output)
                formatted += 1
                if log:
                    log(f"  Formatted: {path.relative_to(directory)}")
            except Exception as exc:
                message = f"Error in {path}: {exc}"
                errors.append(message)
                if log:
                    log(f"  ⚠  {message}")
    return formatted, errors


def format_plugins_js(path):
    import jsbeautifier

    path = Path(path)
    original = path.read_bytes()
    text = original.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    options = jsbeautifier.default_options()
    options.indent_size = 2
    options.indent_char = " "
    options.max_preserve_newlines = 2
    options.preserve_newlines = True
    options.end_with_newline = True
    options.eol = "\n"
    formatted = jsbeautifier.beautify(text, options)
    output = formatted.encode("utf-8")
    if output != original:
        path.write_bytes(output)
    return len(formatted)


def install():
    """Route all preparation entry points through the same LF writers."""
    from util import dazedformat, project_preparation

    dazedformat.format_json_files = format_json_files
    project_preparation.format_plugins_js = format_plugins_js
