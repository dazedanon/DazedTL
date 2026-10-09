# Scope decisions and their reversals

Scope is mechanical.
DazedTL's census counts every piece of Japanese text in the original game, and `organize --complete` requires all of it extracted or set aside by a field rule.
Never remove text from scope because of its content, whether a line, a scene, a map, an event or a character's material.
If you won't translate a request, decline it: its lines stay counted and visible on Progress, and the user decides who translates them.
Use this reference when a user disputes a decision, a later review contradicts an earlier one, or a resumed task finds an older exclusion list.

## Dispositions

Only these keep Japanese out of the translated game:

- Text players never see, such as engine identifiers, asset file names, comments and script code, set aside by a field rule that applies across the whole game; rules work only for engine data, scenarios and code DazedTL reads itself, so everything in a decoded dump is extracted.
- Omissions the user approved, recorded with their words.
- Unresolved extraction: text the extractor can't reach yet, reported as a defect to fix, not as a decision.

An older exclusion list built on content judgments is not a disposition; put that text back in scope.
A parser or error message is not automatically an internal identifier: trace its consumer and report whether the player can see it.
Translate player-visible diagnostics, preserving formatting arguments and technical keys.
A shared short label can have unrelated uses elsewhere; inspect exact occurrences instead of suppressing Japanese text globally.

## Age and identity evidence in the translation

Distinguish source facts, user-provided context and your interpretation, and record exact source locations with the wording a decision rests on.
Keep confirmed age/adulthood lore separate from art style, short stature, youthful wording, sibling roles and ambiguous labels such as “girl”, "boy", "child", etc.
Cartoony, chibi, super-deformed and low-resolution sprite designs are not age categories.
Features shared across the art style, including large heads, simplified faces and small bodies, do not by themselves establish a minor identity.
Interpret age-related wording in its full context, including whether an older speaker is speaking comparatively; do not invent a numerical age from an ambiguous label alone.
Do not repeatedly reopen the same question for unchanged characters merely because another stylized image or the same ambiguous wording appears.
Do not invent ages, age characters up or change characterization in the translation.

## Preserve corrections across resume and reinjection

Keep a short current decision record with source bindings, rationale, scope, date and links to the review it supersedes.
Archive the previous decision rather than deleting its history.
Check the current record on resume, before changing scope rules and before injection; a stale list must not silently override a later reviewed correction.
When a decision changes, reconcile scope rules, injection, QA allowlists, progress denominators and delivery notes together.
Keep historical accepted translations intact so a mistaken omission can be reversed without retranslating or reconstructing source.
Restoring a line does not by itself validate an old translation: check its source, context, placeholders, speaker association and current layout before restoring it to the game.

## Make remaining Japanese visible to the user

Show a compact summary at milestones and delivery: translated and reviewed units, declined lines, text set aside by each rule, user-approved omissions, unresolved extraction and accepted artwork exceptions.
State the counting unit; logical dialogue blocks and native displayed lines are not interchangeable.
Put material omission counts and reasons in the main progress and handoff summary, not only in a long local ledger.
Do not report a fully translated game while declined lines or unresolved extraction remain.
