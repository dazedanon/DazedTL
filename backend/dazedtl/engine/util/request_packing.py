"""How short a scene must be to share an API request with other scenes, for
both methods: Guided's RPG Maker page packing and Assistant-led's organize.

Each request otherwise repeats the full system prompt. A scene of more than
SHARED_LINES lines, such as message boxes and choice options, keeps a request
of its own, so no other scene's speakers or subjects bleed into it.
"""

SHARED_LINES = 10
