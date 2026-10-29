"""Bounded, cached access to the preserved engine's pricing defaults."""

import json
import os
import subprocess
import sys
import time
from copy import deepcopy
from pathlib import Path

from dazedtl import system
from dazedtl.settings.preferences import text
from dazedtl.storage import write_json


class ModelDefaults:
    def __init__(self, workspace, online):
        self.workspace = workspace
        self.online = online
        self.cache = {}
        # Each model's last lookup, kept across launches (see cached).
        self.saved = None

    def cached(self, model):
        """Known model metadata without a resolver or network read: this
        launch's lookup, else the last one saved. Snapshots compare estimates
        with these, so a restart doesn't outdate every estimate; approving or
        preparing a run looks the prices up again."""
        value = self.cache.get(model)
        if value:
            return deepcopy(value[1])
        return deepcopy(self.last().get(model, {}))

    def last(self):
        if self.saved is None:
            path = self.workspace / "defaults.json"
            try:
                value = json.loads(path.read_bytes()) if not path.is_symlink() else {}
            except OSError, ValueError:
                value = {}
            self.saved = {
                model: row
                for model, row in (value.items() if isinstance(value, dict) else ())
                if isinstance(row, dict) and row.get("model") == model
            }
        return self.saved

    def describe(self, model):
        model = text(model, "model ID", required=True)
        previous = self.cache.get(model)
        # Each lookup starts a process, seconds on Windows, before an estimate
        # can begin; catalog prices change far less often than this.
        if previous and time.monotonic() - previous[0] < 3600:
            return deepcopy(previous[1])
        if self.workspace.is_symlink():
            raise ValueError(
                "The model cache must stay inside the application workspace."
            )
        self.workspace.mkdir(parents=True, exist_ok=True)
        env = {
            key: value
            for key, value in os.environ.items()
            if key
            in {
                "PATH",
                "SYSTEMROOT",
                "WINDIR",
                "TEMP",
                "TMP",
                "TMPDIR",
                "LANG",
                "LC_ALL",
                "LD_LIBRARY_PATH",
                "DYLD_LIBRARY_PATH",
            }
        }
        # A negative fallback lets us distinguish an unknown model from a free one.
        env.update(
            PYTHON_DOTENV_DISABLED="1",
            PYTHONNOUSERSITE="1",
            PYTHONUTF8="1",
            PYTHONIOENCODING="utf-8",
            API_KEY_OPTIONAL="true",
            input_cost="-1",
            output_cost="-1",
        )
        try:
            result = system.run(
                [
                    sys.executable,
                    str(Path(__file__).with_name("pricing_worker.py")),
                    str(self.workspace / "pricing.json"),
                ],
                input=json.dumps({"model": model, "online": self.online}),
                text=True,
                encoding="utf-8",
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                cwd=self.workspace,
                env=env,
                timeout=12,
                check=True,
            )
            value = json.loads(result.stdout)
            if value["model"] != model:
                raise ValueError("Unexpected model defaults.")
        except subprocess.SubprocessError, OSError, ValueError, KeyError:
            raise ValueError(
                "This model's prices could not be looked up. Try again, or enter custom rates in Settings."
            ) from None
        self.cache[model] = (time.monotonic(), value)
        if self.last().get(model) != value:
            self.saved = {**self.last(), model: value}
            try:
                write_json(self.workspace / "defaults.json", self.saved)
            except OSError:
                pass  # Only snapshots after a restart miss it.
        return deepcopy(value)
