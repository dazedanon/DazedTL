<!-- The next release's notes; see docs/development.md#release-notes. -->

### Changed

- **Translate:** Claude Batches keep their repeated instructions for five minutes instead of an hour. A Batch sends most of its requests at once, so many of them pay to store the instructions instead of reusing them, and the five-minute kind costs 1.25 times the input price where the hour-long kind cost twice. A 48-request Database Batch that cost $2.11 would have cost about $1.49 with the same reuse.

### Fixed

- **Translate:** a file with nothing to translate, such as an empty **Troops.json**, reads **Done** instead of **Ready to apply** while a run works and **Applied** after it, though it was never applied. **Apply**, the Project page's files applied and the Check and Release notes about applied text no longer count it.
- **Translate:** a file whose Batch results could not be saved, for example after a canceled Batch, shows **0** saved lines instead of the lines the provider returned, and the Project page's lines translated no longer counts them.
- **Translate:** a file already applied no longer reads **Ready to apply** again after **Translate** finds no new requests for it.
- **Translate:** a Guided Batch no longer stops with "The file operation could not finish." once its cost estimate is done. Since 2.13.0 it happened on every Batch for a game whose earlier translations included text stored in game variables.
- **Translate:** Live translation no longer spends about two seconds starting up for every file, so a large game's run finishes many times faster: 972 map files took under 3 minutes instead of about 40. The app also stays responsive once a run has saved hundreds of files, where every screen update and **Stop** could wait about 10 seconds.
- **Translate:** a Claude Batch estimate is now a range, from every repeated instruction reused to none, instead of one figure that counted on reuse. A 48-request Database Batch estimated at $1.02 cost $2.11, which its new estimate of $1.68–$2.67 covers. The **Cost estimate** in Context, the Batch review and Assistant-led Batch estimates all show it, and an Assistant-led estimate's cost is the higher figure.
- **Translate:** run costs for Claude Opus 5.5 and Sonnet 5.5 count reused instructions at their real price, half of what DazedTL counted before, and a quarter for Fable 5.1.
- **Settings:** when the model catalog can't be loaded, **Built-in engine rates** for Claude Fable and Mythos are $10 and $50 per million tokens instead of $3 and $15, so their estimates no longer show under a third of the cost. Claude Opus 4.7 to 5.5 and Sonnet 5 and 5.5 also get their own prices instead of older models'.
