<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Translate:** a line whose translation keeps a single kana or mark from the Japanese, such as the 〇 of a censored word or a kaomoji's ﾉ, no longer leaves its file at **Needs review** with "1 line never translated. Translate sends it" while the next Batch finds "No new translation requests"; such lines now count as translated, and a line the model gives back unchanged is still sent again.
