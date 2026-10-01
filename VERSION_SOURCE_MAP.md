# Version Source Map

The source archive was assembled from the existing local Git tags and the current source worktree. The names below are **tool versions**, not game versions.

## Tool Versions

- Trainer history: `v0.2.0` through `v0.2.12`, `v0.25`, `v1.0.0` through `v1.0.19`, `v2.0.0` through `v2.0.9`, and `v2.1.0-beta`.
- Hotkey history: `hotkeys-v1.0.0` and `hotkeys-v1.0.1`.
- Current combined source snapshot: `versions/current-20261001/`. This includes the latest trainer source overlay, the latest hotkey source and adapter/transport changes, the selection-limit tool source, native source inputs, build specifications, tests, and current profile data from the worktree used for this publication.

The root files include the current source overlay for the trainer, hotkey tool, selection-limit tool, native helper sources, current profile data, tests, and build specifications. The `current-20261001` snapshot is the explicit copy of that latest source set. Historical snapshots retain only source/configuration files and the required icon assets. They do not include packaged binaries or diagnostics.

## Game Build Profiles

These are compatibility data, not tool releases:

- Trainer profiles: `profiles/3.0.0.24268.json` and `profiles/3.0.1.24323.json`.
- Hotkey profile: `hotkey_profiles/3.0.0.24268.json`.

A game build update may require a profile or adapter change without changing the trainer's own version number.

The source tree is not a release artifact. To publish a build, use the matching specification and record the source commit, game build fingerprint, adapter/profile version, bridge ABI, file hashes, and verification gaps separately.
