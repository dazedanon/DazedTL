"""Preferences, model options and provider connections."""

from typing import Literal, NotRequired, TypedDict


class PreferenceValues(TypedDict):
    language: str
    model: str


class ModelOptions(TypedDict):
    entriesPerRequest: Literal[""] | int | None
    batchInputTokens: NotRequired[int | None]
    maxOutputTokens: NotRequired[int | None]
    pricing: Literal["automatic", "custom"]
    inputRate: Literal[""] | float | None
    outputRate: Literal[""] | float | None
    batchPricing: NotRequired[Literal["automatic", "custom"]]
    batchInputRate: NotRequired[Literal[""] | float | None]
    batchOutputRate: NotRequired[Literal[""] | float | None]


class ModelDefaults(TypedDict):
    model: str
    inputRate: float | None
    outputRate: float | None
    source: Literal["catalog", "engine_default", "unavailable"]
    updatedAt: str | None
    stale: bool
    maxOutputTokens: NotRequired[int | None]
    batchSupported: NotRequired[bool]
    batchReason: NotRequired[str]
    batchInputRate: NotRequired[float | None]
    batchOutputRate: NotRequired[float | None]


class SettingsProvider(TypedDict):
    id: Provider
    label: str
    protocol: ProviderProtocol
    defaultEndpoint: str


class SettingsDraft(TypedDict):
    values: PreferenceValues
    modelOptions: dict[str, ModelOptions]


class Settings(TypedDict):
    revision: int
    values: PreferenceValues
    modelOptions: dict[str, ModelOptions]
    defaultEntriesPerRequest: int
    defaultOutputTokens: NotRequired[int]
    defaultBatchInputTokens: NotRequired[int]
    activeConnectionId: str
    connections: list[Connection]
    providers: list[SettingsProvider]
    checksEnabled: bool
    draft: NotRequired[SettingsDraft]


type Provider = Literal[
    "openai", "openrouter", "anthropic", "gemini", "mistral", "custom"
]


type ProviderProtocol = Literal["openai", "anthropic", "gemini", "mistral"]


class ConnectionCheck(TypedDict):
    status: Literal[
        "not_checked", "verified", "reachable", "failed", "unavailable", "unsupported"
    ]
    message: str
    checkedAt: str | None


class Connection(TypedDict):
    id: str
    name: str
    provider: Provider | None
    protocol: ProviderProtocol
    endpoint: str
    organization: str
    openrouter_host: NotRequired[str]
    keyless: bool
    has_secret: bool
    needsSetup: bool
    model: str
    models: list[str]
    check: ConnectionCheck


class ConnectionInput(TypedDict):
    connection_id: NotRequired[str]
    provider: Provider
    protocol: ProviderProtocol
    name: str
    secret: str
    endpoint: str
    organization: str
    openrouter_host: NotRequired[str]
    keyless: bool
    reuse_secret: bool


class SettingsPayload(TypedDict):
    revision: int
    values: PreferenceValues
    modelOptions: dict[str, ModelOptions]
    activeConnectionId: str


class OpenRouterHost(TypedDict):
    slug: str
    name: str
