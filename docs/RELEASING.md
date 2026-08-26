# Releasing Pinchana API

`VERSION` uses `YY.MM.ITERATION`. Python packages use the equivalent PEP 440
version (`26.08.8` -> `26.8.8`).

## Normal release

Run from the parent `pinchana-api` checkout with `git`, `uv`, and `gh`
installed/authenticated:

```bash
python scripts/version.py bump --publish -n "Describe the release here"
```

`version.py bump` now performs the complete release-version synchronization:

1. Requires a clean parent worktree and clean submodule worktrees.
2. Runs `git submodule sync --recursive` and initializes all submodules.
3. Fetches every submodule's `origin` default branch. A stale parent pin is
   fast-forwarded to the remote head; an ahead pin is preserved; divergent
   history aborts the release.
4. Updates `VERSION`, every root submodule `pyproject.toml`, and every matching
   `uv.lock`.
5. Commits the version changes in each affected submodule.
6. Pushes every submodule HEAD to its default remote branch so every parent pin
   is remotely reachable.
7. Commits the new `VERSION` plus all submodule pointers in the parent repo and
   pushes the parent branch.
8. With `--publish`, creates the matching annotated local tag, pushes it, and
   creates a GitHub Release through `gh`. The tag push triggers the Docker
   release workflow.

Use a description file for multiline notes:

```bash
python scripts/version.py bump --publish -F RELEASE_NOTES.md
```

Set an explicit version instead of incrementing it:

```bash
python scripts/version.py set 26.08.8 --publish -n "Release notes"
```

For the old metadata-only behavior without git synchronization, commits, or
pushes:

```bash
python scripts/version.py bump --local-only
```

## Publish an already-created local tag

If the version commit is already prepared and the matching tag already exists
locally, use:

```bash
python scripts/publish_release.py -n "Describe the release here"
```

The publisher refuses to continue unless:

- the worktree is clean;
- submodules exactly match the parent pins;
- `python scripts/version.py check --tag v<VERSION>` succeeds;
- the matching local tag exists and points at the current `HEAD`.

It then pushes the current branch, pushes that existing local tag, and creates
(or updates) the GitHub Release via `gh`.

If the tag was created locally *before* the final parent/submodule release
commit, repair the version first and explicitly move that unpushed local tag:

```bash
python scripts/version.py set 26.08.7
python scripts/publish_release.py --retag -n "Threads and X fixes"
```

`--retag` refuses to move a tag that already exists on `origin`, so an already
published release tag can never be rewritten accidentally.

Examples:

```bash
python scripts/publish_release.py -F RELEASE_NOTES.md
python scripts/publish_release.py --title "Pinchana 26.08.8" -n "Threads and X fixes"
python scripts/publish_release.py --draft -F RELEASE_NOTES.md
```

If no description is provided for a new GitHub Release, `gh --generate-notes`
is used.
