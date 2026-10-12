<!-- The next release's notes; see docs/development.md#release-notes. -->

### Changed

- **Translate:** short RPG Maker MV/MZ event pages in maps, common events and troops now share requests instead of costing one each, and a longer page's choice menus go with its dialogue; on a 970-map game a Maps & events estimate fell from 4,089 to 2,173 requests and from 23.5 to 14.0 million input tokens. Runs started before the update keep their old requests.
- **Assistant-led:** API runs cost less: lines go to the model by number instead of by their long names, estimates count tokens the way Guided does, and a scene longer than 10 lines gets its own request. On a large test game input fell from 22.5 to 17.6 million tokens and output from 9.1 to 7.2 million. Runs started before the update keep their old requests.
- **Assistant-led:** when your assistant saves an RPG Maker message one line at a time, preparing requests stops and asks it to save whole messages, which otherwise multiplies requests and cuts sentences apart.
- **Translate:** the run inspector shows a run's requests 100 at a time, with Previous and Next beside the picker.

### Fixed

- **Assistant-led:** approving an API estimate for a very large game no longer stops with "Choose a regular JSON file within the supported size limit."
- **Assistant-led:** the app no longer freezes, or reports that it stopped responding, while your assistant prepares requests for a big game; Estimate and Compile show their progress beside the button.
- **Assistant-led:** large Batch runs save their results much faster (about 30 seconds down to 5 for 2,600 requests) and use far less memory and disk while a retry of refused requests waits.
- **Assistant-led:** Cancel while a retry of refused requests waits now cancels that retry and keeps everything already finished; a canceled run no longer reads "The provider batch failed." or leaves its later parts waiting, and parts never sent read "Not sent".
- **Assistant-led:** animation and tileset names, which players never see, no longer have to be extracted and paid for before a complete estimate.
- **Translate:** preparing a Batch on Windows no longer fails with "PermissionError: manual run failed" or "[WinError 32]".
- **Translate:** the app answers faster while a large Batch run is open; on a 1,500-map game each refresh at the Batch review went from about 1 second to half that, and the review opens in about 2 seconds instead of 5.
- **Translate:** "Saved process evidence is unavailable" no longer flashes while a Batch collects its results, and a submission that may not have reached the provider reads as unconfirmed instead of "This request has not been sent."
- **Project:** a running Assistant-led step shows once instead of twice.
