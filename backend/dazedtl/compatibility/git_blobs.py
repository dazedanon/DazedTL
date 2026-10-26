"""A game's original files, read from the blobs its Git repository keeps.

The backend and the [derived readers](../translation/derived_worker.py) read
them alike; this module imports nothing else of the app, so a reader process
starts quickly.
"""

import re
import subprocess
import tempfile

from dazedtl import system

_BLOB = re.compile(r"[0-9a-f]{40,64}")


def git(arguments, purpose, timeout=120):
    """Runs Git for its raw output; a failure says what it was for in words."""
    try:
        result = system.run(
            ["git", *arguments], capture_output=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"Git could not {purpose} within {timeout} seconds.") from exc
    except OSError as exc:
        raise ValueError(f"Git could not {purpose}: {exc.strerror or exc}") from exc
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(
            f"Git could not {purpose}: {detail or f'exit status {result.returncode}'}"
        )
    return result.stdout


def original_bytes(source, blob):
    """One original file's bytes, by its blob in the game at `source`."""
    if not isinstance(blob, str) or not _BLOB.fullmatch(blob):
        raise ValueError("Choose a verified original source blob.")
    return git(
        ["-C", str(source), "cat-file", "blob", blob],
        "read the game's original files",
        timeout=30,
    )


def original_blobs(source, blobs):
    """Yields each blob with its bytes, read through one Git process, which
    Windows starts far faster than one process per file."""
    blobs = list(dict.fromkeys(blobs))
    if any(not isinstance(blob, str) or not _BLOB.fullmatch(blob) for blob in blobs):
        raise ValueError("Choose a verified original source blob.")
    if not blobs:
        return
    purpose = "Git could not read the game's original files"
    with tempfile.TemporaryFile() as requests:
        requests.write("".join(blob + "\n" for blob in blobs).encode("ascii"))
        requests.seek(0)
        try:
            process = system.popen(
                ["git", "-C", str(source), "cat-file", "--batch"],
                stdin=requests,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            raise ValueError(f"{purpose}: {exc.strerror or exc}") from exc
        with process:
            assert process.stdout is not None and process.stderr is not None
            for blob in blobs:
                header = process.stdout.readline().split()
                if not header:
                    # Git stopped, so its error is complete.
                    detail = process.stderr.read().decode("utf-8", "replace")
                    raise ValueError(f"{purpose}: {detail.strip() or 'no output'}")
                if len(header) != 3 or header[:2] != [blob.encode(), b"blob"]:
                    process.kill()
                    raise ValueError(f"{purpose}: {blob} is not a saved file.")
                raw = process.stdout.read(int(header[2]))
                if len(raw) != int(header[2]) or process.stdout.read(1) != b"\n":
                    process.kill()
                    raise ValueError(f"{purpose}: {blob} ended early.")
                yield blob, raw
