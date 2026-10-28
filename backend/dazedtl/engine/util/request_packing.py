"""How both methods pack lines into API requests: Guided's RPG Maker page
packing and its reuse stretches, and Assistant-led's organize.

Each request otherwise repeats the full system prompt. A scene of more than
SHARED_LINES lines, such as message boxes and choice options, keeps a request
of its own, so no other scene's speakers or subjects bleed into it.

A scene whose lines were partly translated earlier sends only the others, in
stretches between the translated ones. A request holding such stretches
labels each with the lines just before it and their earlier translation
(stretch_note), so the model continues the scene from them instead of
reading the stretches as one unbroken scene.
"""

SHARED_LINES = 10

# Earlier lines quoted before each stretch.
STRETCH_CONTEXT = 2


def _before(target):
    return (
        "lists the lines just before it, with their earlier "
        f"{target} after →; continue the scene from them."
    )


# Guided asks for each line's own format, since its stretches of one call are
# sent as the call's lines.
_FORMAT = (
    "Keep every line in the same format as its source line, including any "
    "name at its start."
)

# Guided's heading, for the stretches of one call, which its runs froze
# before the stretch-neighbours policy (settings/preferences).
STRETCHES = (
    "These lines are separate stretches of one scene; the lines between them "
    f"were translated earlier. Each stretch below {_before('English')} "
    f"{_FORMAT} The stretches:"
)


def call_stretches(target):
    """Guided's heading under the stretch-neighbours policy: it also labels a
    call's one stretch, and leaves a stretch at the call's start to the
    call's own history, so it counts no stretches; its target need not be
    English."""
    return (
        "These lines continue a scene whose other lines were translated "
        f"earlier. Each stretch of them below {_before(target)} "
        f"{_FORMAT} The stretches:"
    )


def scene_stretches(target):
    """Assistant-led's heading: its request may also hold other scenes, which
    its scene note names, and its target need not be English. Like that
    note, it does not ask for each line's own format
    (translation/requests.SCENES)."""
    return (
        "Some of these lines continue a scene whose other lines were "
        f"translated earlier. Each stretch of them below {_before(target)} "
        "The stretches:"
    )


def stretches(saved):
    """(start, end) of each run of lines without a reusable translation,
    where *saved* holds None for such a line."""
    spans, start = [], None
    for index, value in enumerate([*saved, ""]):
        if value is None and start is None:
            start = index
        elif value is not None and start is not None:
            spans.append((start, index))
            start = None
    return spans


def lines_label(first, last):
    """Lines *first* to *last* of a request, counted from 1."""
    return f"line {first}" if first == last else f"lines {first}-{last}"


def stretch_note(labelled, heading=STRETCHES):
    """The note on a request's stretches, from each one's label and the lines
    just before it as (source, earlier translation) pairs in request order;
    a line without a translation, such as one sent in an earlier stretch,
    quotes its source alone. Each line reads on one line."""

    def line(text):
        return " ".join(str(text).split())

    return (
        heading
        + "\n"
        + "\n".join(
            f"- {label}"
            + "".join(
                f"\n  {line(source)}"
                + (f" → {line(translation)}" if translation is not None else "")
                for source, translation in before
            )
            for label, before in labelled
        )
    )
