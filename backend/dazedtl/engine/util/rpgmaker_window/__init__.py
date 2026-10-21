"""Runs an RPG Maker MV/MZ game in a hidden window of DazedTL's own Electron
for a harness that plays it: Text QA's screen capture and the release
playtest.

launcher.cjs serves the game read-only to offscreen windows that keep nothing
and reach nothing outside the game's folder, replaces a window whose game
crashes or hangs, and plays again on software graphics when the GPU won't
draw. Each harness keeps its own page script and main script, which builds
its results in the output folder.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from util import system
from util.paths import PROJECT_ROOT

# The application's Electron, which the app names for its workers.
ELECTRON_ENV = "DAZEDTL_ELECTRON"
# How long Electron gets past its own deadline before it is ended.
GRACE_SECONDS = 120
# Progress at least this often, so a long screen never reads as a stalled
# action, and at most this often, so captures don't flood the log.
REPEAT_SECONDS = 20
PROGRESS_SECONDS = 10
# The offscreen window's screen on Linux, which holds any game's window.
SCREEN = "8192,8192"


class WindowUnavailable(Exception):
    """The game cannot run in a hidden window on this machine."""


@dataclass
class Played:
    """How a run went: whether the game started, on software graphics, and
    the end of Electron's own error output."""

    started: bool
    software: bool
    errors: str


def electron() -> Path:
    """The Electron that runs the game: the app's own, or the checkout's."""
    named = os.environ.get(ELECTRON_ENV, "").strip()
    if named and Path(named).is_file():
        return Path(named)
    package = PROJECT_ROOT.parents[2] / "app" / "node_modules" / "electron"
    try:
        binary = package / "dist" / (package / "path.txt").read_text(encoding="utf-8").strip()
    except OSError:
        binary = None
    if binary and binary.is_file():
        return binary
    raise WindowUnavailable("DazedTL's Electron isn't installed, so it can't run the game.")


def web_root(data_root: str | Path) -> Path:
    """The folder that holds the game's index.html, beside its data folder."""
    root = Path(data_root).resolve().parent
    if not (root / "index.html").is_file():
        raise WindowUnavailable("The game folder has no index.html to play.")
    if not any((root / "js" / name).is_file() for name in ("rmmz_core.js", "rpg_core.js")):
        raise WindowUnavailable("The game folder has no RPG Maker engine scripts to play.")
    return root


def screen_size(data_root: str | Path) -> tuple[int, int]:
    """The game's screen size: MZ keeps it in System.json; MV starts at
    816x624, and the window follows a plugin that changes it."""
    try:
        advanced = json.loads(
            (Path(data_root) / "System.json").read_text(encoding="utf-8-sig")
        ).get("advanced") or {}
        width, height = int(advanced["screenWidth"]), int(advanced["screenHeight"])
        if 160 <= width <= 4096 and 120 <= height <= 4096:
            return width, height
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return 816, 624


def run(
    harness: Path,
    web: Path,
    out: Path,
    plan: dict[str, Any],
    *,
    seconds: float,
    size: tuple[int, int],
    overlay: dict[str, str | Path] | None = None,
    starting: str = "",
    status: Callable[[dict[str, Any]], str | None] = lambda _event: None,
    log: Callable[[str], None] = lambda _text: None,
    stopped: Callable[[], bool] = lambda: False,
) -> Played:
    """Plays the game with *harness*, an Electron main script that uses
    launcher.cjs, which reads *plan* and writes its results to *out*.
    *overlay* serves files, by path under *web* such as ``data/Items.json``,
    in place of the game's own. Each line the harness writes is an event
    *status* may turn into progress for *log*, which first hears *starting*.
    Raises InterruptedError when *stopped* says so."""
    binary = electron()
    out.mkdir(parents=True, exist_ok=True)
    progress = _Progress(log, starting)
    software = False
    temporary = system.new_folder(tempfile.gettempdir(), "dazedtl-game-")
    try:
        while True:
            started, errors = _attempt(
                binary, harness, temporary, {
                    "web": str(web),
                    "out": str(out),
                    "profile": str(temporary / f"profile-{int(software)}"),
                    "seconds": seconds,
                    "width": size[0],
                    "height": size[1],
                    "overlay": {key: str(value) for key, value in (overlay or {}).items()},
                    "harness": plan,
                }, software, seconds, status, progress, stopped,
            )
            if started or software:
                return Played(started, software, errors)
            # The GPU may not draw for an offscreen window; play on the CPU.
            software = True
            progress.say("Starting the game again without the GPU")
    finally:
        _remove(temporary)


