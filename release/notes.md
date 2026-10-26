<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Context:** a failed **Save context** shows its reason beside the button, and it and any other failed file write now name the file and why (for example that it is read-only), and a leftover Git lock says another Git process is using the game instead of "The operation could not finish."
- **Inspect:** in **File contents**, every line after a message of more than one row showed beside another line's source text; each message now shows as one line beside its own source.
- **Playtest tools:** installing or removing TL Inspector or Forge no longer says so twice or makes the window jump.
- **Forge:** quick load (Ctrl+Q) no longer crashes some games with an error screen right after loading, such as "Cannot read properties of undefined (reading 'massCharacters')".
- **Settings:** a successful **Check connection** no longer repeats its result beside the button.
- **Translate:** a long Live run no longer makes DazedTL use more memory with every request it saves; a run of a few thousand requests could take over a gigabyte while it ran.
- **Translate:** on a game with more than about a thousand maps, the variables step no longer rereads every map each second, which kept the app busy and slow.
- **GameUpdate:** a game translated into Japanese shows players its "Translation update available" message in Japanese; Set up writes the text into the update check's plugin settings, where it can be edited.
- **Images:** **Compare images** no longer names what discovery found an image to be twice, such as "Recommended" beside its state and again under Discovery.
- **Translate:** a stopped Batch that had nothing new to send for a file no longer kept Other event text open while every file read **Applied**, and the file's Lines show the run that translated it.
- **Set up:** while DazedTL saves a newly opened game's original files, a change that has to wait for them shows how far the save has got beside its button, with **Stop**, instead of a message to try again later.
