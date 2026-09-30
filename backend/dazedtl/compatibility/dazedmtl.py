"""Temporary boundary to the preserved DazedMTLTool Python implementation.

This is the only package allowed to import the previous repository.
It does not import its UI, prototype workspace service, or user profile.
"""

from contextlib import contextmanager
from pathlib import Path
import sys
import threading


class ExistingBackend:
    def __init__(self, source, workspace, allow_providers=True):
        self.source = Path(source).resolve(strict=True)
        self.workspace = Path(workspace).resolve()
        for name in ("modules/rpgmakermvmz.py", "modules/wolf.py", "desktop/backend/manual.py"):
            if not (self.source / name).is_file():
                raise ValueError("Select the preserved DazedMTLTool repository for the migration adapter.")
        sys.path.insert(0, str(self.source))
        from desktop.backend.manual import ManualJobs
        from desktop.backend.operations import Operations
        from desktop.backend.workflow import Workflows
        from desktop.backend.settings import SettingsStore

        self.lock = threading.RLock()
        self.settings = SettingsStore(self.workspace, code_root=self.source)
        self.manual = ManualJobs(self.workspace, self.lock, allow_providers=allow_providers)
        self.operations = Operations(self.workspace, self.lock)
        self.workflows = Workflows(self.workspace, self.lock, self.operations, self.manual)
        self.allow_providers = allow_providers

    @contextmanager
    def context(self):
        from util.paths import runtime_data_profile

        with self.lock, runtime_data_profile(self.workspace):
            yield

    def describe(self, source):
        from desktop.backend.workflow_actions import describe_game

        root = Path(source).expanduser().resolve(strict=True)
        if not root.is_dir() or root == root.parent:
            raise ValueError("Choose a game folder.")
        for protected in (self.source, self.workspace):
            if root.is_relative_to(protected) or protected.is_relative_to(root):
                raise ValueError("Choose a game folder separate from application and workspace storage.")
        return describe_game(root)

    def running(self):
        return self.manual.running() or self.operations.running()

    def discard_settings_draft(self, revision):
        if self.settings.read()["revision"] != revision:
            raise ValueError("Saved settings changed. Reopen Settings before reverting the draft.")
        (self.settings.root / "draft.json").unlink(missing_ok=True)
        return self.settings.describe()

    def phase_files(self, native, phase):
        from util.rpgmaker_profiles import DB_FILES, EVENT_FILES_EXACT
        import re

        if phase == "database":
            return [f["name"] for f in native["files"] if f["name"] in DB_FILES]
        if phase == "dialogue":
            return [f["name"] for f in native["files"] if f["name"] in EVENT_FILES_EXACT or re.fullmatch(r"Map\d+\.json", f["name"])]
        raise ValueError("Choose a migrated translation phase.")

    def close(self):
        self.operations.close()
        self.manual.close()
