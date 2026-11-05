"""Compare models: the same lines translated by several models, or one model
with changed settings (translation/compare.py)."""

from typing import Annotated, Literal, NotRequired, TypedDict

from dazedtl.api.contracts.settings import EffortLevel, EffortOption

type CompareKind = Literal["single", "versus", "tune"]


class CompareChoice(TypedDict):
    """A model on one of Settings' connections, and for Tune settings what
    its test changes."""

    connection_id: str
    model: str
    effort: NotRequired[
        Annotated[EffortLevel | None, "Tune settings: the thinking effort sent."]
    ]
    glossary: NotRequired[
        Annotated[str, "Tune settings: the whole glossary this test sends."]
    ]
    instruction: NotRequired[
        Annotated[str, "Tune settings: guidance this test adds to the game's."]
    ]


class ComparePrice(TypedDict):
    cost: Annotated[float, "The Live price of the model's requests, in USD."]
    requests: int


class CompareModel(TypedDict):
    index: int
    connection: Annotated[str, "The connection's name in Settings."]
    connectionId: str
    model: str
    effort: NotRequired[EffortLevel | None]
    glossary: NotRequired[str]
    instruction: NotRequired[str]
    estimate: NotRequired[ComparePrice]
    error: NotRequired[Annotated[str, "Why the model has no estimate or lines."]]
    cost: NotRequired[Annotated[float, "What its translation cost, in USD."]]
    seconds: NotRequired[float]
    requests: NotRequired[int]


class CompareTranslation(TypedDict):
    speaker: Annotated[str, "The name its name box shows, translated."]
    text: str


class CompareRow(TypedDict):
    id: Annotated[str, "The line's place in its file."]
    speaker: Annotated[str, "Its speaker's name in the source."]
    source: str
    translations: Annotated[
        list[CompareTranslation | None], "Each model's, in the models' order."
    ]
    problems: Annotated[
        list[list[str]], "What the checks found in each model's, in words."
    ]


class Comparison(TypedDict):
    id: Annotated[str, "Its estimate's operation."]
    translationId: Annotated[str | None, "Its translation's operation, once approved."]
    kind: CompareKind
    file: str
    lines: Annotated[int, "The first lines it holds; 0 for the whole file."]
    created: str
    stage: Literal["estimate", "translation"]
    status: str
    message: str
    candidates: list[CompareModel]
    rows: list[CompareRow]
    marks: Annotated[dict[str, int], "The model picked as best, by row ID."]
    blind: bool
    revealed: bool


class CompareScene(TypedDict):
    file: str
    title: Annotated[str, "Its map's name, where it has one."]
    lines: Annotated[int, "Lines whose source holds the game's language."]


class CompareState(TypedDict):
    available: bool
    reason: Annotated[str, "Why the game can't be compared yet."]
    scenes: list[CompareScene]
    glossary: Annotated[str, "The game's glossary, which a Tune test starts from."]
    comparisons: Annotated[list[Comparison], "Newest first."]


class CompareModelInfo(TypedDict):
    """What a model on a connection may be sent."""

    efforts: list[EffortOption]
    priced: Annotated[bool, "Whether its rates are known, so a run can be priced."]
