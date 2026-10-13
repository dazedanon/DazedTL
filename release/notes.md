<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Translate:** a file with nothing to translate, such as an empty **Troops.json**, reads **Done** instead of **Ready to apply** while a run works and **Applied** after it, though it was never applied. **Apply**, the Project page's files applied and the Check and Release notes about applied text no longer count it.
- **Translate:** a file whose Batch results could not be saved, for example after a canceled Batch, shows **0** saved lines instead of the lines the provider returned, and the Project page's lines translated no longer counts them.
- **Translate:** a file already applied no longer reads **Ready to apply** again after **Translate** finds no new requests for it.
