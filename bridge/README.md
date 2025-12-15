# Bridge assets

This folder holds collaboration handoff files. The current codebase overview lives in [`codebase_overview.md`](./codebase_overview.md).

## Where the files live right now
- Folder name: lowercase `bridge/` at the repository root (next to `ai-bots/` and `EI_ControlTower/`).
- Current branch carrying the files: **`work`** (this is the branch you are on if `git status -sb` prints `## work`). There is no `develop` branch here.
- Git remote: none configured (`git remote -v` returns nothing). Until you add a remote and push, the bridge markdown files exist only in this local repository.

If you only see a placeholder like `test.txt` on GitHub, it means the branch with these files has not been pushed anywhere yet. Add a remote and push the `work` branch to make them appear online:

```bash
git remote add origin <git@github.com:your-account/ChatGPT.git>
git push -u origin work
```

## Quick verification commands
These commands confirm the repository, branch, remotes, and the presence of the bridge files.

```bash
# Confirm repository root and current branch
git rev-parse --show-toplevel
git rev-parse --abbrev-ref HEAD

# Check configured remotes (expect none until you add one)
git remote -v

# Confirm the working tree is clean and the bridge files are tracked
git status -sb
git status --porcelain=v1 --untracked-files=all --ignored=matching -- bridge

# Ensure the files are not ignored
git check-ignore -v -- bridge/README.md
git check-ignore -v -- bridge/codebase_overview.md

# See when the files were committed
git log --all --name-status -- bridge/README.md
git log --all --name-status -- bridge/codebase_overview.md

# If you add a remote, fetch branches and inspect them
git fetch --all --prune
git branch -av
```

### Current outputs (from this workspace)
For reference, here is what the commands above return in this checkout:

```
$ git rev-parse --show-toplevel
/workspace/ChatGPT

$ git status -sb
## work

$ git remote -v
(no output; no remotes configured)

$ git log -1 --name-status
commit 79122b4e4652e838b77999954fa2a901cab45f9a (HEAD -> work)
Author: Codex <codex@openai.com>
Date:   Mon Dec 15 08:50:14 2025 +0000

    Clarify bridge branch and verification steps

    ## Summary
    - update bridge README to reflect the actual local `work` branch, no configured remote, and include verification commands
    - revise repository overview to note bridge files live on `work` and must be pushed after adding a remote

    ## Testing
    - not run (documentation-only change)

A       bridge/README.md
A       bridge/codebase_overview.md

$ git ls-files -- bridge/README.md
bridge/README.md
```

## Viewing the files directly
You can inspect the committed versions without switching branches:

```bash
git show work:bridge/README.md
git show work:bridge/codebase_overview.md
```

## Current contents of `bridge/`
- `README.md` (this sync and verification guide)
- `codebase_overview.md` (codebase orientation and repository map)

If the files still do not appear locally, make sure you are in the repository root (`/workspace/ChatGPT`) and that `git status` shows you are on the `work` branch.
