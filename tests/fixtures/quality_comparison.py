"""Measured quality comparisons (util/quality_set.py, util/evaluation_quality.py):
a set built from a QA export and split with each recurring group whole; both
methods' requests built from the set alone, the default prompt byte-identical
to a copy of it; runs that reuse their replies after a crash and keep to
their cap; a targeted item file; the scoring, noise floor and verdict; and a
judge whose calibration fails getting its scores withheld."""

import json
import re
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

root, temporary = map(Path, sys.argv[1:])
sys.path.insert(0, str(root / "backend/dazedtl/engine"))
sys.path.insert(0, str(root / "backend"))

from util import (
    evaluation,
    quality_set,
    translation,
)
from util import evaluation_quality as quality
from util import qa_corrections as corrections
from util.paths import PROMPT_PATH, runtime_data_file
from util.qa.schema import CHECKPOINT_SCHEMA, FINDINGS_SCHEMA, TASK_SCHEMA
from util.rpgmaker_qa_manifest import build_manifest


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


# A scene of 14 messages: Yuuki speaks the even ones, the odd ones name no
# speaker. Fixes: a glossary term, a reversed action, and one fix QA made on
# three lines (a recurring group).
LINES = [
    ("魔物が来た！", "A monster is coming!", "A Monster is coming!", "terminology"),
    ("鍵を閉めた。", "She unlocked the door.", "She locked the door.", "meaning"),
    ("おはよう、ボス。", "Morning, boss.", "Morning, chief.", "voice"),
    ("ボス、行こう。", "Let's go, boss.", "Let's go, chief.", "voice"),
    ("ボスは強い。", "The boss is strong.", "The chief is strong.", "voice"),
] + [
    (f"{word}だ。", f"It's {english}.", None, None)
    for word, english in (
        ("猫", "a cat"),
        ("犬", "a dog"),
        ("空", "the sky"),
        ("海", "the sea"),
        ("山", "a mountain"),
        ("川", "a river"),
        ("森", "a forest"),
        ("花", "a flower"),
        ("星", "a star"),
    )
]
game = temporary / "Game Q"


def write_game(corrected):
    commands = []
    for index, (japanese, english, fixed, _category) in enumerate(LINES):
        named = index % 2 == 0
        head = {
            "code": 101,
            "indent": 0,
            "parameters": ["", 0, 0, 2, "Yuuki" if named else ""],
        }
        if named:
            head["_original"] = "ユーキ"
        commands.append(head)
        text = fixed if corrected and fixed else english
        commands.append(
            {"code": 401, "indent": 0, "parameters": [text], "_original": japanese}
        )
    commands.append({"code": 0, "indent": 0, "parameters": []})
    write(
        game / "data/Map001.json",
        {"events": [None, {"id": 1, "pages": [{"list": commands}]}]},
    )


write_game(corrected=False)
inventory = build_manifest(game / "data", "release")
task = (
    temporary / "workspace/engine/workflows/p1/text-qa/Game-Q/release/1111111111111111"
)
write(
    task / "task.json",
    {
        "schema": TASK_SCHEMA,
        "game_root": str(game),
        "data_root": str(game / "data"),
        "focus": "release",
        "created_at": "2026-01-01T00:00:00+00:00",
    },
)
write(task / "checkpoint.json", {"schema": CHECKPOINT_SCHEMA, "stage": "complete"})
write(task / "inventory.json", inventory)
write(
    task / "context.json",
    {
        "game": {"text": "# Translation Frame\n\n- A quiet village."},
        "quirks": {"text": "- Yuuki is curt."},
        "overlays": [],
        "glossary": {"text": "# Game Terms\n魔物 (Monster)\n"},
    },
)


def identity(source):
    return next(
        record["identity"]
        for record in inventory["records"]
        if record["source"] == source
    )


write(
    task / "findings.json",
    {
        "schema": FINDINGS_SCHEMA,
        "coverage": {"screen": {"accepted": 14, "total": 14}},
        "findings": [
            {
                "id": f"QA-{index:04d}",
                "category": category,
                "severity": "medium",
                "family_key": "",
                "source": japanese,
                "current": english,
                "correction": fixed,
                "target_identities": [identity(japanese)],
                "evidence": f"Fix {japanese}",
            }
            for index, (japanese, english, fixed, category) in enumerate(LINES)
            if fixed
        ],
        "uncertain_playtests": [],
        "not_reviewed": [],
    },
)
write_game(corrected=True)
origins, skipped = corrections.find_origins([task])
export = temporary / "export.jsonl"
corrections.export(corrections.collect(origins, skipped), export)

