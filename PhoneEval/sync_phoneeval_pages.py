#!/usr/bin/env python3
"""Copy PhoneEval assets into the GitHub Pages branch and push the update."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_COMMIT_TEMPLATE = "Sync PhoneEval site ({url})"


def run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        text=True,
        capture_output=True,
    )


def ensure_branch_exists(repo_root: Path, branch: str, remote: str) -> bool:
    if run_git(["rev-parse", "--verify", branch], repo_root).returncode == 0:
        return True
    remote_ref = f"{remote}/{branch}"
    fetch_result = run_git(["fetch", remote, branch], repo_root)
    if fetch_result.returncode == 0:
        branch_result = run_git(["branch", branch, remote_ref], repo_root)
        return branch_result.returncode == 0
    branch_result = run_git(["branch", branch], repo_root)
    return branch_result.returncode == 0


def sanitized_subpath(value: str) -> Path:
    normalized = (value or "").strip()
    if not normalized or normalized in {".", "./"}:
        return Path(".")
    path = Path(normalized)
    if path.is_absolute():
        raise ValueError("target path must be relative")
    if any(part == ".." for part in path.parts):
        raise ValueError("target path must not escape repo root")
    return path


def copy_source(source_dir: Path, dest_root: Path) -> None:
    if not dest_root.exists():
        dest_root.mkdir(parents=True, exist_ok=True)
    for child in source_dir.iterdir():
        target = dest_root / child.name
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        if child.is_dir():
            shutil.copytree(child, target)
        else:
            shutil.copy2(child, target)


def clean_worktree(worktree_dir: Path) -> None:
    for child in list(worktree_dir.iterdir()):
        if child.name == ".git":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish PhoneEval to a GitHub Pages branch.")
    parser.add_argument("--branch", required=True, help="Branch to update (e.g., gh-pages).")
    parser.add_argument(
        "--remote",
        default="origin",
        help="Git remote for pushing the branch.",
    )
    parser.add_argument(
        "--source-dir",
        default="PhoneEval",
        help="Path to the PhoneEval source relative to the repo root.",
    )
    parser.add_argument(
        "--target-path",
        default=".",
        help="Relative path inside the branch where PhoneEval should live.",
    )
    parser.add_argument(
        "--commit-message",
        default=DEFAULT_COMMIT_TEMPLATE,
        help="Commit message template (supports {url}).",
    )
    parser.add_argument(
        "--base-url",
        default="",
        help="Optional tunnel URL used for commit messages.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parent.parent
    source_dir = (repo_root / args.source_dir).resolve()
    if not source_dir.exists():
        print(f"PhoneEval source not found: {source_dir}", file=sys.stderr)
        return 2

    branch = args.branch.strip()
    remote = args.remote.strip()
    if not branch:
        print("Branch name is required.", file=sys.stderr)
        return 2

    if not ensure_branch_exists(repo_root, branch, remote):
        print(f"Unable to prepare branch {branch}", file=sys.stderr)
        return 1

    worktree_dir = Path(tempfile.mkdtemp())
    try:
        add = run_git(["worktree", "add", "--detach", str(worktree_dir), branch], repo_root)
        if add.returncode != 0:
            print(f"Failed to add worktree: {add.stderr.strip()}", file=sys.stderr)
            return 1

        clean_worktree(worktree_dir)
        target_subpath = sanitized_subpath(args.target_path)
        deploy_root = worktree_dir if target_subpath == Path(".") else worktree_dir / target_subpath
        if deploy_root.exists():
            shutil.rmtree(deploy_root)
        deploy_root.mkdir(parents=True, exist_ok=True)
        copy_source(source_dir, deploy_root)

        status = run_git(["status", "--porcelain"], worktree_dir)
        if not status.stdout.strip():
            print("No changes to publish.", file=sys.stdout)
            return 0

        add_result = run_git(["add", "--all"], worktree_dir)
        if add_result.returncode != 0:
            print(f"git add failed: {add_result.stderr.strip()}", file=sys.stderr)
            return 1

        message = args.commit_message.format(url=args.base_url or "unknown")
        commit_result = run_git(["commit", "-m", message], worktree_dir)
        if commit_result.returncode != 0:
            print(f"git commit failed: {commit_result.stderr.strip()}", file=sys.stderr)
            return 1

        push = run_git(["push", remote, branch], worktree_dir)
        if push.returncode != 0:
            push = run_git(["push", "--set-upstream", remote, branch], worktree_dir)
            if push.returncode != 0:
                print(f"git push failed: {push.stderr.strip()}", file=sys.stderr)
                return 1

        print("PhoneEval pages branch updated.", file=sys.stdout)
        return 0
    finally:
        run_git(["worktree", "remove", "--force", str(worktree_dir)], repo_root)
        if worktree_dir.exists():
            shutil.rmtree(worktree_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
