"""Keep the legacy job controller, with a local worker-launch boundary."""

from copy import deepcopy
from contextlib import contextmanager
import importlib.util
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace


def manual_jobs(source, workspace, lock, allow_providers):
    # Load an isolated module namespace so substituting its launcher never changes
    # the shared subprocess module or the preserved application's controller.
    name = "desktop.backend._dazedtl_manual"
    spec = importlib.util.spec_from_file_location(
        name, source / "desktop/backend/manual.py"
    )
    native = importlib.util.module_from_spec(spec)
    sys.modules[name] = native
    spec.loader.exec_module(native)
    expected = source / "desktop/backend/manual_worker.py"

    def launch(arguments, **kwargs):
        if len(arguments) != 4 or Path(arguments[2]) != expected:
            raise RuntimeError(
                "The preserved worker entrypoint changed. Update the compatibility adapter."
            )
        arguments = [
            *arguments[:2],
            str(Path(__file__).with_name("manual_worker.py")),
            arguments[3],
        ]
        kwargs["env"] = {
            **kwargs["env"],
            "DAZEDTL_ENGINE_SOURCE": str(source),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        return subprocess.Popen(arguments, **kwargs)

    native.subprocess = SimpleNamespace(Popen=launch, PIPE=subprocess.PIPE,
                                        DEVNULL=subprocess.DEVNULL, run=subprocess.run)

    class ManualJobs(native.ManualJobs):
        request_policy = None
        workflow_selection = None

        @contextmanager
        def selected_workflow(self, identity, files):
            previous = self.workflow_selection
            self.workflow_selection = (identity, tuple(files))
            try:
                yield
            finally:
                self.workflow_selection = previous

        def start(self, source, engine, files, *args, **kwargs):
            if self.workflow_selection is not None:
                identity, selected = self.workflow_selection
                if (kwargs.get("workflow") or {}).get("id") != identity or set(selected) - set(files):
                    raise ValueError("The selected files no longer match this project's phase.")
                files = list(selected)
            return super().start(source, engine, files, *args, **kwargs)

        def _snapshot_context(self, directory, plan, workspace=None):
            super()._snapshot_context(directory, plan, workspace)
            if self.request_policy is not None:
                if self.request_policy["model"] != plan["settings"]["model"]:
                    raise ValueError(
                        "The selected model changed before creating the run."
                    )
                # Included before the native plan hash is computed and launch starts.
                plan["dazedtl_request_policy"] = deepcopy(self.request_policy)

    return ManualJobs(workspace, lock, allow_providers=allow_providers)
