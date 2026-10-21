"""Every workflow action DazedTL reviews, runs or lists in History, defined once.

A row names the action, what its review and History call it and how it is
reviewed and run; the backend's checks, the worker's dispatch and the renderer
(through the generated contracts) all read these rows, so adding an action is
one row here plus its handler.

`family` says how Guided reviews an action:

- `run` starts a translation, estimate or speaker run from the current phase.
- `lifecycle` backs up, versions, reloads or packages the game through the
  app's own operations, reviewed by the app.
- `native` is reviewed by the engine's workflow, which binds the plan to the
  game, guidance and workflow files it read.
- `apply` and `text` publish saved or reviewed text through the engine's
  export review: `apply` saved run output, `text` QA batches and restores.
- `preparation` runs the preparation stages one after another.
- `background` is started by the app itself, never through a review.
- `engine` is the engine's own and not offered by Guided.
- `retired` is no longer run; its rows name the records History still holds.

Flags:

- `read_only`: writes only its reports, never the game; the engine's review
  asks for no confirmation.
- `one_click`: routine work that starts on one click; its review keeps the
  same one-use plan and execution checks without asking the user.
- `ready`: needs the translation to be ready to take work: a source backup and
  Git baseline, and a checkout on the translation branch with no unfinished
  Git operation.
- `source_backup`: makes or chooses the source backup, so it runs before one
  exists.
- `writes_text`: writes the game's text, which on VX Ace the game-write
  gateway packs into Data, so its review refuses while an RGSS archive sits
  beside Game.exe.
- `restorable`: History restores its batch.
- `isolated`: may start while isolated translation workers run.
- `tools`: installs or configures the MV/MZ playtest tools, which need their
  hotkeys; the engine changes the game's plugins inside the game-write
  gateway.
- `reports_outcome`: its outcome shows where its work lands (Apply's notice,
  a tool row, the archive panel), so its control leaves the finished status
  out.

`history` is History's name when it differs from the review's, `step` the
name of a preparation stage, `counterpart` the action that undoes a tool
change, and `handler` the `module:function` the worker runs the plan with;
without one the engine runs it.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Literal

Family = Literal[
    "run",
    "lifecycle",
    "native",
    "apply",
    "text",
    "preparation",
    "background",
    "engine",
    "retired",
]
# The families a Guided preview takes; the others start elsewhere or not at all.
GUIDED = ("run", "lifecycle", "native", "apply", "text", "preparation")
# The families whose review is the engine workflow's, so its preview knows them.
ENGINE = ("native", "apply", "engine")

PUBLISH = "dazedtl.compatibility.text:run_publication"
PREPARE = "dazedtl.compatibility.guided:run_preparation"
ACE = "dazedtl.compatibility.guided:run_ace"
QA = "dazedtl.compatibility.text:run_qa"
PLAYTEST = "dazedtl.compatibility.playtest"


@dataclass(frozen=True)
class ActionSpec:
    name: str
    label: str
    family: Family
    history: str | None = None
    step: str | None = None
    counterpart: str | None = None
    handler: str | None = None
    read_only: bool = False
    one_click: bool = False
    ready: bool = False
    source_backup: bool = False
    writes_text: bool = False
    restorable: bool = False
    isolated: bool = False
    tools: bool = False
    reports_outcome: bool = False

    @property
    def history_label(self):
        return self.history or self.label


ROWS = (
    ActionSpec("start", "Translate", "run", ready=True),
    # Lifecycle
    ActionSpec(
        "backup_source", "Back up original game", "lifecycle", source_backup=True
    ),
    ActionSpec(
        "use_source_backup",
        "Use the game's saved original",
        "lifecycle",
        source_backup=True,
        one_click=True,
    ),
    # Setup saves the version from the form it shows, right after backing up
    # and preparing; execution rechecks the same scope.
    ActionSpec("git_setup", "Save game version", "lifecycle", one_click=True),
    ActionSpec("checkpoint", "Save translation version", "lifecycle", ready=True),
    ActionSpec(
        "guided_review",
        "Record playtest review",
        "lifecycle",
        history="Record guided playtest review",
        ready=True,
    ),
    ActionSpec(
        "guided_package",
        "Build local patch ZIP",
        "lifecycle",
        history="Package reviewed guided patch",
        ready=True,
    ),
    ActionSpec(
        "release_patch", "Build local patch ZIP", "lifecycle", reports_outcome=True
    ),
    ActionSpec(
        "refresh_sources",
        "Reload selected files from game",
        "lifecycle",
        handler="dazedtl.compatibility.guided:run_refresh",
        isolated=True,
    ),
    # Text publications
    ActionSpec(
        "export_selected",
        "Apply selected saved outputs",
        "apply",
        handler=PUBLISH,
        ready=True,
        writes_text=True,
        isolated=True,
        reports_outcome=True,
    ),
    ActionSpec(
        "runtime_restore",
        "Restore reviewed text batch",
        "text",
        handler=PUBLISH,
        ready=True,
        writes_text=True,
    ),
    # QA applies its finished findings, and undoes one, in one click; History
    # restores each batch.
    ActionSpec(
        "qa_apply",
        "Apply QA corrections",
        "text",
        handler=PUBLISH,
        one_click=True,
        ready=True,
        writes_text=True,
        restorable=True,
        reports_outcome=True,
    ),
    ActionSpec(
        "qa_undo",
        "Undo QA corrections",
        "text",
        handler=PUBLISH,
        one_click=True,
        ready=True,
        writes_text=True,
        restorable=True,
    ),
    # Preparation
    ActionSpec(
        "prepare_game",
        "Prepare game files",
        "preparation",
        handler=PREPARE,
        one_click=True,
    ),
    ActionSpec(
        "format_data",
        "Format game data",
        "native",
        step="Format game data",
        handler=PREPARE,
        one_click=True,
        reports_outcome=True,
    ),
    ActionSpec(
        "format_plugins",
        "Format plugins.js",
        "native",
        step="Format plugins.js",
        handler=PREPARE,
        one_click=True,
        reports_outcome=True,
    ),
    ActionSpec(
        "gameupdate",
        "Install GameUpdate",
        "native",
        step="Create GameUpdate files",
        handler=PREPARE,
        one_click=True,
        reports_outcome=True,
    ),
    ActionSpec("import", "Import selected files", "native"),
    # VX Ace
    ActionSpec(
        "ace_decrypt", "Decrypt Ace archive", "native", handler=ACE, one_click=True
    ),
    ActionSpec(
        "ace_extract",
        "Convert Ace data to JSON",
        "native",
        handler=ACE,
        one_click=True,
    ),
    # Packing brings Data up to ace_json, as Apply does.
    ActionSpec(
        "ace_pack",
        "Pack translated Ace data",
        "native",
        handler=ACE,
        one_click=True,
        ready=True,
        writes_text=True,
        reports_outcome=True,
    ),
    # Text QA
    ActionSpec(
        "qa_prepare",
        "Prepare or resume translation QA",
        "native",
        handler=QA,
        one_click=True,
        ready=True,
        reports_outcome=True,
    ),
    ActionSpec(
        "qa_status", "Refresh translation QA", "native", handler=QA, read_only=True
    ),
    # The release playtest and the layout and label checks write only their
    # reports, never the game.
    ActionSpec(
        "release_playtest",
        "Play the game for the release playtest",
        "native",
        handler=PLAYTEST + ":run_playtest",
        read_only=True,
    ),
    # The assistant's fixes go in once a play with them in place breaks
    # nothing new; History restores them.
    ActionSpec(
        "playtest_fix",
        "Apply playtest fixes",
        "native",
        handler=PLAYTEST + ":run_fixes",
        one_click=True,
        ready=True,
        restorable=True,
    ),
    ActionSpec(
        "layout_capture",
        "Show test text in the game's windows",
        "native",
        handler=PLAYTEST + ":run_layout",
        read_only=True,
    ),
    ActionSpec(
        "label_capture",
        "Show shortened plugin labels in the game",
        "native",
        handler=PLAYTEST + ":run_labels",
        read_only=True,
    ),
    # Playtest tools
    ActionSpec(
        "playtest_install",
        "Install both playtest plugins",
        "native",
        one_click=True,
        ready=True,
        tools=True,
    ),
    ActionSpec("playtest_status", "Refresh playtest plugins", "native", read_only=True),
    ActionSpec(
        "playtest_apply",
        "Apply playtest settings",
        "native",
        one_click=True,
        ready=True,
        tools=True,
    ),
    ActionSpec(
        "inspector_install",
        "Install TL Inspector",
        "native",
        counterpart="inspector_remove",
        one_click=True,
        ready=True,
        tools=True,
        reports_outcome=True,
    ),
    ActionSpec(
        "inspector_remove",
        "Remove TL Inspector",
        "native",
        counterpart="inspector_install",
        ready=True,
        tools=True,
        reports_outcome=True,
    ),
    ActionSpec(
        "forge_install",
        "Install Forge",
        "native",
        counterpart="forge_remove",
        one_click=True,
        ready=True,
        tools=True,
        reports_outcome=True,
    ),
    ActionSpec(
        "forge_remove",
        "Remove Forge",
        "native",
        counterpart="forge_install",
        ready=True,
        tools=True,
        reports_outcome=True,
    ),
    ActionSpec(
        "editors",
        "Find code editors",
        "native",
        read_only=True,
        reports_outcome=True,
    ),
    # Release
    ActionSpec(
        "release",
        "Build clean game ZIP",
        "native",
        handler="dazedtl.compatibility.guided:run_release",
        reports_outcome=True,
    ),
    # Context
    ActionSpec("reference_add", "Add DazedTL reference translation", "native"),
    ActionSpec("reference_pair", "Add Japanese / English reference pair", "native"),
    ActionSpec(
        "reference_remove", "Remove reference registration", "native", one_click=True
    ),
    ActionSpec(
        "reference_build", "Build exact reference matches", "native", one_click=True
    ),
    ActionSpec("images_status", "Refresh image readiness", "native", read_only=True),
    # Started by the app
    ActionSpec(
        "fit_text",
        "Fit text to the new Line widths",
        "background",
        handler="dazedtl.compatibility.text:run_fit",
        writes_text=True,
        restorable=True,
    ),
    ActionSpec(
        "full_estimate",
        "Estimate the translation cost",
        "background",
        handler="dazedtl.compatibility.full_estimate:run",
    ),
    ActionSpec(
        "speaker_scan",
        "Scan speaker names",
        "background",
        handler="dazedtl.compatibility.speaker_scan:run_scan",
    ),
    # A glossary fix batch from before Text QA took the glossary over.
    ActionSpec("glossary_apply", "Apply glossary fixes", "retired", restorable=True),
    # The engine's own
    ActionSpec("prepare", "Prepare game files", "engine"),
    ActionSpec("export_all", "Export all translated files to game", "engine"),
    ActionSpec("git_status", "Inspect Git version tracking", "engine", read_only=True),
    ActionSpec("wolf_unpack", "Unpack WOLF archives", "engine"),
    ActionSpec("wolf_extract", "Extract WOLF text and preserve originals", "engine"),
    ActionSpec("wolf_maps", "Extract missing maps", "engine"),
    ActionSpec("wolf_discover", "Discover database sheets", "engine", read_only=True),
    ActionSpec("wolf_profile", "Save database profile", "engine"),
    ActionSpec("wolf_names", "Inspect name safety", "engine", read_only=True),
    ActionSpec("wolf_precheck", "Reconcile names and check injection", "engine"),
    ActionSpec("wolf_inject", "Apply all translated WOLF files", "engine"),
    ActionSpec("wolf_inject_game", "Apply all files from wolf_json", "engine"),
    ActionSpec("wolf_restore", "Restore source layout", "engine"),
    ActionSpec("wolf_loose", "Back up archives for loose playtest", "engine"),
    ActionSpec("wolf_repack", "Repack Data.wolf", "engine"),
    ActionSpec("wolf_saves", "Update existing WOLF saves", "engine"),
    ActionSpec("wolf_search", "Find translated text", "engine", read_only=True),
    ActionSpec("wolf_wrap_preview", "Preview WOLF wrapping", "engine", read_only=True),
    ActionSpec("wolf_wrap", "Apply WOLF wrapping", "engine"),
)
ACTIONS = {row.name: row for row in ROWS}
GUIDED_ACTIONS = tuple(row.name for row in ROWS if row.family in GUIDED)
GuidedAction = Literal[*GUIDED_ACTIONS]


def spec(name):
    """The row for an action name, or ValueError for one DazedTL doesn't know."""
    try:
        return ACTIONS[name]
    except KeyError, TypeError:
        raise ValueError("Choose a supported guided action.") from None


def label(name):
    return ACTIONS[name].label


def history_label(name):
    return ACTIONS[name].history_label


def named(*, family=None, **flags):
    """The action names whose rows are in `family` (one or several) and set
    every given flag to its value."""
    families = (family,) if isinstance(family, str) else family
    return frozenset(
        row.name
        for row in ROWS
        if (families is None or row.family in families)
        and all(getattr(row, flag) == value for flag, value in flags.items())
    )


def handler(name):
    """The worker function a plan of this action runs, or None for the engine's."""
    row = ACTIONS.get(name)
    if not row or not row.handler:
        return None
    module, function = row.handler.split(":")
    return getattr(import_module(module), function)


def run(engine, plan, log):
    """Runs a plan in the worker with its action's handler, or `engine`, the
    engine's own run."""
    function = handler(plan["action"])
    if function is not None:
        return function(plan, log)
    if not ACTIONS[plan["action"]].tools:
        return engine(plan, log)
    from dazedtl.compatibility.game_write import write_game

    # The tools are plugins of an MV/MZ game, which has no Data to pack.
    with write_game(plan["project"]["source"], log=log, pack=False):
        return engine(plan, log)
