"""Atomic preferences and profiles; saved secrets are never returned to the UI."""

from copy import deepcopy
import json
from pathlib import Path
import uuid

from dazedtl.storage import WorkspaceError, read_versioned_json, write_json
from . import providers


class Settings:
    def __init__(self, workspace, adapter):
        self.adapter = adapter
        self.path = Path(workspace) / "settings" / "settings.json"
        self.metadata = adapter.settings_metadata()
        self.empty = {
            "version": 1,
            "revision": 0,
            "values": self.metadata["values"],
            "engines": {},
            "active": "",
            "connections": [],
            "draft": None,
        }
        if not self.path.exists():
            self._import()
        self._read()

    def _validate(self, value):
        invalid = WorkspaceError(
            "workspace_invalid",
            "Saved settings are invalid. The original file was left unchanged.",
        )
        if (
            type(value.get("revision")) is not int
            or value["revision"] < 0
            or not isinstance(value.get("values"), dict)
            or not isinstance(value.get("engines"), dict)
        ):
            raise invalid
        known = {field["key"] for field in self.metadata["fields"]}
        if set(value["values"]) - known:
            raise invalid
        connections = value.get("connections")
        if not isinstance(connections, list) or len(connections) > 1000:
            raise invalid
        identities, runtime_names = set(), set()
        for connection in connections:
            if not isinstance(connection, dict) or any(
                not isinstance(connection.get(key), str)
                for key in (
                    "id",
                    "name",
                    "runtime_name",
                    "endpoint",
                    "secret",
                    "model",
                    "organization",
                )
            ):
                raise invalid
            if (
                not connection["id"]
                or connection["id"] in identities
                or not connection["runtime_name"]
                or connection["runtime_name"] in runtime_names
            ):
                raise invalid
            if (
                not (
                    connection.get("provider") is None
                    or isinstance(connection.get("provider"), str)
                    and connection["provider"] in providers.PROVIDERS
                )
                or not isinstance(connection.get("protocol"), str)
                or connection["protocol"] not in providers.PROTOCOLS
                or type(connection.get("keyless")) is not bool
            ):
                raise invalid
            if not isinstance(connection.get("check"), dict) or not isinstance(
                connection.get("models"), list
            ):
                raise invalid
            verification = connection["check"]
            if not isinstance(verification.get("status"), str) or verification[
                "status"
            ] not in {
                "not_checked",
                "verified",
                "reachable",
                "failed",
                "unavailable",
                "unsupported",
            }:
                raise invalid
            if not isinstance(verification.get("message"), str) or not (
                verification.get("checkedAt") is None
                or isinstance(verification.get("checkedAt"), str)
            ):
                raise invalid
            if any(not isinstance(model, str) for model in connection["models"]):
                raise invalid
            identities.add(connection["id"])
            runtime_names.add(connection["runtime_name"])
        if (
            not isinstance(value.get("active"), str)
            or value["active"]
            and value["active"] not in identities
        ):
            raise invalid
        draft = value.get("draft")
        if draft is not None and (
            not isinstance(draft, dict)
            or any(
                not isinstance(draft.get(key), dict)
                for key in ("values", "engines", "models")
            )
        ):
            raise invalid
        if draft is not None and set(draft["values"]) - known:
            raise invalid

    def _read(self):
        if (
            self.path.is_symlink()
            or self.path.exists()
            and self.path.stat().st_size > 8_000_000
        ):
            raise WorkspaceError(
                "workspace_invalid", "Choose a regular settings file below 8 MB."
            )
        return read_versioned_json(self.path, self.empty, {}, self._validate)

    def _write(self, value, bump=True):
        self._validate(value)
        if bump:
            value["revision"] += 1
        if len(json.dumps(value).encode()) > 8_000_000:
            raise ValueError("Saved settings are too large.")
        write_json(self.path, value)

    @staticmethod
    def _connection(value, identity=None):
        selected = value["active"] if identity is None else identity
        return next(
            (item for item in value["connections"] if item["id"] == selected), None
        )

    @staticmethod
    def _revision(value, revision):
        if type(revision) is not int or value["revision"] != revision:
            raise ValueError(
                "Settings changed elsewhere. Reopen Settings before saving."
            )

    @staticmethod
    def _configured(connection):
        return bool(
            connection
            and connection["provider"]
            and (connection["secret"] or connection["keyless"])
        )

    def _import(self):
        saved, vault, draft = self.adapter.import_settings()
        state = deepcopy(self.empty)
        state.update(
            revision=saved["revision"], values=saved["values"], engines=saved["engines"]
        )
        for name, entry in vault["keys"].items():
            active = name == vault["active"]
            endpoint = entry["endpoint"] or (saved["values"]["api"] if active else "")
            protocol = saved["values"]["API_PROVIDER"] if active else "openai"
            if active:
                protocol, effective = self.adapter.engine_route(
                    saved["values"]["model"], protocol, endpoint
                )
                provider = providers.infer_provider(protocol, effective)
            else:
                effective = endpoint
                provider = None
                for identity, definition in providers.PROVIDERS.items():
                    if identity != "custom" and providers.route(
                        definition["protocol"], endpoint
                    ) == providers.route(
                        definition["protocol"], definition["endpoint"]
                    ):
                        protocol = definition["protocol"]
                        provider = identity
                        break
            try:
                providers.endpoint(endpoint)
            except ValueError:
                provider = None
            if protocol == "anthropic" and provider == "custom":
                provider = None
            if entry["keyless"] and provider and endpoint:
                provider = "custom"
            if provider and provider != "custom":
                endpoint = ""
            connection = {
                "id": uuid.uuid4().hex,
                "runtime_name": name,
                "name": name,
                "provider": provider,
                "protocol": protocol,
                "endpoint": endpoint,
                "secret": entry["secret"],
                "keyless": entry["keyless"],
                "organization": saved["values"].get("organization", "")
                if active
                else "",
                "model": saved["values"]["model"] if active else "",
                "check": providers.unchecked(),
                "models": [],
            }
            state["connections"].append(connection)
            if active:
                state["active"] = connection["id"]
        if draft:
            values = deepcopy(draft["values"])
            model = values.pop("model", state["values"]["model"])
            for key in ("api", "API_PROVIDER", "organization"):
                values.pop(key, None)
            state["draft"] = {
                "values": values,
                "engines": draft["engines"],
                "models": {state["active"]: model},
            }
        self._write(state, bump=False)

    def _values(self, state):
        values = {**self.metadata["values"], **state["values"]}
        connection = self._connection(state)
        if connection:
            values.update(
                model=connection["model"],
                API_PROVIDER=connection["protocol"],
                api=providers.address(connection),
                organization=connection["organization"],
            )
        return values

    def describe(self):
        state = self._read()
        values = self._values(state)
        for key in ("api", "API_PROVIDER", "organization"):
            values.pop(key, None)
        engines = deepcopy(self.metadata["engines"])
        for name, overrides in state["engines"].items():
            engines.setdefault(name, {}).update(overrides)
        connections = []
        for item in state["connections"]:
            # Incomplete imported entries stay recoverable, but unsafe old URL
            # query strings are never reflected into the renderer.
            try:
                endpoint = providers.endpoint(item["endpoint"])
            except ValueError:
                endpoint = ""
            connections.append(
                {
                    key: item[key]
                    for key in (
                        "id",
                        "name",
                        "provider",
                        "protocol",
                        "keyless",
                        "model",
                        "organization",
                        "check",
                        "models",
                    )
                }
                | {
                    "endpoint": endpoint,
                    "check": {
                        key: item["check"][key]
                        for key in ("status", "message", "checkedAt")
                    },
                    "has_secret": bool(item["secret"]),
                    "needsSetup": not self._configured(item),
                }
            )
        result = {
            "revision": state["revision"],
            "values": values,
            "engines": engines,
            "fields": self.metadata["fields"],
            "activeConnectionId": state["active"],
            "connections": connections,
            "providers": [
                {
                    "id": name,
                    "label": definition["label"],
                    "defaultEndpoint": definition["endpoint"],
                }
                for name, definition in providers.PROVIDERS.items()
            ],
            "checksEnabled": self.adapter.allow_providers,
        }
        if state["draft"]:
            draft = state["draft"]
            draft_engines = deepcopy(engines)
            for name, overrides in draft["engines"].items():
                draft_engines.setdefault(name, {}).update(overrides)
            result["draft"] = {
                "revision": state["revision"],
                "values": {
                    **values,
                    **draft["values"],
                    "model": draft["models"].get(state["active"], values["model"]),
                },
                "engines": draft_engines,
            }
        return result

    def ready(self):
        connection = self._connection(self._read())
        return self._configured(connection) and bool(connection["model"].strip())

    def translation_defaults(self):
        state = self._read()
        values = self._values(state)
        active = self._connection(state)
        if active and not self._configured(active):
            values["model"] = ""
        return self.adapter.provider_defaults(values)

    def save(self, revision, connection_id, values, engines):
        state = self._read()
        self._revision(state, revision)
        if connection_id != state["active"]:
            raise ValueError(
                "The active connection changed. Review its preferences before saving."
            )
        connection = self._connection(state)
        if not isinstance(values, dict) or not isinstance(values.get("model"), str):
            raise ValueError("Enter a model ID.")
        model = values["model"].strip()
        candidate = (
            {**values, "model": model or state["values"]["model"]}
            if connection
            else values
        )
        normalized, normalized_engines = self.adapter.validate_preferences(
            candidate, engines
        )
        if connection:
            connection["model"] = model
            normalized["model"] = state["values"]["model"]
        for key in ("api", "API_PROVIDER", "organization"):
            normalized[key] = state["values"][key]
        state.update(values=normalized, engines=normalized_engines)
        if state["draft"]:
            models = state["draft"]["models"]
            models.pop(connection_id, None)
            state["draft"] = (
                {"values": {}, "engines": normalized_engines, "models": models}
                if models
                else None
            )
        self._write(state)
        return self.describe()

    def draft(self, revision, connection_id, values, engines):
        state = self._read()
        self._revision(state, revision)
        if (
            not isinstance(values, dict)
            or not isinstance(engines, dict)
            or connection_id != state["active"]
        ):
            raise ValueError(
                "The active connection changed. Reopen Settings before editing its preferences."
            )
        if (
            set(values) - {field["key"] for field in self.metadata["fields"]}
            or len(json.dumps([values, engines])) > 100000
        ):
            raise ValueError("Invalid preferences draft.")
        schemas = self.metadata["engines"]
        if set(engines) - schemas.keys() or any(
            not isinstance(value, dict) or set(value) - schemas[name].keys()
            for name, value in engines.items()
        ):
            raise ValueError("Unknown engine draft field.")
        if not isinstance(values.get("model", ""), str):
            raise ValueError("Enter a model ID.")
        models = (state["draft"] or {}).get("models", {})
        values = dict(values)
        models[connection_id] = values.pop("model", self._values(state)["model"])
        for key in ("api", "API_PROVIDER", "organization"):
            values.pop(key, None)
        state["draft"] = {"values": values, "engines": engines, "models": models}
        self._write(state, bump=False)
        return {"saved": True}

    def revert(self, revision, connection_id):
        state = self._read()
        self._revision(state, revision)
        if connection_id != state["active"]:
            raise ValueError(
                "The active connection changed. Reopen Settings before reverting."
            )
        models = (state["draft"] or {}).get("models", {})
        models.pop(connection_id, None)
        state["draft"] = (
            {"values": {}, "engines": state["engines"], "models": models}
            if models
            else None
        )
        self._write(state, bump=False)
        return self.describe()

    def select(self, revision, connection_id):
        state = self._read()
        self._revision(state, revision)
        if not self._connection(state, connection_id):
            raise ValueError("Choose a saved connection.")
        state["active"] = connection_id
        self._write(state)
        return self.describe()

    def save_connection(
        self,
        revision,
        provider,
        connection_id="",
        name="",
        secret="",
        endpoint="",
        keyless=False,
        protocol="openai",
        organization="",
        reuse_secret=False,
    ):
        state = self._read()
        self._revision(state, revision)
        if (
            not isinstance(provider, str)
            or provider not in providers.PROVIDERS
            or not isinstance(protocol, str)
            or protocol not in providers.PROTOCOLS
        ):
            raise ValueError("Choose a supported provider.")
        if (
            any(not isinstance(value, str) for value in (name, secret, organization))
            or len(name) > 100
            or len(secret) > 16000
            or len(organization) > 200
            or type(keyless) is not bool
            or type(reuse_secret) is not bool
        ):
            raise ValueError("Invalid connection details.")
        old = self._connection(state, connection_id) if connection_id else None
        if connection_id and old is None:
            raise ValueError("That saved connection is no longer available.")
        endpoint = providers.endpoint(endpoint)
        if provider != "custom":
            protocol = providers.PROVIDERS[provider]["protocol"]
            endpoint = ""
            keyless = False
        elif not endpoint or protocol == "anthropic":
            raise ValueError(
                "Enter an OpenAI-compatible server URL. Use the Anthropic provider for its native API."
            )
        if protocol != "openai":
            organization = ""
        if any(ord(char) < 32 for char in secret + organization):
            raise ValueError(
                "API keys and organization IDs must be single-line values."
            )
        new = {
            "provider": provider,
            "protocol": protocol,
            "endpoint": endpoint,
            "organization": organization.strip(),
            "keyless": keyless,
        }
        same_route = old and providers.route(
            old["protocol"], providers.address(old)
        ) == providers.route(protocol, providers.address(new))
        secret = secret.strip()
        if keyless:
            secret = ""
        elif not secret:
            if (
                old
                and old["secret"]
                and (old["provider"] and same_route or reuse_secret)
            ):
                secret = old["secret"]
            else:
                raise ValueError("Enter the API key for this provider or server.")
        if not secret and not keyless:
            raise ValueError("Enter an API key.")
        name = name.strip()
        used = {
            item["name"].casefold()
            for item in state["connections"]
            if item["id"] != connection_id
        }
        if not name:
            base = providers.PROVIDERS[provider]["label"]
            name, suffix = base, 2
            while name.casefold() in used:
                name = f"{base} {suffix}"
                suffix += 1
        if name.casefold() in used and (not old or name != old["name"]):
            raise ValueError("That connection name is already in use.")
        identity = old["id"] if old else uuid.uuid4().hex
        unchanged = (
            old
            and same_route
            and old["secret"] == secret
            and old["keyless"] == keyless
            and old["organization"] == organization.strip()
        )
        record = {
            **new,
            "id": identity,
            "name": name,
            "secret": secret,
            "runtime_name": old["runtime_name"] if old else "connection-" + identity,
            "model": old["model"] if old and same_route else "",
            "check": old["check"] if unchanged else providers.unchecked(),
            "models": old["models"] if unchanged else [],
        }
        state["connections"] = (
            [
                record if item["id"] == identity else item
                for item in state["connections"]
            ]
            if old
            else [*state["connections"], record]
        )
        if old and not same_route and state["draft"]:
            state["draft"]["models"].pop(identity, None)
        state["active"] = identity
        self._write(state)
        return self.describe()

    def check_connection(self, revision, connection_id):
        if not self.adapter.allow_providers:
            raise ValueError("Connection checks are disabled in offline mode.")
        state = self._read()
        self._revision(state, revision)
        connection = self._connection(state, connection_id)
        if not self._configured(connection):
            raise ValueError("Choose the provider and save this connection first.")
        result = providers.check(connection)
        current = self._read()
        latest = self._connection(current, connection_id)
        if not latest or any(
            latest[key] != connection[key]
            for key in (
                "provider",
                "protocol",
                "endpoint",
                "secret",
                "keyless",
                "organization",
            )
        ):
            raise ValueError(
                "The connection changed while checking it. Check it again."
            )
        latest["check"] = result["check"]
        if result["models"] is not None:
            latest["models"] = result["models"]
        self._write(current, bump=False)
        return self.describe()

    def prepare_engine(self, mode=None, resume=None):
        state = self._read()
        active = self._connection(state)
        if mode and active and not self._configured(active):
            raise ValueError(
                "Finish setting up the active connection in Settings before starting a run."
            )
        if mode and active and not active["model"].strip():
            raise ValueError(
                "Choose a model in Settings > Preferences before starting a run."
            )
        if mode in {"translate", "batch"} and not self._configured(active):
            raise ValueError("Save an API connection in Settings before translating.")
        values = self._values(state)
        if mode and active and active["provider"]:
            self.adapter.validate_route(values)
        if mode == "batch" and not self.translation_defaults()["batch_supported"]:
            raise ValueError("This connection does not support provider batch jobs.")
        if not values["model"]:
            values["model"] = state["values"]["model"]
        vault = {
            "active": active["runtime_name"] if self._configured(active) else "",
            "keys": {
                item["runtime_name"]: {
                    "secret": item["secret"],
                    "endpoint": providers.address(item)
                    if item["provider"]
                    else item["endpoint"],
                    "keyless": item["keyless"],
                }
                for item in state["connections"]
            },
        }
        if resume:
            key_name = resume["key_name"]
            connection = next(
                (
                    item
                    for item in state["connections"]
                    if item["runtime_name"] == key_name
                ),
                None,
            )
            if resume["mode"] not in {"estimate", "offline"}:
                if not self._configured(connection):
                    raise ValueError(
                        "Configure the saved run's connection in Settings before resuming."
                    )
                frozen = resume["settings"]
                expected = self.adapter.engine_route(
                    frozen["model"], frozen["API_PROVIDER"], frozen["api"]
                )
                actual = self.adapter.engine_route(
                    frozen["model"],
                    connection["protocol"],
                    providers.address(connection),
                )
                if expected != actual or connection["organization"] != frozen.get(
                    "organization", ""
                ):
                    raise ValueError(
                        "This connection's provider, server, or organization changed. Restore the saved run's original connection before resuming."
                    )
                vault["keys"][key_name]["endpoint"] = frozen["api"]
        self.adapter.install_settings(
            state["revision"], values, state["engines"], vault
        )
