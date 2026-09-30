# Migration record

Historical reference for the initial migration on 2026-09-30; see [README](../README.md) for current scope.

The sibling DazedMTLTool checkout and its uncommitted work were preserved before creating DazedTL.
The local `.git/migration-reference/` checkpoint holds its binary Git diff, changed/untracked source and build files, and a hash manifest.
[migration-reference.json](migration-reference.json) records the source commit and inventory.
The checkpoint excludes credentials, games, workspaces, and dependency caches, and is not included in clones of this repository.

The initial application reused the existing backend through a compatibility adapter and was built and visually reviewed without running tests or provider translations.
The first DazedTL checkpoint is `645b0b8` on `codex/foundation`.
