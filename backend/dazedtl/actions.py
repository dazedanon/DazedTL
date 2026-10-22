"""Every workflow action DazedTL reviews, runs or lists in History, defined once.

A row names the action, what its review and History call it and how it is
reviewed and run; the backend's checks, the worker's dispatch and the renderer
(through the generated contracts) all read these rows, so adding an action is
one row here plus its handler.

`family` says how Guided reviews an action:

- `run` starts a translation, estimate or speaker run from the current phase.
- `lifecycle` versions, reloads or packages the game through the
  app's own operations, reviewed by the app.
- `native` is reviewed by the engine's workflow, which binds the plan to the
  game, guidance and workflow files it read.
- `apply` and `text` publish saved or reviewed text through the engine's
  export review: `apply` saved run output, `text` QA batches and restores.
- `preparation` runs the preparation stages one after another.
- `background` is started by the app itself, never through a review.
- `helper` is run by an assistant's project helper, never offered by Guided.
- `engine` is the engine's own and not offered by Guided.
- `retired` is no longer run; its rows name the records History still holds.

Flags:

- `read_only`: writes only its reports, never the game; the engine's review
  asks for no confirmation.
- `one_click`: routine work that starts on one click; its review keeps the
  same one-use plan and execution checks without asking the user.
- `ready`: needs the translation to be ready to take work: a Git baseline,
  and a checkout on the translation branch with no unfinished Git operation.
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

`stage` is the workflow stage whose checkpoints the action's writes to the
game make ([checkpoint_commits](compatibility/checkpoint_commits.py)).
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
    "helper",
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


# What a stop the user asked for leaves, said once per kind of run: what was
# kept and whether running it again continues or starts over. An action
# without a row of its own claims nothing.
STOPPED = "It ended early at your request."
SETUP_STOPPED = (
    "Steps that finished are kept. Setting up again continues with the step "
    "that was stopped."
)
STEP_STOPPED = "The step did not finish. Setting up again runs it again from its start."
TOOL_STOPPED = "It did not finish. Running it again starts it over."
FIT_STOPPED = (
    "Text already fitted stays as it is. Saving the line widths fits the text again."
)
ESTIMATE_STOPPED = "No new estimate was saved. Estimating again starts over."
RELEASE_STOPPED = (
    "No new ZIP was saved, and any earlier ZIP is unchanged. Building again "
    "starts over."
)


@dataclass(frozen=True)
class ActionSpec:
    name: str
    label: str
    family: Family
    stage: str
    history: str | None = None
    step: str | None = None
    counterpart: str | None = None
    handler: str | None = None
    read_only: bool = False
    one_click: bool = False
    ready: bool = False
    writes_text: bool = False
    restorable: bool = False
    isolated: bool = False
    tools: bool = False
    reports_outcome: bool = False
    stopped: str = STOPPED

    @property
    def history_label(self):
        return self.history or self.label


ROWS = (
    ActionSpec("start", "Translate", "run", stage="Translate", ready=True),
    # Lifecycle
    # Setup saves the version from the form it shows, right after preparing;
    # execution rechecks the same scope.
    ActionSpec(
        "git_setup",
        "Record game version",
        "lifecycle",
        stage="Set up",
        one_click=True,
        stopped=STEP_STOPPED,
    ),
    # Every write is its own checkpoint; an assistant's own edits are saved
    # by the helper's checkpoint.
    ActionSpec(
        "checkpoint", "Save a checkpoint", "helper", stage="Assistant-led", ready=True
    ),
    ActionSpec(
        "release_patch",
        "Build local patch ZIP",
        "lifecycle",
        stage="Release",
        reports_outcome=True,
        stopped=RELEASE_STOPPED,
    ),
    ActionSpec(
        "refresh_sources",
        "Reload selected files from game",
        "lifecycle",
        stage="Translate",
        handler="dazedtl.compatibility.guided:run_refresh",
        isolated=True,
    ),
    # Text publications
    ActionSpec(
        "export_selected",
        "Apply selected saved outputs",
        "apply",
        stage="Translate",
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
        stage="Translate",
        handler=PUBLISH,
        ready=True,
        writes_text=True,
    ),
    ActionSpec(
        "runtime_undo",
        "Undo text batch",
        "text",
        stage="Translate",
        handler="dazedtl.compatibility.text:run_undo",
        one_click=True,
        ready=True,
        writes_text=True,
    ),
    # QA applies its finished findings, and undoes one, in one click; History
    # restores each batch.
    ActionSpec(
        "qa_apply",
        "Apply QA corrections",
        "text",
        stage="Check",
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
        stage="Check",
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
        stage="Set up",
        handler=PREPARE,
        one_click=True,
        stopped=SETUP_STOPPED,
    ),
    ActionSpec(
        "format_data",
        "Format game data",
        "native",
        stage="Set up",
        step="Format game data",
        handler=PREPARE,
        one_click=True,
        reports_outcome=True,
        stopped=TOOL_STOPPED,
    ),
    ActionSpec(
        "format_plugins",
        "Format plugins.js",
        "native",
        stage="Set up",
        step="Format plugins.js",
        handler=PREPARE,
        one_click=True,
        reports_outcome=True,
        stopped=TOOL_STOPPED,
    ),
    ActionSpec(
        "gameupdate",
        "Install GameUpdate",
        "native",
        stage="Set up",
        step="Create GameUpdate files",
        handler=PREPARE,
        one_click=True,
        reports_outcome=True,
        stopped=TOOL_STOPPED,
    ),
    ActionSpec("import", "Import selected files", "native", stage="Set up"),
    # VX Ace
    ActionSpec(
        "ace_decrypt",
        "Decrypt Ace archive",
        "native",
        stage="Set up",
        handler=ACE,
        one_click=True,
    ),
    ActionSpec(
        "ace_extract",
        "Convert Ace data to JSON",
        "native",
        stage="Set up",
        handler=ACE,
        one_click=True,
        stopped=STEP_STOPPED,
    ),
    # Packing brings Data up to ace_json, as Apply does.
    ActionSpec(
        "ace_pack",
        "Pack translated Ace data",
        "native",
        stage="Release",
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
        stage="Check",
        handler=QA,
        one_click=True,
        ready=True,
        reports_outcome=True,
    ),
    ActionSpec(
        "qa_status",
        "Refresh translation QA",
        "native",
        stage="Check",
        handler=QA,
        read_only=True,
    ),
    # The release playtest and the layout and label checks write only their
    # reports, never the game.
    ActionSpec(
        "release_playtest",
        "Play the game for the release playtest",
        "native",
        stage="Check",
        handler=PLAYTEST + ":run_playtest",
        read_only=True,
    ),
    # The assistant's fixes go in once a play with them in place breaks
    # nothing new; History restores them.
    ActionSpec(
        "playtest_fix",
        "Apply playtest fixes",
        "native",
        stage="Check",
        handler=PLAYTEST + ":run_fixes",
        one_click=True,
        ready=True,
        restorable=True,
    ),
    ActionSpec(
        "layout_capture",
        "Show test text in the game's windows",
        "native",
        stage="Check",
        handler=PLAYTEST + ":run_layout",
        read_only=True,
    ),
    ActionSpec(
        "label_capture",
        "Show shortened plugin labels in the game",
        "native",
        stage="Check",
        handler=PLAYTEST + ":run_labels",
        read_only=True,
    ),
    # Playtest tools
    ActionSpec(
        "playtest_install",
        "Install both playtest plugins",
        "native",
        stage="Check",
        one_click=True,
        ready=True,
        tools=True,
    ),
    ActionSpec(
        "playtest_status",
        "Refresh playtest plugins",
        "native",
        stage="Check",
        read_only=True,
    ),
    ActionSpec(
        "playtest_apply",
        "Apply playtest settings",
        "native",
        stage="Check",
        one_click=True,
        ready=True,
        tools=True,
    ),
    ActionSpec(
        "inspector_install",
        "Install TL Inspector",
        "native",
        stage="Check",
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
        stage="Check",
        counterpart="inspector_install",
        ready=True,
        tools=True,
        reports_outcome=True,
    ),
    ActionSpec(
        "forge_install",
        "Install Forge",
        "native",
        stage="Check",
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
        stage="Check",
        counterpart="forge_install",
        ready=True,
        tools=True,
        reports_outcome=True,
    ),
    ActionSpec(
        "editors",
        "Find code editors",
        "native",
        stage="Check",
        read_only=True,
        reports_outcome=True,
    ),
    # Release
    ActionSpec(
        "release",
        "Build clean game ZIP",
        "native",
        stage="Release",
        handler="dazedtl.compatibility.guided:run_release",
        reports_outcome=True,
        stopped=RELEASE_STOPPED,
    ),
    # Context
    ActionSpec(
        "reference_add", "Add DazedTL reference translation", "native", stage="Context"
    ),
    ActionSpec(
        "reference_pair",
        "Add Japanese / English reference pair",
        "native",
        stage="Context",
    ),
    ActionSpec(
        "reference_remove",
        "Remove reference registration",
        "native",
        stage="Context",
        one_click=True,
    ),
    ActionSpec(
        "reference_build",
        "Build exact reference matches",
        "native",
        stage="Context",
        one_click=True,
    ),
    ActionSpec(
        "images_status",
        "Refresh image readiness",
        "native",
        stage="Translate",
        read_only=True,
    ),
    # Started by the app
    ActionSpec(
        "fit_text",
        "Fit text to the new Line widths",
        "background",
        stage="Context",
        handler="dazedtl.compatibility.text:run_fit",
        writes_text=True,
        restorable=True,
        stopped=FIT_STOPPED,
    ),
    ActionSpec(
        "full_estimate",
        "Estimate the translation cost",
        "background",
        stage="Context",
        handler="dazedtl.compatibility.full_estimate:run",
        stopped=ESTIMATE_STOPPED,
    ),
    ActionSpec(
        "speaker_scan",
        "Scan speaker names",
        "background",
        stage="Context",
        handler="dazedtl.compatibility.speaker_scan:run_scan",
    ),
    # Backups Set up took before the game's original files were kept in Git.
    ActionSpec("backup_source", "Back up original game", "retired", stage="Set up"),
    ActionSpec(
        "use_source_backup", "Use the game's saved original", "retired", stage="Set up"
    ),
    # A glossary fix batch from before Text QA took the glossary over.
    ActionSpec(
        "glossary_apply",
        "Apply glossary fixes",
        "retired",
        stage="Context",
        restorable=True,
    ),
    # The engine's own
    ActionSpec("prepare", "Prepare game files", "engine", stage="Set up"),
    ActionSpec(
        "export_all", "Export all translated files to game", "engine", stage="Translate"
    ),
    ActionSpec(
        "git_status",
        "Inspect Git version tracking",
        "engine",
        stage="Set up",
        read_only=True,
    ),
    ActionSpec("wolf_unpack", "Unpack WOLF archives", "engine", stage="Set up"),
    ActionSpec(
        "wolf_extract",
        "Extract WOLF text and preserve originals",
        "engine",
        stage="Set up",
    ),
    ActionSpec("wolf_maps", "Extract missing maps", "engine", stage="Set up"),
    ActionSpec(
        "wolf_discover",
        "Discover database sheets",
        "engine",
        stage="Set up",
        read_only=True,
    ),
    ActionSpec("wolf_profile", "Save database profile", "engine", stage="Set up"),
    ActionSpec(
        "wolf_names", "Inspect name safety", "engine", stage="Translate", read_only=True
    ),
    ActionSpec(
        "wolf_precheck",
        "Reconcile names and check injection",
        "engine",
        stage="Translate",
    ),
    ActionSpec(
        "wolf_inject", "Apply all translated WOLF files", "engine", stage="Translate"
    ),
    ActionSpec(
        "wolf_inject_game",
        "Apply all files from wolf_json",
        "engine",
        stage="Translate",
    ),
    ActionSpec("wolf_restore", "Restore source layout", "engine", stage="Translate"),
    ActionSpec(
        "wolf_loose", "Back up archives for loose playtest", "engine", stage="Translate"
    ),
    ActionSpec("wolf_repack", "Repack Data.wolf", "engine", stage="Translate"),
    ActionSpec("wolf_saves", "Update existing WOLF saves", "engine", stage="Translate"),
    ActionSpec(
        "wolf_search",
        "Find translated text",
        "engine",
        stage="Translate",
        read_only=True,
    ),
    ActionSpec(
        "wolf_wrap_preview",
        "Preview WOLF wrapping",
        "engine",
        stage="Translate",
        read_only=True,
    ),
    ActionSpec("wolf_wrap", "Apply WOLF wrapping", "engine", stage="Translate"),
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


def stopped_note(name):
    """What a stop the user asked for leaves of this action's run."""
    row = ACTIONS.get(name)
    return row.stopped if row else STOPPED


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
    from dazedtl.compatibility.checkpoint_commits import for_action, running

    with running(for_action(plan["action"], plan.get("label"))):
        function = handler(plan["action"])
        if function is not None:
            return function(plan, log)
        row = ACTIONS.get(plan["action"])
        source = (plan.get("project") or {}).get("source")
        if not row or row.read_only or not source:
            return engine(plan, log)
        from dazedtl.compatibility.game_write import write_game

        # The engine's own writes, such as the playtest tools, which are
        # plugins of an MV/MZ game, and WOLF's files, have no Data to pack.
        with write_game(source, log=log, pack=False):
            return engine(plan, log)
