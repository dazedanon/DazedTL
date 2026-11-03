<!-- The next release's notes; see docs/development.md#release-notes. -->

### Changed

- **Release:** an Assistant-led patch ZIP no longer waits for your assistant's QA or translation to finish: its review lists what's left, and **Build anyway** saves it.

### Fixed

- **Release:** a progress report the assistant's project helper refused ("The current phase must be active or blocked.") no longer stops every patch ZIP with that message, or leaves "Saved records or source inputs need rechecking" behind; the refusal now tells the assistant to leave the phase out once every phase is done.
