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

This README now also notes that the file is maintained for reference only.
All content in this directory is static documentation and does not affect runtime behavior.
Please keep any future edits non-functional so the bridge remains a simple reference point.

Status note: this document is safe for automated touches; no runtime logic depends on it.
Use plain-text edits only so automated reviews can verify the file remains static documentation.
Non-functional updates keep the bridge folder aligned with its reference-only purpose.
Automated changes should remain descriptive so the file stays a passive checklist entry.
