"""The translation hand-off file's contents.

The workflow splits at a file so the part that needs language ability runs
inside DazedTL, with the same provider, prompt and glossary as every other kind
of file the project translates:

  1. Lens reads the images; the user confirms boxes and text in the editor
  2. the Images editor writes ``build``'s payload as ``image_text.json`` into
     the run that translates it (``compatibility/image_editor.exchange``)
  3. the Images editor reads the translations back from that run's own output
     (``images/editor.py``)

Only images the user marked ``confirmed`` are exported. Nothing reaches the
translator that a human has not looked at - that gate is the point of the
whole semi-manual design.

The format is flat and boring - one object per block, source and target side by
side - so it can be edited by hand, diffed, or fed to another translator
entirely without this toolkit being involved.
"""

from __future__ import annotations

from util.imagetools.fonts import text_budget
from util.imagetools.job import Job

FORMAT_VERSION = 3


def build(job: Job) -> dict:
    """Everything a translator needs, and nothing it does not."""
    images = []
    for entry in job.confirmed():
        blocks = []
        for block in entry.translatable():
            orientation = "vertical" if block.vertical else "horizontal"
            blocks.append(
                {
                    "id": block.block_id,
                    "source": block.source_text,
                    "target": block.target_text,
                    # Context the translator cannot see but the layout demands.
                    "max_chars": text_budget(
                        width=block.box.w,
                        height=block.box.h,
                        cap_height=_cap_height(block),
                        orientation=orientation,
                        target=job.language,
                    ),
                    "lines": block.line_count,
                    "box": block.box.as_xywh(),
                    "orientation": orientation,
                }
            )
        if blocks:
            images.append(
                {"image": entry.relpath, "index": entry.index, "regions": blocks}
            )

    return {
        "format": "dazedtl-image-text",
        "version": FORMAT_VERSION,
        "language": job.language,
        "root": str(job.root),
        "note": (
            "Fill in every 'target'. Keep it at or under 'max_chars' characters "
            "or it will not fit the image. Leave 'source' unchanged."
        ),
        "images": images,
    }


def _cap_height(block) -> int:
    """Type size, from the measured line boxes rather than the block's."""
    if block.lines:
        sizes = sorted(
            (line.box.w if block.vertical else line.box.h) for line in block.lines
        )
        return max(7, sizes[len(sizes) // 2])
    span = block.box.w if block.vertical else block.box.h
    return max(7, span // max(1, block.line_count))
