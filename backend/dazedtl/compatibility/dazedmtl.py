"""Temporary boundary to the preserved DazedMTLTool Python implementation.

This is the only package allowed to import the previous repository.
It does not import its UI, prototype workspace service, or user profile.
"""

from contextlib import contextmanager
from pathlib import Path
import sys
import threading
import json
import hashlib

from dazedtl.storage import WorkspaceError, write_bytes, write_json


class ExistingBackend:
    def __init__(self, source, workspace, allow_providers=True):
        self.source = Path(source).resolve(strict=True)
        self.workspace = Path(workspace).resolve()
        for name in ("modules/rpgmakermvmz.py", "modules/wolf.py", "desktop/backend/manual.py"):
            if not (self.source / name).is_file():
                raise ValueError("Select the preserved DazedMTLTool repository for the migration adapter.")
        sys.path.insert(0, str(self.source))
        from .manual import manual_jobs
        from .model_defaults import ModelDefaults
        from desktop.backend.operations import Operations
        from desktop.backend.workflow import Workflows
        from desktop.backend.settings import SettingsStore

        self.lock = threading.RLock()
        self._legacy_settings = SettingsStore(self.workspace, code_root=self.source)
        self.manual = manual_jobs(self.source, self.workspace, self.lock, allow_providers)
        self.model_defaults = ModelDefaults(self.source, self.workspace / "model-cache", allow_providers)
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

    def settings_metadata(self):
        from desktop.backend.settings import FIELDS, validate_values
        from util.engine_options import engine_options

        return {"fields": FIELDS, "values": validate_values({}), "engines": {
            engine: {item["key"]: item["default"] for item in schema["fields"]}
            for engine, schema in engine_options(self.source).items()}}

    def validate_preferences(self, values, engines):
        from desktop.backend.settings import validate_values
        from util.engine_options import validate_engine_options

        return validate_values(values), validate_engine_options(engines, self.source)

    def import_settings(self):
        """Read and retain the previous app-local settings before making a cache."""
        files = {}
        for name in ("settings.json", "api_keys.json", "draft.json"):
            path = self._legacy_settings.root / name
            if path.exists():
                if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
                    raise WorkspaceError("workspace_invalid", "Saved settings must be regular files below 2 MB.")
                raw = path.read_bytes()
                try:
                    value = json.loads(raw)
                except (ValueError, UnicodeError) as exc:
                    raise WorkspaceError("workspace_invalid", "Saved settings could not be read. The original files were retained.") from exc
                files[name] = (raw, value)
        saved = self._legacy_settings.read()
        values, engines = self.validate_preferences(saved["values"], saved["engines"])
        raw_vault = files.get("api_keys.json", (None, {"active": "", "keys": {}}))[1]
        if not isinstance(raw_vault, dict) or not isinstance(raw_vault.get("keys"), dict):
            raise WorkspaceError("workspace_invalid", "Saved credentials could not be read. The original file was retained.")
        keys = {}
        for name, value in raw_vault["keys"].items():
            entry = {"secret": value, "endpoint": "", "keyless": False} if isinstance(value, str) else value
            if not isinstance(name, str) or not name.strip() or not isinstance(entry, dict):
                raise WorkspaceError("workspace_invalid", "A saved credential needs review in the original settings file.")
            secret, endpoint, keyless = entry.get("secret", entry.get("key", "")), entry.get("endpoint", ""), entry.get("keyless", False)
            if not isinstance(secret, str) or not isinstance(endpoint, str) or type(keyless) is not bool:
                raise WorkspaceError("workspace_invalid", "A saved credential has invalid fields. The original file was retained.")
            keys[name] = {"secret": secret, "endpoint": endpoint, "keyless": keyless}
        active = raw_vault.get("active", "")
        if not isinstance(active, str) or active and active not in keys:
            raise WorkspaceError("workspace_invalid", "The saved active credential is missing. The original file was retained.")
        draft = files.get("draft.json", (None, None))[1]
        if draft is not None and (not isinstance(draft, dict) or not isinstance(draft.get("values"), dict) or not isinstance(draft.get("engines"), dict)):
            raise WorkspaceError("workspace_invalid", "Saved preferences drafts could not be read. The original file was retained.")
        for name, (raw, _value) in files.items():
            backup = self._legacy_settings.root / "backups" / f"{Path(name).stem}.before-connections.{hashlib.sha256(raw).hexdigest()[:16]}.json"
            if backup.parent.is_symlink() or backup.is_symlink() or backup.exists() and backup.read_bytes() != raw:
                raise WorkspaceError("workspace_backup", "The previous settings could not be backed up safely.")
            if not backup.exists():
                write_bytes(backup, raw)
        return {**saved, "values": values, "engines": engines}, {"active": active, "keys": keys}, draft

    def install_settings(self, revision, values, engines, vault):
        """Materialize a derived legacy cache immediately before an engine action."""
        normalized, normalized_engines = self.validate_preferences(values, engines)
        write_json(self._legacy_settings.vault_path, vault)
        write_json(self._legacy_settings.path, {"version": 1, "revision": revision, "values": normalized, "engines": normalized_engines})

    @staticmethod
    def engine_route(model, protocol, endpoint):
        from dazedtl.settings.providers import PROVIDERS, route

        # Mirrors the preserved live runner's native-Claude routing without
        # importing its provider clients or changing the translation engine.
        native_claude = any(marker in model.lower() for marker in ("claude", "sonnet", "haiku", "opus")) and (not endpoint or "anthropic" in endpoint.lower())
        if native_claude:
            return "anthropic", PROVIDERS["anthropic"]["endpoint"]
        protocol = protocol if protocol in {"gemini", "mistral"} else "openai"
        return route(protocol, endpoint or PROVIDERS[protocol]["endpoint"])

    def validate_route(self, values):
        from dazedtl.settings.providers import route

        expected = route(values["API_PROVIDER"], values["api"])
        if self.engine_route(values["model"], values["API_PROVIDER"], values["api"]) != expected:
            raise ValueError("The model and server use a different provider route. Choose the matching provider and model in Settings.")

    def provider_defaults(self, values):
        from dazedtl.settings.providers import PROVIDERS, route
        from util.batch_providers import detect_batch_provider

        official = any(route(values["API_PROVIDER"], values["api"]) == route(item["protocol"], item["endpoint"])
                       for name, item in PROVIDERS.items() if name != "custom")
        batch = bool(values["model"] and official and detect_batch_provider(values["model"], api_url=values["api"], api_provider=values["API_PROVIDER"]))
        return {"model": values["model"], "batch_supported": batch,
                "default_mode": ("batch" if batch else "translate") if self.allow_providers else "estimate"}

    def saved_run_configuration(self, identity):
        path = self.manual.folder(identity) / "plan.json"
        if path.is_symlink() or not path.is_file():
            raise ValueError("The saved run configuration is unavailable.")
        return json.loads(path.read_text(encoding="utf-8"))

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