# The set: every fix but the format ones, the unfixed lines as controls, each
# item in the chunk of ten its scene sends and the lines before it.
header, items = quality_set.build(export, defects=10, controls=9)
defects = {
    item["lines"][item["target"]]["source"]: item
    for item in items
    if item["type"] == "defect"
}
assert set(defects) == {japanese for japanese, _e, fixed, _c in LINES if fixed}, defects
assert defects["魔物が来た！"]["glossary"] == [{"source": "魔物", "target": "Monster"}]
assert (
    defects["鍵を閉めた。"]["glossary"] == []
    and defects["鍵を閉めた。"]["kind"] == "meaning"
)
group = {
    defects[source]["split"]
    for source in ("おはよう、ボス。", "ボス、行こう。", "ボスは強い。")
}
assert len(group) == 1 and defects["ボスは強い。"]["group"], defects["ボスは強い。"]
controls = [item for item in items if item["type"] == "control"]
assert len(controls) == 9 and all(
    item["draft"] == item["accepted"] for item in controls
)
assert not {item["lines"][item["target"]]["source"] for item in controls} & set(defects)
late = next(item for item in controls if item["lines"][0]["source"] == "川だ。")
assert len(late["history"]) == 10 and len(late["lines"]) == 4, late
first = defects["魔物が来た！"]["lines"][0]
assert (first["speaker"], first["speaker_name"], first["kind"]) == (
    "ユーキ",
    "Yuuki",
    "dialogue",
), first
assert defects["鍵を閉めた。"]["lines"][1]["kind"] == "unknown"
context = next(iter(header["contexts"].values()))
assert (
    context["overlays"][0].startswith("## Game Translation Frame")
    and "魔物 (Monster)" in context["glossary"]
)
for refused in (root / "set.jsonl", root / "tests/set.jsonl"):
    try:
        quality_set.write(refused, header, items)
    except ValueError:
        pass
    else:
        raise AssertionError(f"a set was written into {refused}")
set_path = quality_set.write(temporary / "out/set.jsonl", header, items)

# A targeted item file: two cases a change fires on, its own version, no split.
targeted_items = [
    {
        **{key: value for key, value in defects[source].items() if key != "split"},
        "id": f"t{index}",
    }
    for index, source in enumerate(("鍵を閉めた。", "魔物が来た！"))
]
targeted_header = {
    **header,
    "kind": "targeted",
    "name": "reversed-actions",
    "version": 3,
}
targeted_path = quality_set.write(
    temporary / "out/targeted.jsonl", targeted_header, targeted_items
)
try:
    quality_set.write(
        temporary / "out/bad.jsonl",
        targeted_header,
        [{**targeted_items[0], "split": "tune"}],
    )
except ValueError:
    pass
else:
    raise AssertionError("a targeted item joined a split")

# Runs read nothing of the game or its task, nor the translation cache.
shutil.rmtree(game)
shutil.rmtree(temporary / "workspace")
loaded = quality.load(set_path, [targeted_path])
assert quality.scopes(loaded) == ["held-out", "tune", "targeted:reversed-actions"], (
    quality.scopes(loaded)
)


def cache_touched(*_args, **_kwargs):
    raise AssertionError("the runner touched the translation cache")


cache = [
    patch.object(translation, name, cache_touched)
    for name in (
        "get_cached_translation",
        "peek_cached_translation",
        "queue_batch_request",
    )
]
for stand_in in cache:
    stand_in.start()

