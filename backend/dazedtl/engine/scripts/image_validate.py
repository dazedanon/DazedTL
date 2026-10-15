#!/usr/bin/env python3
"""Check edited game images against their originals and recipes.

The checks are DazedTL's own (dazedtl.images.recipes), the same ones the app
runs when it reads an image report; run with --help for the commands.
"""

import sys
from pathlib import Path

# Standalone helpers use the same bundled runtime as the app.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from dazedtl.images.recipes import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
