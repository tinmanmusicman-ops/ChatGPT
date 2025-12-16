# Bridge assets

This folder holds collaboration handoff files. The current codebase overview lives in [`codebase_overview.md`](./codebase_overview.md).

## Where the files live
- Folder name: lowercase `bridge/` at the repository root (next to `ai-bots/` and `EI_ControlTower/`).
- Branch carrying these files: `develop`.
- Files:
  - `bridge/README.md`
  - `bridge/codebase_overview.md`

## Quick verification commands

```bash
# Confirm repository root and current branch
git rev-parse --show-toplevel
git rev-parse --abbrev-ref HEAD

# Check configured remotes (expect an `origin` for GitHub)
git remote -v

# Confirm the bridge files are tracked and not ignored
git ls-files -- bridge/README.md bridge/codebase_overview.md
git check-ignore -v -- bridge/README.md
git check-ignore -v -- bridge/codebase_overview.md

# See when the files were committed
git log --name-status -- bridge/README.md
git log --name-status -- bridge/codebase_overview.md
```

## Sync from GitHub

```bash
git fetch origin
git checkout develop
git pull --ff-only origin develop
ls bridge
```

## Troubleshooting
- On GitHub, confirm the branch selector is set to `develop` when browsing `bridge/`.
- If you are using a fork, replace `origin` with your fork remote name in the commands above.
Codex handshake verification — static test run.
Codex handshake verification — static test run.
