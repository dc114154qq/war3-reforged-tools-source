# Version Source Map

The source archive was assembled from the existing local Git tags and the current source worktree. It includes source-only snapshots for these tags:

- Trainer history: `v0.2.0` through `v0.2.12`, `v0.25`, `v1.0.0` through `v1.0.19`, `v2.0.0` through `v2.0.9`, and `v2.1.0-beta`.
- Hotkey history: `hotkeys-v1.0.0` and `hotkeys-v1.0.1`.

The root files include the current source overlay for the trainer, hotkey tool, selection-limit tool, native helper sources, current profile data, tests, and build specifications. Historical snapshots retain only source/configuration files and the required icon assets. They do not include packaged binaries or diagnostics.

The source tree is not a release artifact. To publish a build, use the matching specification and record the source commit, game build fingerprint, adapter/profile version, bridge ABI, file hashes, and verification gaps separately.