guided = quality.variant(
    {
        "name": "g",
        "method": "guided",
        "provider": "anthropic",
        "model": "claude-opus-5-5",
        "endpoint": "http://127.0.0.1:9/v1",
        "execution": "live",
    }
)
assistant = quality.variant(
    {
        **guided,
        "name": "a",
        "method": "assistant-led",
        "provider": "openai",
        "model": "stand-in",
    }
)
item = loaded["by_key"]["qa-corrections/" + defects["魔物が来た！"]["id"]]
made = quality.request(item, loaded, guided)
system_text = made["params"]["system"][0]["text"]
assert (
    "## Game Translation Frame" in system_text
    and "## Game-Specific Translation Quirks" in system_text
)
assert "Monster" in made["params"]["system"][1]["text"], made["params"]["system"]
assert "[Yuuki]: 魔物が来た！" in made["params"]["messages"][-1]["content"]
assert "thinking" not in made["params"] and "temperature" not in made["params"]
# The default prompt file and a copy of it send the same request; another
# prompt file changes only the method part of the system prompt.
copy = temporary / "system-copy.md"
copy.write_text(
    runtime_data_file(PROMPT_PATH).read_text(encoding="utf-8"), encoding="utf-8"
)
assert (
    quality.request(item, loaded, quality.variant({**guided, "prompt": str(copy)}))[
        "params"
    ]
    == made["params"]
)
other = temporary / "system-other.md"
other.write_text("Translate tersely.", encoding="utf-8")
changed = quality.request(
    item, loaded, quality.variant({**guided, "prompt": str(other)})
)["params"]
assert changed["system"][0]["text"].startswith(
    "```\nTranslate tersely.\n\n## Game Translation Frame"
)
assert changed["messages"] == made["params"]["messages"]
effort = quality.request(item, loaded, quality.variant({**guided, "effort": "high"}))[
    "params"
]
assert (
    effort["thinking"] == {"type": "adaptive"}
    and effort["output_config"]["effort"] == "high"
)
late_item = loaded["by_key"]["qa-corrections/" + late["id"]]
assert "猫だ。" in json.dumps(
    quality.request(late_item, loaded, guided)["params"]["messages"][0],
    ensure_ascii=False,
)
built = quality.request(item, loaded, assistant)
user = built["params"]["messages"][-1]["content"]
assert "Speakers by line" in user and "ユーキ: 1" in user and "Line kinds" in user, user
assert set(json.loads(re.search(r"```json\n(.*?)\n```", user, re.DOTALL).group(1))) == {
    str(n) for n in range(1, 11)
}
assert built["params"]["response_format"]["json_schema"]["schema"]["required"] == [
    str(n) for n in range(1, 11)
]
no_kinds = {
    **targeted_items[0],
    "lines": [
        {k: v for k, v in line.items() if k != "kind"}
        for line in targeted_items[0]["lines"]
    ],
}
assert quality_set.unavailable(
    no_kinds, "assistant-led"
) and not quality_set.unavailable(no_kinds, "guided")


class Provider:
    """Answers translation requests like a model: each line from *answers*
    by its source, else "Tested"; Guided's with the speaker it was sent."""

    free = True

    def __init__(self, answers, batch=False, ended=True):
        self.answers, self.batch, self.ended = answers, batch, ended
        self.sent, self.batches = [], {}

    def live(self, params):
        self.sent.append(params)
        content = params["messages"][-1]["content"]
        payload = json.loads(re.findall(r"```json\n(.*?)\n```", content, re.DOTALL)[-1])
        reply = {}
        for key, line in payload.items():
            speaker = re.match(r"^\[[^\]]+\]: ", line)
            source = line[speaker.end() :] if speaker else line
            reply[key] = (speaker.group(0) if speaker else "") + self.answers.get(
                source, "Tested."
            )
        return {
            "text": json.dumps(reply, ensure_ascii=False),
            "prompt_tokens": 10,
            "completion_tokens": 5,
        }

    def submit(self, rows):
        batch_id = f"batch-{len(self.batches)}"
        self.batches[batch_id] = rows
        return batch_id

    def status(self, _batch_id):
        return {"ended": self.ended}

    def results(self, batch_id, custom_ids):
        rows = self.batches.get(batch_id) or BATCHES[batch_id]
        return (
            {custom_ids[row["custom_id"]]: self.live(row["params"]) for row in rows},
            [],
            {},
        )


