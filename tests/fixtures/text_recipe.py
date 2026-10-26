"""Text recipes end to end: fit one from pixels, draw the next image with it.

A two-string card is drawn with known numbers onto a base with a gradient, a
translucent band and fully transparent pixels hiding colour. The recipe tool
must read the numbers back from the pixels alone, through the command line the
assistant uses, then draw a sibling that keeps the family's rule and leaves
every pixel it does not reach byte-identical. The Image Editor draws the same
effects, with a shadow that falls the same way whichever way the type runs and
a fractional outline as written, and offers the game's own fonts.
"""

import contextlib
import importlib.util
import io
import json
import os
import sys
from pathlib import Path

root, temporary = map(Path, sys.argv[1:])
# As the command line does: thin matrices are faster on one BLAS thread.
os.environ["OPENBLAS_NUM_THREADS"] = "1"
sys.path.insert(0, str(root / "backend/dazedtl/engine"))

import numpy as np
from PIL import Image, ImageFont, PngImagePlugin
from util.imagetools import recipe as recipes
from util.imagetools.geometry import Box
from util.imagetools.job import ImageEntry, TextBlock
from util.imagetools.render import render_entry
from util.imagetools.style import Style

spec = importlib.util.spec_from_file_location(
    "image_recipe", root / "backend/dazedtl/engine/scripts/image_recipe.py"
)
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


