<!-- The next release's notes; see docs/development.md#release-notes. -->

### Fixed

- **Translate:** the TOTAL at the end of a run's log now adds up every file in the run, including files translated before a resume. It repeated the last file's own cost, so a run that cost $2.22 could read $0.0237, or $0.0000 when the last files needed no requests.