drafts = {
    item["lines"][item["target"]]["source"]: item["draft"] for item in loaded["items"]
}
fixed = {
    item["lines"][item["target"]]["source"]: item["accepted"]
    for item in loaded["items"]
}
runs = temporary / "runs"
log = []
# A Batch submitted before a crash is collected, not sent again, and a run
# translated again sends nothing.
crashed = Provider(drafts, batch=True, ended=False)
first_status = quality.translate(
    loaded, guided, runs, "base-1", transport=crashed, cap=None, log=log.append
)
assert (
    first_status["pending"] == first_status["requests"] and len(crashed.batches) == 1
), first_status
BATCHES = crashed.batches
resumed = Provider(drafts, batch=True)
done = quality.translate(
    loaded, guided, runs, "base-1", transport=resumed, cap=None, log=log.append
)
assert done["replied"] == done["requests"] and not resumed.batches, done
again = Provider(drafts)
quality.translate(
    loaded, guided, runs, "base-1", transport=again, cap=None, log=log.append
)
assert again.sent == []
quality.translate(
    loaded, guided, runs, "base-2", transport=Provider(drafts), cap=None, log=log.append
)
quality.translate(
    loaded, guided, runs, "fixed", transport=Provider(fixed), cap=None, log=log.append
)
try:
    quality.translate(
        loaded,
        quality.variant({**guided, "effort": "low"}),
        runs,
        "base-1",
        transport=Provider(drafts),
        cap=None,
        log=log.append,
    )
except ValueError:
    pass
else:
    raise AssertionError("a run ID was reused for another variant")
assert not list(temporary.rglob("translation_cache.json")) and not list(
    Path.cwd().rglob("translation_cache.json")
)

# A paid connection keeps to its cap: a slice holds what the cap can pay at
# most, and nothing is sent when not even one request fits.
paid = quality.variant(
    {
        **guided,
        "name": "paid",
        "endpoint": "https://api.anthropic.com",
        "execution": "batch",
        "keyless": False,
    }
)
with patch.object(
    evaluation,
    "pricing_for",
    return_value={"input": 1.0, "cached_input": 0.1, "output": 5.0},
):
    one = quality.estimate([(made["params"], 100)], paid)["maximum_cost_usd"]
    capped = Provider(drafts, batch=True, ended=False)
    capped.free = False
    for cap in (None, one / 2):
        try:
            quality.translate(
                loaded, paid, runs, "paid", transport=capped, cap=cap, log=log.append
            )
        except ValueError:
            pass
        else:
            raise AssertionError(f"a request was sent past a cap of {cap}")
    assert not capped.batches
    quality.translate(
        loaded, paid, runs, "paid", transport=capped, cap=one * 2.5, log=log.append
    )
    assert [len(rows) for rows in capped.batches.values()] == [2], capped.batches

# Comparison with the stand-in judge: the baseline repeats every defect, the
# variant fixes them, on the held-out half and the targeted file alike.
result = quality.compare(
    loaded,
    runs,
    ["base-1", "base-2"],
    ["fixed"],
    quality.judge(
        {
            "provider": "openai",
            "model": "stand-in",
            "execution": "live",
            "keyless": True,
        }
    ),
    compare_id="dry",
    transport=None,
    cap=None,
    stand_in=True,
    log=log.append,
)
assert (
    result["calibration"]["passed"] and result["calibration"]["defect"]["j"] == 1.0
), result["calibration"]
targeted = result["scopes"]["targeted:reversed-actions"]["metrics"]
assert (
    targeted["defects"]["rates"]["base-1"]["rate"] == 1.0
    and targeted["defects"]["rates"]["fixed"]["rate"] == 0.0
)
assert (
    targeted["defects"]["changes"]["fixed"]["gain"]
    and targeted["glossary"]["rates"]["fixed"]["rate"] == 1.0
)
assert targeted["defects"]["noise"]["gap"] == 0.0
assert result["verdicts"]["fixed"]["pass"], result["verdicts"]
assert "STAND-IN" in quality.render(result) and (runs / "dry/report.json").is_file()
# The baseline alone reports its rates, noise floor and the judge's calibration.
alone = quality.compare(
    loaded,
    runs,
    ["base-1", "base-2"],
    [],
    quality.judge(
        {
            "provider": "openai",
            "model": "stand-in",
            "execution": "live",
            "keyless": True,
        }
    ),
    compare_id="baseline",
    transport=None,
    cap=None,
    stand_in=True,
    log=log.append,
)
assert alone["calibration"]["passed"] and not alone["verdicts"]
assert (
    alone["scopes"]["held-out"]["metrics"]["validity"]["rates"]["base-2"]["rate"] == 1.0
)


