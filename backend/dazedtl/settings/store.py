"""Atomic preferences and profiles; saved secrets are never returned to the UI."""

from copy import deepcopy
import json
from pathlib import Path
import time
import uuid

from dazedtl.storage import WorkspaceError, read_versioned_json, write_json
from dazedtl.translation.refusals import POLICY as REFUSAL_POLICY
from . import providers, preferences, openrouter


class Settings:
    def __init__(self, workspace, adapter):
        self.adapter = adapter
        self._openrouter_prices = {}
        self.path = Path(workspace) / "settings" / "settings.json"
        self.metadata = adapter.settings_metadata()
        self.empty = {
            "version": 2,
            "revision": 0,
            "values": {
                key: self.metadata["values"][key] for key in ("language", "model")
            },
            "legacy": {"values": self.metadata["values"], "engines": {}, "draft": None},
            "model_options": {},
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
            or not isinstance(value.get("legacy"), dict)
            or not isinstance(value["legacy"].get("values"), dict)
            or not isinstance(value["legacy"].get("engines"), dict)
        ):
            raise invalid
        try:
            preferences.values(value.get("values"))
            preferences.model_options(value.get("model_options"))
        except ValueError as exc:
            raise invalid from exc
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
            try:
                preferences.model_options(connection.get("model_options"))
                if "catalog" in connection:
                    openrouter.validate_catalog(connection["catalog"])
                if "batch_endpoints" in connection:
                    openrouter.validate_endpoints(connection["batch_endpoints"])
                host = providers.openrouter_host(connection.get("openrouter_host", ""))
                if host and connection["provider"] != "openrouter":
                    raise ValueError("Only OpenRouter connections can select a host.")
            except ValueError as exc:
                raise invalid from exc
            identities.add(connection["id"])
            runtime_names.add(connection["runtime_name"])
        if (
            not isinstance(value.get("active"), str)
            or value["active"]
            and value["active"] not in identities
        ):
            raise invalid
        draft = value.get("draft")
        if draft is not None:
            if not isinstance(draft, dict) or not isinstance(
                draft.get("connections"), dict
            ):
                raise invalid
            try:
                preferences.text(draft.get("language"), "target language")
                for identity, profile in draft["connections"].items():
                    if (
                        identity
                        and identity not in identities
                        or not isinstance(profile, dict)
                    ):
                        raise invalid
                    preferences.text(profile.get("model"), "model ID")
                    preferences.model_options(profile.get("model_options"), draft=True)
            except ValueError as exc:
                raise invalid from exc

    def _read(self):
        if (
            self.path.is_symlink()
            or self.path.exists()
            and self.path.stat().st_size > 8_000_000
        ):
            raise WorkspaceError(
                "workspace_invalid", "Choose a regular settings file below 8 MB."
            )
        return read_versioned_json(
            self.path, self.empty, {1: preferences.upgrade_v1}, self._validate
        )

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

    def batch_connection(self, batch, plan):
        """Resolve the submitted account without using the current selection."""
        name = batch.get("key_name") or plan.get("key_name")
        connection = next(
            (
                item
                for item in self._read()["connections"]
                if item["runtime_name"] == name
            ),
            None,
        )
        if not self._configured(connection):
            raise ValueError(
                "This Batch's saved connection is unavailable. Restore that connection in Settings to read its status."
            )
        frozen = plan.get("settings", {})
        endpoint = batch.get("endpoint") or frozen.get("api")
        protocol = "openai" if batch["provider"] == "openrouter" else batch["provider"]
        if (
            not endpoint
            or providers.route(protocol, endpoint)
            != providers.route(connection["protocol"], providers.address(connection))
            or batch["provider"] == "openrouter"
            and connection["provider"] != "openrouter"
            or connection["organization"] != frozen.get("organization", "")
        ):
            raise ValueError(
                "This Batch's saved provider, server, or organization changed. Restore its original connection before reading status."
            )
        return {
            "secret": connection["secret"],
            "keyless": connection["keyless"],
            "endpoint": endpoint,
            "organization": connection["organization"],
            **(
                {
                    "openrouterBatch": (plan.get("dazedtl_request_policy") or {}).get(
                        "openrouterBatch"
                    )
                }
                if batch["provider"] == "openrouter"
                else {}
            ),
        }

    def _import(self):
        saved, vault, draft = self.adapter.import_settings()
        state = {
            "version": 1,
            "revision": saved["revision"],
            "values": saved["values"],
            "engines": saved["engines"],
            "active": "",
            "connections": [],
            "draft": None,
        }
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
        state = preferences.upgrade_v1(state)
        state["version"] = 2
        self._write(state, bump=False)

    def _values(self, state):
        values = {
            **self.metadata["values"],
            **state["legacy"]["values"],
            **state["values"],
        }
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
        values = {key: self._values(state)[key] for key in ("language", "model")}
        selected = self._connection(state)
        model_options = deepcopy(
            selected["model_options"] if selected else state["model_options"]
        )
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
                    "openrouter_host": item.get("openrouter_host", ""),
                    "needsSetup": not self._configured(item),
                }
            )
        result = {
            "revision": state["revision"],
            "values": values,
            "modelOptions": model_options,
            "defaultEntriesPerRequest": preferences.DEFAULT_ENTRIES_PER_REQUEST,
            "defaultOutputTokens": preferences.DEFAULT_OUTPUT_TOKENS,
            "defaultBatchInputTokens": preferences.DEFAULT_BATCH_INPUT_TOKENS,
            "activeConnectionId": state["active"],
            "connections": connections,
            "providers": [
                {
                    "id": name,
                    "label": definition["label"],
                    "protocol": definition["protocol"],
                    "defaultEndpoint": definition["endpoint"],
                }
                for name, definition in providers.PROVIDERS.items()
            ],
            "checksEnabled": self.adapter.allow_providers,
        }
        if state["draft"]:
            draft = state["draft"]
            profile = draft["connections"].get(state["active"])
            result["draft"] = {
                "values": {
                    "language": draft["language"],
                    "model": profile["model"] if profile else values["model"],
                },
                "modelOptions": deepcopy(
                    profile["model_options"] if profile else model_options
                ),
            }
        return result

    def ready(self):
        connection = self._connection(self._read())
        return self._configured(connection) and bool(connection["model"].strip())

    def guided_configuration(self, mode):
        from .execution import configuration

        state = self._read()
        return {
            **configuration(self, mode),
            "engine_settings": self._values(state),
            "stateGrouping": "compatible-states-v1",
            "choiceCollection": preferences.CHOICE_COLLECTION,
            "speakerContext": preferences.SPEAKER_CONTEXT,
        }

    def connection_summary(self):
        from .execution import connection_summary

        return connection_summary(self)

    def translation_defaults(self):
        state = self._read()
        values = self._values(state)
        active = self._connection(state)
        if active and not self._configured(active):
            values["model"] = ""
        result = self.adapter.provider_defaults(values)
        if active and active["provider"] == "openrouter" and values["model"]:
            defaults = openrouter.describe(active, values["model"])
            result.update(
                batch_supported=defaults["batchSupported"],
                batch_reason=defaults["batchReason"],
                default_mode=("batch" if defaults["batchSupported"] else "translate")
                if self.adapter.allow_providers
                else "estimate",
            )
        elif (
            values.get("api", "").rstrip("/")
            == providers.PROVIDERS["openrouter"]["endpoint"]
        ):
            result.update(
                batch_supported=False,
                batch_reason="Choose the OpenRouter connection preset for Batch.",
                default_mode="translate"
                if self.adapter.allow_providers
                else "estimate",
            )
        return result

    def model_defaults(
        self, connection_id, model, *, cached_only=False, batch_endpoints=None
    ):
        state = self._read()
        if connection_id != state["active"]:
            raise ValueError("The active connection changed. Reopen Settings.")
        active = self._connection(state)
        if active and active["provider"] == "openrouter":
            if batch_endpoints is not None:
                active = {**active, "batch_endpoints": batch_endpoints}
            value = openrouter.describe(active, model)
            cached = self._openrouter_prices.get(
                (active["id"], model, active.get("openrouter_host", ""))
            )
            if cached:
                value.update(
                    {key: item for key, item in cached[1].items() if key != "host"},
                    stale=time.monotonic() - cached[0] > 600,
                )
            return value
        if cached_only:
            cached = getattr(
                getattr(self.adapter, "model_defaults", None), "cached", None
            )
            return cached(model) if cached is not None else {}
        return self.adapter.model_defaults.describe(model)

    def batch_lookup(self, *, connection_id=None, model=None):
        """Select a targeted endpoint read; observations never call this."""
        active = self._connection(self._read())
        if connection_id is not None and connection_id != (
            active["id"] if active else ""
        ):
            raise ValueError("The active connection changed. Reopen Settings.")
        if (
            not active
            or active["provider"] != "openrouter"
            or not self.adapter.allow_providers
            or not self._configured(active)
            or active["check"]["status"] != "verified"
        ):
            return None
        model = (
            active["model"]
            if model is None
            else preferences.text(model, "model ID", required=True)
        )
        row = (
            active.get("catalog", {}).get(model + ":batch", {})
            if ":" not in model
            else {}
        )
        if not model or not row.get("text") or not row.get("json"):
            return None
        endpoints = active.get("batch_endpoints", {})
        if (
            endpoints.get("model") == model
            and endpoints.get("host") == active.get("openrouter_host", "")
            and "providers" in endpoints
            and not endpoints.get("error")
        ):
            return None
        return {"connection": active, "model": model}

    def retain_batch_endpoints(self, lookup, endpoints, *, persist):
        state = self._read()
        active, previous = self._connection(state), lookup["connection"]
        keys = (
            "id",
            "provider",
            "protocol",
            "endpoint",
            "secret",
            "keyless",
            "organization",
            "model",
            "openrouter_host",
            "check",
            "catalog",
            "batch_endpoints",
        )
        if not active or any(active.get(key) != previous.get(key) for key in keys):
            if persist:
                return None  # A completed save must not overwrite a newer selection.
            raise ValueError(
                "The connection or model changed while checking Batch support. Try again."
            )
        openrouter.validate_endpoints(endpoints)
        if endpoints.get("model") != lookup["model"] or endpoints.get(
            "host"
        ) != active.get("openrouter_host", ""):
            raise ValueError(
                "The Batch endpoints do not match the selected model and host."
            )
        if persist:
            if lookup["model"] != active["model"]:
                raise ValueError("Only the saved model can retain Batch availability.")
            active["batch_endpoints"] = endpoints
            self._write(state, bump=False)
        return endpoints

    def pricing_lookup(self, *, connection_id=None, model=None, explicit=False):
        """Choose an optional public read while the caller holds the app lock."""
        state = self._read()
        active = self._connection(state)
        if (
            not active
            or active["provider"] != "openrouter"
            or not self.adapter.allow_providers
        ):
            return None
        if connection_id is not None and connection_id != active["id"]:
            raise ValueError("The active connection changed. Reopen Settings.")
        model = (
            active["model"]
            if model is None
            else preferences.text(model, "model ID", required=True)
        )
        if not model:
            return None
        options = active["model_options"].get(model, preferences.DEFAULT_OPTIONS)
        if not explicit and options["pricing"] == "custom":
            return None
        known = self.model_defaults(active["id"], model)
        if (
            known["inputRate"] is not None
            and known["outputRate"] is not None
            and not known["stale"]
        ):
            return None
        return {
            "connection": {
                key: active.get(key, "")
                for key in (
                    "id",
                    "provider",
                    "protocol",
                    "endpoint",
                    "model",
                    "openrouter_host",
                )
            },
            "model": model,
            "host": active.get("openrouter_host", ""),
        }

    def pricing_selection(self, lookup):
        state = self._read()
        active = self._connection(state)
        if not active or any(
            active.get(key, "") != value for key, value in lookup["connection"].items()
        ):
            raise ValueError(
                "The connection or model changed while reading prices. Try again with the current selection."
            )
        return active

    def retain_prices(self, lookup, prices):
        """A late lookup cannot replace another connection/model's defaults."""
        active = self.pricing_selection(lookup)
        if prices["model"] != lookup["model"] or prices["host"] != lookup["host"]:
            raise ValueError(
                "The returned prices do not match the selected model and host."
            )
        key = (active["id"], lookup["model"], lookup["host"])
        self._openrouter_prices.pop(key, None)
        self._openrouter_prices[key] = (time.monotonic(), deepcopy(prices))
        while len(self._openrouter_prices) > 64:
            self._openrouter_prices.pop(next(iter(self._openrouter_prices)))

    @staticmethod
    def _clear_draft(state, connection_id):
        profiles = (state["draft"] or {}).get("connections", {})
        profiles.pop(connection_id, None)
        state["draft"] = (
            {"language": state["values"]["language"], "connections": profiles}
            if profiles
            else None
        )

    def save(self, revision, connection_id, values, model_options):
        state = self._read()
        self._revision(state, revision)
        if connection_id != state["active"]:
            raise ValueError(
                "The active connection changed. Review its preferences before saving."
            )
        connection = self._connection(state)
        normalized = preferences.values(values, connection=connection is not None)
        if (
            connection
            and connection["provider"] == "openrouter"
            and ":batch" in normalized["model"]
        ):
            raise ValueError(
                "Save the base OpenRouter model ID, then choose Batch as the translation method."
            )
        configured = preferences.model_options(model_options)
        state["values"]["language"] = normalized["language"]
        if connection:
            connection.update(model=normalized["model"], model_options=configured)
        else:
            state["values"]["model"] = normalized["model"]
            state["model_options"] = configured
        self._clear_draft(state, connection_id)
        self._write(state)
        return self.describe()

    def draft(self, revision, connection_id, values, model_options):
        state = self._read()
        self._revision(state, revision)
        if connection_id != state["active"]:
            raise ValueError(
                "The active connection changed. Reopen Settings before editing its preferences."
            )
        preferences.values(values, draft=True)
        preferences.model_options(model_options, draft=True)
        if len(json.dumps([values, model_options])) > 100000:
            raise ValueError("Preferences draft is too large.")
        profiles = (state["draft"] or {}).get("connections", {})
        profiles[connection_id] = {
            "model": values["model"],
            "model_options": model_options,
        }
        state["draft"] = {"language": values["language"], "connections": profiles}
        self._write(state, bump=False)
        return {"saved": True}

    def revert(self, revision, connection_id):
        state = self._read()
        self._revision(state, revision)
        if connection_id != state["active"]:
            raise ValueError(
                "The active connection changed. Reopen Settings before reverting."
            )
        self._clear_draft(state, connection_id)
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
        openrouter_host=None,
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
        host = (
            providers.openrouter_host(
                openrouter_host
                if openrouter_host is not None
                else (old or {}).get("openrouter_host", "")
            )
            if provider == "openrouter"
            else ""
        )
        endpoint = providers.endpoint(endpoint)
        if provider != "custom":
            protocol = providers.PROVIDERS[provider]["protocol"]
            endpoint = ""
            keyless = False
        elif not endpoint or protocol == "anthropic":
            raise ValueError(
                "Enter an OpenAI-compatible server URL. Use the Anthropic provider for its native API."
            )
        if protocol != "openai" or provider == "openrouter":
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
            "openrouter_host": host,
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
            "model_options": old["model_options"] if old and same_route else {},
            "check": old["check"] if unchanged else providers.unchecked(),
            "models": old["models"] if unchanged else [],
            **(
                {"catalog": old.get("catalog", {})}
                if unchanged and old and provider == "openrouter"
                else {}
            ),
            **(
                {"batch_endpoints": old.get("batch_endpoints", {})}
                if unchanged and old and provider == "openrouter"
                else {}
            ),
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
            state["draft"]["connections"].pop(identity, None)
        state["active"] = identity
        self._write(state)
        return self.describe()

    def openrouter_hosts(self, model=""):
        if not self.adapter.allow_providers:
            raise ValueError("Host lookup is disabled in offline mode.")
        return providers.openrouter_hosts(model)

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
            latest.get(key) != connection.get(key)
            for key in (
                "provider",
                "protocol",
                "endpoint",
                "secret",
                "keyless",
                "organization",
                "openrouter_host",
                "model",
            )
        ):
            raise ValueError(
                "The connection changed while checking it. Check it again."
            )
        latest["check"] = result["check"]
        if result["models"] is not None:
            latest["models"] = result["models"]
        if "catalog" in result:
            latest["catalog"] = result["catalog"]
            latest["batch_endpoints"] = result.get("batch_endpoints", {})
            # A new authenticated catalog supersedes earlier public quotes.
            self._openrouter_prices = {
                key: value
                for key, value in self._openrouter_prices.items()
                if key[0] != connection_id
            }
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
        self.adapter.manual.request_policy = None
        if mode:
            configured = (
                active["model_options"] if active else state["model_options"]
            ).get(values["model"], preferences.DEFAULT_OPTIONS)
            custom = configured["pricing"] == "custom"
            defaults = self.model_defaults(
                state["active"], values["model"], cached_only=custom
            )
            input_rate = configured["inputRate"] if custom else defaults["inputRate"]
            output_rate = configured["outputRate"] if custom else defaults["outputRate"]
            if input_rate is None or output_rate is None:
                raise ValueError(
                    "No price is available for this model. Enter custom rates in Settings before starting; use 0 for a free model."
                )
            entries = (
                configured["entriesPerRequest"]
                or preferences.DEFAULT_ENTRIES_PER_REQUEST
            )
            self.adapter.manual.request_policy = {
                "version": 1,
                "model": values["model"],
                "generationParameters": preferences.GENERATION_PARAMETERS,
                "maxOutputTokens": preferences.output_allowance(
                    configured.get("maxOutputTokens"), defaults.get("maxOutputTokens")
                ),
                "refusalRetry": REFUSAL_POLICY,
                "stateGrouping": "compatible-states-v1",
                "choiceCollection": preferences.CHOICE_COLLECTION,
                "speakerContext": preferences.SPEAKER_CONTEXT,
                "entriesPerRequest": entries,
                "inputRate": input_rate,
                "outputRate": output_rate,
                "source": "custom" if custom else defaults["source"],
                "updatedAt": None if custom else defaults["updatedAt"],
            }
            if active and active["provider"] == "openrouter":
                self.adapter.manual.request_policy["openrouterStructuredOutputs"] = (
                    openrouter.STRUCTURED_OUTPUTS
                )
                self.adapter.manual.request_policy["openrouterBatch"] = (
                    openrouter.policy(
                        active, values["model"], configured, required=mode == "batch"
                    )
                )
                if mode == "batch":
                    batch_limit = self.adapter.manual.request_policy[
                        "openrouterBatch"
                    ].get("max_output")
                    self.adapter.manual.request_policy["maxOutputTokens"] = (
                        preferences.output_allowance(
                            self.adapter.manual.request_policy["maxOutputTokens"],
                            batch_limit,
                        )
                    )
            if (active and active["provider"] == "openai") or configured.get(
                "batchInputTokens"
            ) is not None:
                self.adapter.manual.request_policy["batchInputTokens"] = (
                    configured.get("batchInputTokens")
                    or preferences.DEFAULT_BATCH_INPUT_TOKENS
                )
            if (
                active
                and active["provider"] == "openrouter"
                and active.get("openrouter_host")
            ):
                self.adapter.manual.request_policy["openrouterHost"] = active[
                    "openrouter_host"
                ]
            values.update(batchsize=entries)
        self.adapter.install_settings(
            state["revision"], values, state["legacy"]["engines"], vault
        )