def run(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.main([str(arg) for arg in args])
    return code, json.loads(out.getvalue() or "{}")


# Pillow's own embedded face, so the test needs no font from the system.
font = temporary / "aileron.ttf"
font.write_bytes(ImageFont.load_default(10).font_bytes)

width, height = 260, 120
rng = np.random.default_rng(7)
base = np.zeros((height, width, 4), np.uint8)
base[..., 0] = np.linspace(30, 180, width)[None, :]
base[..., 1] = rng.integers(40, 70, (height, width))
base[..., 2] = np.linspace(160, 60, height)[:, None]
base[..., 3] = 255
base[:, 150:, 3] = 150
# Fully transparent with colour stored under it: once under the title's glow,
# once far from any text.
base[20:34, 180:200, 3] = 0
base[100:, 200:, 3] = 0
hidden = base[..., 3] == 0
base[hidden, :3] = rng.integers(0, 255, (int(hidden.sum()), 3))

title = {
    "text_color": [250, 240, 200, 255],
    "outline_color": [90, 20, 40, 255],
    "outline_width": 1.5,
    "shadow": {"color": [0, 0, 0, 170], "dx": 2, "dy": 2, "spread": 1, "blur": 1},
    "glow": {"color": [200, 120, 255, 140], "spread": 1, "blur": 3},
}
subtitle = {
    "text_color": [220, 250, 245, 255],
    "outline_color": [10, 60, 70, 255],
    "outline_width": 1,
}
digest = recipes.file_sha256(font)
truth = recipes.Recipe(
    width,
    height,
    [
        recipes.Slot(
            "title",
            "Fjall Winter",
            str(font),
            digest,
            30,
            recipes.Placement("center", "advance", 130, 50),
            Style.from_dict(title),
        ),
        recipes.Slot(
            "subtitle",
            "Chapter of the Warrior",
            str(font),
            digest,
            14,
            recipes.Placement("center", "advance", 130, 84),
            Style.from_dict(subtitle),
        ),
    ],
)
accepted, _ = recipes.render(
    truth, base, {"title": "Fjall Winter", "subtitle": "Chapter of the Warrior"}
)
info = PngImagePlugin.PngInfo()
info.add_text("Comment", "drawn by the original pass")
Image.fromarray(base, "RGBA").save(temporary / "base.png", pnginfo=info)
Image.fromarray(accepted, "RGBA").save(temporary / "accepted.png")

# --------------------------------------------------------------------- fit
code, fitted = run(
    "fit",
    "--accepted",
    temporary / "accepted.png",
    "--base",
    temporary / "base.png",
    "--font",
    font,
    "--slot",
    "title=Fjall Winter",
    "--slot",
    "subtitle=Chapter of the Warrior",
    "--recipe",
    temporary / "card.json",
)
assert code == 0, fitted
assert fitted["error"]["mean"] < 1.0, fitted["error"]
slots = {slot["name"]: slot for slot in fitted["slots"]}
for name, size, baseline in (("title", 30, 50), ("subtitle", 14, 84)):
    slot = slots[name]
    assert slot["size"] == size, slot
    # The family's rule, not just the position it was measured at.
    assert slot["placement"] == {
        "align": "center",
        "by": "advance",
        "x": 130,
        "baseline": baseline,
        "snap": True,
    }, slot["placement"]
    assert slot["correlation"] > 0.9, slot


def near(found, expected, tolerance):
    return all(abs(a - b) <= tolerance for a, b in zip(found, expected, strict=True))


style = slots["title"]["style"]
assert near(style["text_color"], title["text_color"], 4), style
assert near(style["outline_color"], title["outline_color"], 6), style
assert abs(style["outline_width"] - 1.5) <= 0.25, style
assert near([style["shadow"]["dx"], style["shadow"]["dy"]], [2, 2], 0.5), style
assert near(style["shadow"]["color"], [0, 0, 0, 170], 16), style
# A glow under an outline and a shadow trades spread for opacity almost
# freely; that it is found, in its colour, is what can be asked of it.
assert near(style["glow"]["color"][:3], [200, 120, 255], 12), style
style = slots["subtitle"]["style"]
assert near(style["text_color"], subtitle["text_color"], 6), style
assert abs(style["outline_width"] - 1) <= 0.25, style
assert "shadow" not in style and "glow" not in style, style

# ------------------------------------------------------------------- check
code, checked = run(
    "check",
    "--recipe",
    temporary / "card.json",
    "--accepted",
    temporary / "accepted.png",
    "--base",
    temporary / "base.png",
    "--diff",
    temporary / "diff.png",
)
assert code == 0 and checked["ok"], checked
assert checked["error"] == fitted["error"], (checked, fitted)
assert checked["error"]["outside"]["pixels"] == 0, checked

# ------------------------------------------------------------------ render
code, drawn = run(
    "render",
    "--recipe",
    temporary / "card.json",
    "--base",
    temporary / "base.png",
    "--slot",
    "title=The Bitter Winter",
    "--slot",
    "subtitle=Chapter of the Warrior",
    "--like",
    temporary / "base.png",
    "--output",
    temporary / "next.png",
)
assert code == 0, drawn
with Image.open(temporary / "next.png") as image:
    assert (
        image.mode == "RGBA"
        and image.info.get("Comment") == "drawn by the original pass"
    )
    candidate = np.asarray(image).copy()
placed = {item["name"]: item for item in drawn["slots"]}
face = ImageFont.truetype(str(font), 30)
assert placed["title"]["origin"] == [
    round(130 - face.getlength("The Bitter Winter") / 2),
    50 - face.getmetrics()[0],
], placed
reach = np.zeros(base.shape[:2], bool)
for item in placed.values():
    x, y, w, h = item["reach_xywh"]
    reach[max(0, y) : y + h, max(0, x) : x + w] = True
assert (candidate[~reach] == base[~reach]).all()
assert (candidate[100:, 200:] == base[100:, 200:]).all()
# Deterministic: the same recipe, base and text give the same bytes.
code, again = run(
    "render",
    "--recipe",
    temporary / "card.json",
    "--base",
    temporary / "base.png",
    "--slot",
    "title=The Bitter Winter",
    "--slot",
    "subtitle=Chapter of the Warrior",
    "--output",
    temporary / "again.png",
)
assert code == 0 and np.array_equal(
    np.asarray(Image.open(temporary / "again.png")), candidate
)
code, refused = run(
    "render",
    "--recipe",
    temporary / "card.json",
    "--base",
    temporary / "base.png",
    "--slot",
    "title=Only the title",
    "--output",
    temporary / "partial.png",
)
assert code == 2 and not (temporary / "partial.png").exists(), refused

# -------------------------------------------------------- the Image Editor
plain = np.zeros((80, 160, 4), np.uint8)
plain[..., :3] = (30, 40, 90)
plain[..., 3] = 255
shadowed = {
    "background": "keep",
    "text_color": [255, 255, 255, 255],
    "cap_height": 16,
    "font": str(font),
    "locked": True,
    "shadow": {"color": [0, 0, 0, 255], "dx": 5, "dy": 5, "blur": 0},
}
for vertical in (False, True):
    box = Box(50, 30, 110, 50) if not vertical else Box(70, 10, 90, 70)
    marks = []
    for look in (dict(shadowed, shadow=None), shadowed):
        block = TextBlock(
            "b", box, source_text="x", target_text="Ag", style=Style.from_dict(look)
        )
        block.angle = 90 if vertical else 0
        result = render_entry(plain, ImageEntry("x.png", blocks=[block]))
        ys, xs = np.nonzero((result.array != plain).any(axis=2))
        marks.append((xs.min(), ys.min(), xs.max(), ys.max()))
    (left, top, right, bottom), (sleft, stop, sright, sbottom) = marks
    # Below right of the type, whichever way it runs, and outside its block.
    assert (sleft, stop) == (left, top) and (sright, sbottom) == (
        right + 5,
        bottom + 5,
    ), marks

# A fitted 1.5px outline is drawn as one, between the whole widths either side
# of it, rather than rounded up to 2px.
ink = []
for width in (1, 1.5, 2):
    look = dict(
        shadowed, shadow=None, outline_color=[0, 0, 0, 255], outline_width=width
    )
    block = TextBlock(
        "b",
        Box(20, 20, 140, 60),
        source_text="x",
        target_text="Ag",
        style=Style.from_dict(look),
    )
    result = render_entry(plain, ImageEntry("x.png", blocks=[block]))
    ink.append(int((plain[..., :3].astype(int) - result.array[..., :3]).clip(0).sum()))
assert ink[0] < ink[1] < ink[2], ink

# A Japanese translation set in a Latin face would draw boxes: it is set in a
# face the computer has that draws it, here the tests' own subset of Noto Sans
# CJK, while English keeps the face chosen.
from util.imagetools import fonts as faces

faces.BUNDLED_FONT_DIR = root / "tests/fixtures/fonts"
faces.CJK_FACES = ()
faces._cjk_faces.cache_clear()
japanese = "テスト了解っ！　すぐ行くね〜"
face = faces.covering(str(font), japanese)
assert Path(face).name == "noto-sans-cjk-jp-subset.otf", face
assert faces.covering(str(font), "Ag") == str(font)
block = TextBlock(
    "b",
    Box(10, 10, 150, 70),
    source_text="x",
    target_text=japanese,
    style=Style.from_dict(dict(shadowed, shadow=None)),
)
result = render_entry(plain, ImageEntry("x.png", blocks=[block]))
assert not result.failures and (result.array != plain).any(), result.notes

# The game's own faces join the font list by their place in the game, so a
# moved copy keeps them; a link out of the game and an unreadable file do not.
sys.path.insert(0, str(root / "backend"))
from dazedtl.compatibility.image_editor import game_fonts

game = temporary / "game"
(game / "Fonts").mkdir(parents=True)
(game / "www/fonts").mkdir(parents=True)
(game / "Fonts/Title.ttf").write_bytes(font.read_bytes())
(game / "www/fonts/Window.ttf").write_bytes(font.read_bytes())
(game / "Fonts/Broken.otf").write_bytes(b"not a face")
(game / "Fonts/notes.txt").write_text("not a face")
try:
    os.symlink(font, game / "Fonts/Outside.ttf")
except OSError:  # Windows without the symlink privilege
    pass
listed = game_fonts(game)
assert [Path(item["path"]).name for item in listed] == ["Title.ttf", "Window.ttf"], (
    listed
)
assert {item["origin"] for item in listed} == {"game"}
# One family in two files reads alike, so each label names its file.
assert listed[0]["label"].endswith(" · Title.ttf"), listed
moved = temporary / "moved"
game.rename(moved)
assert [item["id"] for item in game_fonts(moved)] == [item["id"] for item in listed]
print("ok")
