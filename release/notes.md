<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Translate:** a file that fails after some of its requests were answered, such as on a later request's error or a missing Batch result, now keeps what those requests cost in its cost and the run's total, which left them out.
- **Translate:** a file that failed in one attempt and was translated in a later one now counts what both attempts cost in its cost and the run's total, which kept only the later attempt's.
- **Translate:** an RPG Maker file that could not be saved after some lines kept their original text now reads as failed, which counted it as finished with mismatches.
- **Translate:** a WOLF map or common event file now asks once for each choice, choice window and speaker name, instead of paying again to translate its own translation when the text still read as Japanese, such as Chinese; its line now shows the tokens it used, which counted a speaker's input as output and left out those second requests.
- **Translate:** a server that refuses the run's thinking effort with HTTP 422, or by saying the model takes no reasoning or thinking, now stops a Guided Live run at the first refused request with "refused thinking effort", as **Check an effort** reads such a reply, instead of after three requests with "The provider rejected 3 requests in a row"; a Guided Batch the provider refused for its effort ends with the same message instead of "No successful Batch responses".
- **Settings:** a thinking effort that **Check an effort** accepted now reads refused after a Guided Batch the server refused it in, and after an Assistant-led run that it refused while DazedTL was closed, not only after a Live run.
- **Translate:** a WOLF map whose request fails partway now shows as failed with what it paid for and keeps the map's earlier translation as it was, instead of being written with the failing page's lines half translated and counted as complete, or replacing a complete earlier translation with the pages that finished.
- **Translate:** a WOLF choice window's question is now asked for in the target language, where its request read "{LANGUAGE}", and a 選択肢/確認 window without a question, or a common event or database whose text holds `'events':` or `'types':`, no longer fails its file.
