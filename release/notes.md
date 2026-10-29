<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Translate:** a file that fails after some of its requests were answered, such as on a later request's error or a missing Batch result, now keeps what those requests cost in its cost and the run's total, which left them out.
- **Translate:** a WOLF map whose request fails partway now shows as failed with what it paid for, keeping only the pages that finished, instead of being written with the failing page's lines half translated and counted as complete.
- **Translate:** a WOLF map or common event file now asks once for each choice, choice window and speaker name, instead of paying again to translate its own translation when the text still read as Japanese, such as Chinese; its line now shows the tokens it used, which counted a speaker's input as output and left out those second requests.
