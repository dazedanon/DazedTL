# Direct translation and efficient context preparation

Use this for Assistant only translation and local request compilation in every mode.
Direct work runs through the coding assistant's existing access; no DazedTL provider client, API key or hosted image generation is needed.
The user's instructions determine whether other agents may participate.
Translation mode never overrides a request to work alone.

## Establish the work units once

Use occurrence IDs tied to file/scene/field and retain source, speaker, surrounding source context and translation provenance.
Do not deduplicate dialogue globally by Japanese text alone: the same line can require different voice, gender or meaning.
UI terms can share an accepted decision when their meaning and rendering constraints match.
Maintain a source census independent of the extractor; a successful extraction loop does not prove completeness.
Keep unknown fields and unresolved source readings in an explicit ledger; DazedTL's census, not the extractor, decides what is in scope.

As a starting point, group about 200–300 short units by scene/speaker continuity, adapting down for long passages, dense controls or context/output limits.
Use smaller batches after a validation failure, and increase only when the measured result remains reliable.
Do not split a scene merely to hit a fixed batch size.
Translate names and terminology before dependent dialogue when that prevents repeated revision.

## Organize the extracted lines without rewriting them

Under DazedTL's project helper, the extractor saves every line in scope as source units, and `organize` groups them into requests and compiles the run.
Run the helper's `units-format` for the file's shape: stable occurrence IDs the injector maps back, scene and group keys in play order, kinds, evidenced speakers or null, literal protected tokens and layout bounds.
Move game text only with scripts; never paste, retype or summarize the Japanese or its translation in replies or hand-written files.

```bash
<helper> organize --input .dazedtl/len-method/work/source-units.json --complete
```

Run the helper's `census` first; `--complete` is accepted only once the units cover everything it counted, and API estimates require it.
When organize names text that isn't extracted, fix the extractor using the locations in `.dazedtl/len-method/work/census-uncovered.json`; set aside text players never see only with game-wide field rules in `.dazedtl/len-method/work/scope-rules.json`.
The reply holds counts only, and errors name unit IDs, so fix the extractor and organize again.
Organize packs whole scenes of one group up to the model's entries per request, splits larger scenes with their earlier lines as context, and binds the run to the units file.
Every request carries the full system, glossary, SFX, field instructions, preceding source context, speaker-bearing `user` payload and advisory reference translations.
In Assistant only, read each request with the helper, translate it, and save its receipt with `accept`; decline a request you won't translate rather than softening or leaving out lines.
`results --run ID` writes the accepted translations by unit ID for the injector.

## Save small results; validate at the right scale

Apply the shared source-checked dialogue pass before saving a batch. At cross-batch checkpoints,
read split exchanges together so reply continuity and voice survive the batch boundary.

After each batch, save accepted outputs atomically and check IDs, untranslated/empty results, placeholder multisets, protected codes and local layout bounds.
Do not recompute the whole source/reference census or run every global rendering check merely because another small batch finished.
As a starting point, perform a cross-batch review and checkpoint after roughly 1,000–1,500 units, or sooner when a glossary decision, renderer, extractor, control-code handling or source scope changes.
Run the complete structural/coverage checks at the final milestone and whenever a change invalidates their assumptions.
Use incremental validation only when the validator can identify its affected dependency set.

Cache validation evidence by source/output, glossary/context, validator version, renderer/font and target-build fingerprints as applicable.
Reuse an unchanged check's actual saved evidence; never manufacture a source/review fingerprint just to reuse an output.
If any relevant dependency changes, invalidate the affected downstream checks and report them pending until rerun.
For MV/MZ, all final writes still pass through `write-rpgmaker-json`; an external store or faster injector does not replace `_original` preservation.
Keep the same original command structure and save identity unless an explicitly validated adapter provides the required mapping.

Update the GUI and the user using `progress-reporting.md` at every saved milestone and at least every 10 minutes.
Before a long wait or QA segment, state the remaining scope, estimate basis and next visible checkpoint.
Use targeted native checks for changed behavior; do not turn an ordinary translation follow-up into an unrequested full playthrough.
