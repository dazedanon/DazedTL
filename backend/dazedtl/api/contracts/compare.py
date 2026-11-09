"""Compare models: the same lines translated by several models, or one model
with changed settings (translation/compare.py)."""

from typing import Annotated, Literal, NotRequired, TypedDict

from dazedtl.api.contracts.settings import EffortLevel, EffortOption

# "tune" names only comparisons saved before Tune settings joined the one
# workspace; new ones are "single" or "versus".
type CompareKind = Literal["single", "versus", "tune"]


class CompareChoice(TypedDict):
    """A model on one of Settings' connections, with the settings its
    column changes from the game's."""

    connection_id: str
    model: str
    effort: NotRequired[Annotated[EffortLevel | None, "The thinking effort sent."]]
    glossary: NotRequired[Annotated[str, "The whole glossary this column sends."]]
    glossary_revision: NotRequired[
        Annotated[str, "The game glossary's revision its glossary was edited from."]
    ]
    instruction: NotRequired[Annotated[str, "Guidance this column adds to the game's."]]


class ComparePrice(TypedDict):
    cost: Annotated[float, "The Live price of the model's requests, in USD."]
    requests: int


class CompareModel(TypedDict):
    index: int
    connection: Annotated[str, "The connection's name in Settings."]
    model: str
    choice: Annotated[
        CompareChoice,
        "What its estimate was made from, settings and all, as a column's choice.",
    ]
    glossaryChanged: NotRequired[
        Annotated[
            bool,
            "The game's glossary changed in Context after this column's "
            "glossary edit, so Use asks which to keep.",
        ]
    ]
    estimate: NotRequired[ComparePrice]
    error: NotRequired[Annotated[str, "Why the model has no estimate or lines."]]
    cost: NotRequired[
        Annotated[float, "What its translation cost, in USD, even when it failed."]
    ]
    seconds: NotRequired[float]
    requests: NotRequired[Annotated[int, "The requests its translation sent."]]
    keptRequests: NotRequired[
        Annotated[int, "The first requests it sent that Show request can open."]
    ]
    finished: NotRequired[
        Annotated[bool, "It translated every line, so it can be used."]
    ]
    stopped: NotRequired[
        Annotated[bool, "The user stopped its translation before it finished."]
    ]
    reused: NotRequired[
        Annotated[
            bool,
            "An earlier translation of the same lines, inputs and settings "
            "finished, so this one sends nothing and shows that one's lines.",
        ]
    ]


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


class CompareOperation(TypedDict):
    """A comparison operation as the Compare page follows it."""

    id: str
    action: Literal["compare_estimate", "compare_translate"]
    label: str
    status: str
    message: str
    stopping: Annotated[bool, "A stop was asked for and the models are ending."]


class CompareScene(TypedDict):
    file: str
    title: Annotated[str, "Its map's name, where it has one."]
    lines: Annotated[int, "Lines whose source holds the game's language."]


class CompareState(TypedDict):
    available: bool
    reason: Annotated[str, "Why the game can't be compared yet."]
    scenes: list[CompareScene]
    glossary: Annotated[
        str, "The game's glossary, which a column's test glossary starts from."
    ]
    glossaryRevision: Annotated[str, "The revision of the glossary's file it read."]
    comparisons: Annotated[list[Comparison], "Newest first."]


class CompareModelInfo(TypedDict):
    """What a model on a connection may be sent."""

    efforts: list[EffortOption]
    priced: Annotated[bool, "Whether its rates are known, so a run can be priced."]