def _attempt(
    binary: Path,
    harness: Path,
    temporary: Path,
    launch: dict[str, Any],
    software: bool,
    seconds: float,
    status: Callable[[dict[str, Any]], str | None],
    progress: _Progress,
    stopped: Callable[[], bool],
) -> tuple[bool, str]:
    """One Electron run; whether the game started, and its error output."""
    plan_path = temporary / "plan.json"
    plan_path.write_text(json.dumps(launch, ensure_ascii=False), encoding="utf-8")
    command = [str(binary)]
    linux = sys.platform.startswith("linux")
    if linux:
        # Offscreen windows need no display, and a screen of their own to
        # be larger than one pixel.
        command += ["--ozone-platform=headless", f"--ozone-override-screen-size={SCREEN}"]
    # WebGL draws with the GPU, which Linux reaches through EGL without a
    # display, or with SwiftShader on the CPU.
    if software:
        command.append("--use-angle=swiftshader")
    elif linux:
        command.append("--use-angle=gl-egl")
    command += [str(harness), str(plan_path)]
    environment = {
        key: value for key, value in os.environ.items()
        if key not in {"ELECTRON_RUN_AS_NODE", "NODE_OPTIONS"}
    }
    errors_path = temporary / "electron.log"
    started = False
    with errors_path.open("wb") as errors:
        process = system.popen(
            command,
            cwd=temporary,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=errors,
            text=True,
            encoding="utf-8",
            errors="replace",
            # Its own process group, so ending it ends Electron's helpers.
            group=True,
        )
        lines: queue.Queue[str | None] = queue.Queue()

        def read() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                lines.put(line)
            lines.put(None)

        threading.Thread(target=read, daemon=True).start()
        deadline = time.monotonic() + seconds + GRACE_SECONDS
        try:
            while time.monotonic() < deadline:
                if stopped():
                    raise InterruptedError("Stopped while the game was running.")
                try:
                    line = lines.get(timeout=0.5)
                except queue.Empty:
                    line = ""
                if line is None:
                    break
                try:
                    event = json.loads(line) if line else {}
                except ValueError:
                    event = {}
                if not isinstance(event, dict):
                    event = {}
                if event.get("launcher") == "started":
                    started = True
                elif event.get("launcher") == "exit":
                    break
                elif event and (text := status(event)):
                    progress.update(text)
                progress.tick()
        finally:
            # Electron gets a moment to exit after its results, unless the
            # user stopped the run; then it is ended.
            try:
                process.wait(timeout=0 if stopped() else 30)
            except subprocess.TimeoutExpired:
                pass
            _end(process)
            process.wait()
    tail = errors_path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    return started, " ".join(tail[-3:])


class _Progress:
    """Status lines for the log: a new one at most every PROGRESS_SECONDS,
    and the last one again every REPEAT_SECONDS."""

    def __init__(self, log: Callable[[str], None], starting: str):
        self.log = log
        self.pending = starting
        self.said = ""
        self.at = 0.0
        if starting:
            self.say(starting)

    def say(self, text: str) -> None:
        self.pending = self.said = text
        self.at = time.monotonic()
        self.log(text)

    def update(self, text: str) -> None:
        self.pending = text
        if not self.said:
            self.say(text)

    def tick(self) -> None:
        if not self.pending:
            return
        waited = time.monotonic() - self.at
        if (
            self.pending != self.said and waited >= PROGRESS_SECONDS
            or waited >= REPEAT_SECONDS
        ):
            self.say(self.pending)


def _end(process: system.Process) -> None:
    """Ends Electron and the processes it started, which may outlive it."""
    system.stop_tree(process, force=True)


def _remove(folder: Path) -> None:
    """Removes the run's profile and plan, which Windows keeps locked until
    Electron's helpers have exited."""
    for _ in range(40):
        system.remove_tree(folder, ignore_errors=True)
        if not folder.exists():
            return
        time.sleep(0.25)
