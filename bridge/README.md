# Bridge assets

This folder holds collaboration handoff files. The current codebase overview lives in [`codebase_overview.md`](./codebase_overview.md).

You should see this folder at the repository root as `bridge/` (next to `ai-bots/` and `EI_ControlTower/`). On GitHub, the path is `bridge/` in the branch that carries these files—double-check the spelling (it is **not** `branch/`). If you only see a placeholder like `test.txt`, you are probably on a different branch or an outdated snapshot. Switch to the branch that contains the bridge docs: **`develop`**.

**Exact save location:** both handoff files are committed under `bridge/` at the repository root on the `develop` branch:

- `bridge/README.md`
- `bridge/codebase_overview.md`

You can verify they exist in the remote branch without switching branches by running:

```bash
git show origin/develop:bridge/README.md
git show origin/develop:bridge/codebase_overview.md
```

To update your local copy from this repository root:

```bash
git fetch origin
# Verify the branch exists remotely
git ls-remote --heads origin develop
# Switch to the branch with the bridge files
git checkout develop
# Pull the latest changes
git pull origin develop
# Confirm the files are present (expect README.md and codebase_overview.md)
ls bridge
cat bridge/codebase_overview.md
```

Current contents of this `bridge/` folder on `develop` (what you should see on GitHub and locally after pulling):

- `README.md` (this sync guide)
- `codebase_overview.md` (codebase orientation and repository map)

If those files do not appear on GitHub after selecting `develop` and opening `bridge/`, refresh the page and confirm the branch selector shows `develop`. The `test.txt` file is not part of this handoff; seeing only that file means the branch view is still pointed elsewhere.

Quick sanity checks if the folder is still missing:

- Run `git status -sb` to confirm the branch you are on matches the commands above (it should show `## develop`).
- Verify the remote is set with `git remote -v`; if it points somewhere unexpected, update it or clone fresh.
- If you are using a fork, replace `origin` with your fork remote name in the commands above.

If you still do not see the files locally:

- Make sure you are in the repository root (the folder that contains `bridge/`).
- Run `git status` to confirm you are on the expected branch and there are no uncommitted changes preventing a clean pull.
- If the `develop` branch is missing locally, run `git checkout -b develop origin/develop` after fetching.
- If your local branch name differs, substitute it in the commands above, or run `git branch -a` to see available branches.
- As a last resort, clone a fresh copy of the repository to ensure the `bridge/` directory syncs correctly.

If you are browsing the repo directly in your environment, these files already live under `bridge/` alongside the main automation projects.
