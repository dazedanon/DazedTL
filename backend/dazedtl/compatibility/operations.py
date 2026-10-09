"""Retain operation recovery while launching the app's compatibility worker."""

import importlib.util
import os
import sys
from pathlib import Path

from dazedtl.diagnostics import FOLDER


def workflow_operations(source, workspace, lock):
    name = "desktop.backend._dazedtl_operations"
    spec = importlib.util.spec_from_file_location(
        name, source / "desktop/backend/operations.py"
    )
    if spec is None or spec.loader is None:
        raise ImportError("The bundled engine module " + name + " is missing.")
    native = importlib.util.module_from_spec(spec)
    sys.modules[name] = native
    spec.loader.exec_module(native)

    def launch(native_launch, arguments, **kwargs):
        if (
            len(arguments) != 4
            or Path(arguments[2]) != source / "desktop/backend/workflow_worker.py"
        ):
            raise RuntimeError(
                "The workflow worker changed. Update its compatibility adapter."
            )
        kwargs["env"] = {**kwargs["env"], "PYTHONDONTWRITEBYTECODE": "1"}
        if FOLDER in os.environ:
            kwargs["env"][FOLDER] = os.environ[FOLDER]
        return native_launch(
            [
                *arguments[:2],
                str(Path(__file__).with_name("workflow_worker.py")),
                arguments[3],
            ],
            **kwargs,
        )

    native.launch_worker.layer("dazedtl-worker", launch)
    return native.Operations(workspace, lock)