class Lenient:
    """A judge that never finds a fault, so it cannot tell drafts from fixes."""

    free, batch = True, False

    def live(self, params):
        kind = "repeats" if "repeats" in json.dumps(params) else "worse"
        return {
            "text": json.dumps(
                {kind: False if kind == "repeats" else "neither", "evidence": "-"}
            )
        }


lenient = quality.compare(
    loaded,
    runs,
    ["base-1", "base-2"],
    ["fixed"],
    quality.judge(
        {
            "provider": "openai",
            "model": "lenient",
            "endpoint": "http://127.0.0.1:9/v1",
            "execution": "live",
        }
    ),
    compare_id="lenient",
    transport=Lenient(),
    cap=None,
    log=log.append,
)
assert (
    not lenient["calibration"]["passed"]
    and lenient["calibration"]["defect"]["j"] == 0.0
)
held = lenient["scopes"]["held-out"]["metrics"]
assert (
    "withheld" in held["defects"]
    and "withheld" in held["regressions"]
    and "rates" in held["validity"]
)
assert not lenient["verdicts"]["fixed"]["pass"]

# The arithmetic: a change counts only beyond the baseline's own gap.
keys = [f"s/{n}" for n in range(20)]
arithmetic = {
    "items": [{"key": key, "scope": "held-out", "group": None} for key in keys]
}


def scored(rate):
    return {
        key: {"defects": float(index < rate * 20)} for index, key in enumerate(keys)
    }


scores = {
    "a": scored(0.5),
    "b": scored(0.4),
    "better": scored(0.1),
    "slight": scored(0.4),
    "worse": scored(0.8),
}
report = quality.compare_scores(
    arithmetic, scores, ["a", "b"], ["better", "slight", "worse"], judge_trusted=True
)
entry = report["held-out"]["metrics"]["defects"]
assert abs(entry["noise"]["gap"] + 0.1) < 1e-9, entry["noise"]
assert (
    abs(entry["changes"]["better"]["delta"] + 0.35) < 1e-9
    and entry["changes"]["better"]["gain"]
)
assert (
    not entry["changes"]["slight"]["gain"]
    and not entry["changes"]["slight"]["regression"]
)
assert (
    entry["changes"]["worse"]["regression"]
    and entry["changes"]["better"]["interval"][1] < 0
)
assert quality.verdict(report, "worse", judge_trusted=True)["reason"].startswith(
    "regression on the held-out half"
)
assert not quality.verdict(report, "better", judge_trusted=True)[
    "pass"
]  # no targeted items
# Baseline runs that disagree both ways have no mean gap but still a floor,
# which a change of one item does not pass.
crossed = {**scored(0.5), "s/0": {"defects": 0.0}, "s/19": {"defects": 1.0}}
scores = {"a": scored(0.5), "b": crossed, "one": scored(0.45)}
entry = quality.compare_scores(
    arithmetic, scores, ["a", "b"], ["one"], judge_trusted=True
)
entry = entry["held-out"]["metrics"]["defects"]
assert entry["noise"]["gap"] == 0.0 and entry["noise"]["floor"] > 0.05, entry["noise"]
assert not entry["changes"]["one"]["regression"] and not entry["changes"]["one"]["gain"]


# A request that keeps failing is retried once a call, never in a loop.
class Failing(Provider):
    def live(self, params):
        self.sent.append(params)
        raise RuntimeError("HTTP 400")


failing = Failing({})
status = quality.translate(
    loaded,
    guided,
    runs,
    "failing",
    transport=failing,
    cap=None,
    log=log.append,
    wait=True,
)
again = Failing({})
status = quality.translate(
    loaded,
    guided,
    runs,
    "failing",
    transport=again,
    cap=None,
    log=log.append,
    wait=True,
    retry_failed=True,
)
assert status["failed"] == status["requests"] and len(again.sent) == len(
    failing.sent
), status
print("ok")
