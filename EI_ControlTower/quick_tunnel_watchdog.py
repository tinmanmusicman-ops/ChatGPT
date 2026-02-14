import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable, List, Optional


URL_PATTERN = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com", re.IGNORECASE)
DEFAULT_GIT_COMMIT_MESSAGE_TEMPLATE = "Update tower configs to {url}"
DEFAULT_PHONEEVAL_PAGES_COMMIT_TEMPLATE = "Sync PhoneEval site ({url})"


def now_stamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def log(message: str) -> None:
    print(f"[{now_stamp()}] {message}", flush=True)


def normalize_url(url: str) -> str:
    return str(url or "").strip().rstrip("/")


def http_ok(url: str, timeout_seconds: float = 6.0) -> bool:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            code = int(getattr(response, "status", 0) or 0)
            return 200 <= code < 300
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError):
        return False


def resolve_cloudflared_path(explicit_path: str = "") -> Optional[str]:
    if explicit_path:
        explicit = Path(explicit_path)
        if explicit.exists():
            return str(explicit)
        found = shutil.which(explicit_path)
        if found:
            return found
        return None

    env_candidate = str(os.environ.get("HSST_CLOUDFLARED_PATH", "")).strip()
    if env_candidate:
        found_env = resolve_cloudflared_path(env_candidate)
        if found_env:
            return found_env

    candidates = [
        r"C:\Program Files\cloudflared\cloudflared.exe",
        r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
        "cloudflared",
    ]
    for candidate in candidates:
        found = resolve_cloudflared_path(candidate)
        if found:
            return found
    return None


def write_tower_config_files(config_paths: Iterable[Path], base_url: str) -> None:
    clean_url = normalize_url(base_url)
    payload = {"towerBaseUrl": clean_url}
    serialized = json.dumps(payload, indent=2) + "\n"

    for config_path in config_paths:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = config_path.with_name(f"{config_path.name}.tmp")
        temp_path.write_text(serialized, encoding="utf-8")
        temp_path.replace(config_path)
        log(f"updated config: {config_path} -> {clean_url}")


def read_config_tower_base(config_path: Path) -> str:
    try:
        if not config_path.exists():
            return ""
        data = json.loads(config_path.read_text(encoding="utf-8"))
        return normalize_url(str(data.get("towerBaseUrl", "")))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return ""


class QuickTunnelWatchdog:
    def __init__(
        self,
        *,
        cloudflared_path: str,
        origin_url: str,
        config_paths: list[Path],
        check_interval_seconds: float,
        failure_threshold: int,
        startup_timeout_seconds: float,
        repo_root: Path,
        auto_git_push: bool,
        git_commit_message_template: str,
        git_remote: str,
        git_branch: Optional[str],
        pages_branch: str,
        pages_remote: str,
        pages_source_dir: str,
        pages_target_path: str,
        pages_commit_message_template: str,
        manage_tower: bool,
        tower_command: List[str],
        tower_cwd: Path,
    ) -> None:
        self.cloudflared_path = cloudflared_path
        self.origin_url = normalize_url(origin_url)
        self.origin_health_url = f"{self.origin_url}/health"
        self.config_paths = config_paths
        self.check_interval_seconds = max(check_interval_seconds, 1.0)
        self.failure_threshold = max(failure_threshold, 1)
        self.startup_timeout_seconds = max(startup_timeout_seconds, 5.0)

        self.repo_root = repo_root
        self.auto_git_push = auto_git_push
        self.git_commit_message_template = git_commit_message_template
        self.git_remote = git_remote
        self.git_branch = git_branch
        self.git_available = bool(self.auto_git_push and shutil.which("git"))
        if self.auto_git_push and not self.git_available:
            log("git executable not found; automatic config pushes disabled")
        self.pages_branch = pages_branch.strip()
        self.pages_remote = pages_remote.strip() or git_remote
        self.pages_source_dir = pages_source_dir.strip() or "PhoneEval"
        self.pages_target_path = pages_target_path.strip() or "."
        self.pages_commit_message_template = (
            pages_commit_message_template.strip() or DEFAULT_PHONEEVAL_PAGES_COMMIT_TEMPLATE
        )
        self.manage_tower = manage_tower and bool(tower_command)
        self.tower_command = list(tower_command) if tower_command else []
        self.tower_cwd = tower_cwd
        self.tower_process: Optional[subprocess.Popen[str]] = None

        self.current_tunnel_base_url = ""
        self.startup_deadline = 0.0
        self.consecutive_public_failures = 0

        self.process: Optional[subprocess.Popen[str]] = None
        self.reader_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.lock = threading.Lock()

    def _cloudflared_command(self) -> list[str]:
        return [
            self.cloudflared_path,
            "tunnel",
            "--url",
            self.origin_url,
            "--no-autoupdate",
        ]

    def _on_tunnel_url_found(self, discovered_url: str) -> None:
        with self.lock:
            normalized = normalize_url(discovered_url)
            if not normalized or normalized == self.current_tunnel_base_url:
                return
            self.current_tunnel_base_url = normalized
            self.consecutive_public_failures = 0
        log(f"tunnel url discovered: {normalized}")
        write_tower_config_files(self.config_paths, normalized)
        self._auto_push_configs(normalized)
        self._sync_phoneeval_pages_branch(normalized)
        self._restart_tower("new tunnel url discovered")

    def _configs_match_current_url(self, tunnel_base_url: str) -> bool:
        expected = normalize_url(tunnel_base_url)
        for path in self.config_paths:
            current = read_config_tower_base(path)
            if current != expected:
                return False
        return True

    def _relative_repo_path(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.repo_root))
        except ValueError:
            return str(path)

    def _config_relative_paths(self) -> List[str]:
        return [self._relative_repo_path(path) for path in self.config_paths]

    def _run_git_command(self, args: List[str]) -> Optional[subprocess.CompletedProcess[str]]:
        if not self.git_available:
            return None
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=str(self.repo_root),
                text=True,
                capture_output=True,
            )
        except OSError as exc:
            log(f"git command {' '.join(args)} failed: {exc}")
            self.git_available = False
            return None
        if result.returncode != 0:
            details = (result.stderr or result.stdout or "").strip()
            log(f"git {' '.join(args)} exited {result.returncode}: {details}")
        return result

    def _git_has_changes(self, rel_paths: List[str]) -> bool:
        if not rel_paths:
            return False
        result = self._run_git_command(["status", "--porcelain", "--", *rel_paths])
        if not result or result.returncode != 0:
            return False
        return bool(result.stdout.strip())

    def _format_commit_message(self, url: str) -> str:
        template = self.git_commit_message_template or DEFAULT_GIT_COMMIT_MESSAGE_TEMPLATE
        try:
            return template.format(url=url)
        except Exception as exc:
            fallback = DEFAULT_GIT_COMMIT_MESSAGE_TEMPLATE.format(url=url)
            log(f"git: invalid commit message template '{template}'; using fallback ('{fallback}'): {exc}")
            return fallback

    def _auto_push_configs(self, base_url: str) -> None:
        if not self.auto_git_push or not self.git_available:
            return
        rel_paths = [path for path in self._config_relative_paths() if path]
        if not rel_paths:
            return
        if not self._git_has_changes(rel_paths):
            log("git: tower config files already match repo; skipping push")
            return
        add_result = self._run_git_command(["add", "--", *rel_paths])
        if not add_result or add_result.returncode != 0:
            return
        commit_message = self._format_commit_message(base_url)
        commit_result = self._run_git_command(["commit", "-m", commit_message])
        if not commit_result or commit_result.returncode != 0:
            return
        target_ref = self.git_branch or "HEAD"
        push_result = self._run_git_command(["push", self.git_remote, target_ref])
        if not push_result or push_result.returncode != 0:
            return
        log(f"git: pushed config updates to {self.git_remote}/{target_ref}")

    def _sync_phoneeval_pages_branch(self, base_url: str) -> None:
        if not self.pages_branch:
            return
        script_path = self.repo_root / "PhoneEval" / "sync_phoneeval_pages.py"
        if not script_path.exists():
            log(f"pages sync script missing: {script_path}")
            return
        cmd = [
            sys.executable,
            str(script_path),
            "--branch",
            self.pages_branch,
            "--remote",
            self.pages_remote,
            "--source-dir",
            self.pages_source_dir,
            "--target-path",
            self.pages_target_path,
            "--base-url",
            normalize_url(base_url),
            "--commit-message",
            self.pages_commit_message_template,
        ]
        log(f"running PhoneEval pages sync for {self.pages_branch}")
        result = subprocess.run(cmd, cwd=str(self.repo_root), text=True, capture_output=True)
        if result.stdout:
            log(f"pages sync stdout: {result.stdout.strip()}")
        if result.stderr:
            log(f"pages sync stderr: {result.stderr.strip()}")
        if result.returncode != 0:
            log(f"pages sync process exited {result.returncode}")

    def _read_process_output(self) -> None:
        assert self.process is not None
        assert self.process.stdout is not None

        for raw_line in self.process.stdout:
            line = raw_line.rstrip("\r\n")
            if line:
                log(f"cloudflared: {line}")
                match = URL_PATTERN.search(line)
                if match:
                    self._on_tunnel_url_found(match.group(0))

        log("cloudflared output stream ended")

    def start_process(self) -> None:
        if self.process and self.process.poll() is None:
            return

        with self.lock:
            self.current_tunnel_base_url = ""
            self.consecutive_public_failures = 0
            self.startup_deadline = time.time() + self.startup_timeout_seconds

        command = self._cloudflared_command()
        log(f"starting tunnel: {' '.join(command)}")
        self.process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self.reader_thread = threading.Thread(target=self._read_process_output, daemon=True)
        self.reader_thread.start()

    def stop_process(self) -> None:
        process = self.process
        self.process = None
        if not process:
            return

        if process.poll() is None:
            log("stopping cloudflared process")
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                log("cloudflared did not exit in time; killing")
                process.kill()
                process.wait(timeout=5)

    def restart_process(self, reason: str) -> None:
        log(f"restarting tunnel: {reason}")
        self.stop_process()
        self.start_process()

    def start_tower(self) -> None:
        if not self.manage_tower or not self.tower_command:
            return
        if self.tower_process and self.tower_process.poll() is None:
            return
        log(f"starting tower: {' '.join(self.tower_command)} (cwd={self.tower_cwd})")
        try:
            self.tower_process = subprocess.Popen(
                self.tower_command,
                cwd=str(self.tower_cwd),
            )
        except OSError as exc:
            log(f"tower start failed: {exc}")
            self.tower_process = None

    def stop_tower(self) -> None:
        process = self.tower_process
        self.tower_process = None
        if not process:
            return

        if process.poll() is None:
            log("stopping tower process")
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                log("tower did not exit in time; killing")
                process.kill()
                process.wait(timeout=5)

    def _restart_tower(self, reason: str) -> None:
        if not self.manage_tower:
            return
        log(f"restarting tower: {reason}")
        self.stop_tower()
        self.start_tower()

    def run(self) -> int:
        if self.manage_tower:
            self.start_tower()
        self.start_process()

        while not self.stop_event.is_set():
            process_dead = self.process is None or self.process.poll() is not None
            if process_dead:
                self.start_process()
                time.sleep(self.check_interval_seconds)
                continue

            with self.lock:
                tunnel_base = self.current_tunnel_base_url
                startup_deadline = self.startup_deadline

            if not tunnel_base:
                if time.time() > startup_deadline:
                    self.restart_process("no trycloudflare url discovered within startup timeout")
                time.sleep(self.check_interval_seconds)
                continue

            public_health_url = f"{tunnel_base}/health"
            local_ok = http_ok(self.origin_health_url)
            public_ok = http_ok(public_health_url)

            if public_ok:
                if self.consecutive_public_failures:
                    log("public health recovered")
                self.consecutive_public_failures = 0
                if not self._configs_match_current_url(tunnel_base):
                    write_tower_config_files(self.config_paths, tunnel_base)
            else:
                if local_ok:
                    self.consecutive_public_failures += 1
                    log(
                        f"public health failed ({self.consecutive_public_failures}/{self.failure_threshold}) "
                        f"at {public_health_url}"
                    )
                    if self.consecutive_public_failures >= self.failure_threshold:
                        self.restart_process("public health failed while local origin is healthy")
                        continue
                else:
                    self.consecutive_public_failures = 0
                    log(
                        f"origin health failed at {self.origin_health_url}; "
                        "holding tunnel restart until origin recovers"
                    )

            time.sleep(self.check_interval_seconds)

        self.stop_process()
        self.stop_tower()
        return 0

    def request_stop(self) -> None:
        self.stop_event.set()


def parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    default_config_paths = [
        repo_root / "tower.config.json",
        repo_root / "AI-Fit-Site" / "tower.config.json",
        repo_root / "CORES" / "tower.config.json",
        repo_root / "PhoneEval" / "tower.config.json",
    ]

    parser = argparse.ArgumentParser(
        description=(
            "Keep a free Cloudflare Quick Tunnel running and keep tower.config.json files "
            "updated to the live trycloudflare URL."
        )
    )
    parser.add_argument("--cloudflared-path", default="", help="Path to cloudflared executable.")
    parser.add_argument("--origin-url", default="http://127.0.0.1:5000", help="Local origin URL.")
    parser.add_argument(
        "--config",
        dest="config_paths",
        action="append",
        default=[],
        help="Config file path to update. Can be repeated.",
    )
    parser.add_argument("--check-interval", type=float, default=15.0, help="Health check interval in seconds.")
    parser.add_argument(
        "--failure-threshold",
        type=int,
        default=3,
        help="Public-health failures before tunnel restart.",
    )
    parser.add_argument(
        "--startup-timeout",
        type=float,
        default=45.0,
        help="Seconds to wait for initial trycloudflare URL before restart.",
    )
    parser.add_argument(
        "--print-default-configs",
        action="store_true",
        help="Print default config paths and exit.",
    )
    parser.add_argument(
        "--skip-git-push",
        action="store_true",
        default=False,
        help="Do not automatically stage, commit, or push updated tower configs.",
    )
    parser.add_argument(
        "--git-commit-message",
        default=DEFAULT_GIT_COMMIT_MESSAGE_TEMPLATE,
        help="Commit message template for config updates (supports {url}).",
    )
    parser.add_argument(
        "--git-remote",
        default="origin",
        help="Remote to push config updates to.",
    )
    parser.add_argument(
        "--git-branch",
        default="",
        help="Git ref to push after committing config updates (defaults to HEAD).",
    )
    parser.add_argument(
        "--pages-branch",
        default="",
        help="Branch name where PhoneEval should be deployed (e.g., gh-pages).",
    )
    parser.add_argument(
        "--pages-remote",
        default="",
        help="Remote name used to push the PhoneEval branch (defaults to --git-remote).",
    )
    parser.add_argument(
        "--pages-source-dir",
        default="PhoneEval",
        help="Path to the PhoneEval source directory relative to the repo root.",
    )
    parser.add_argument(
        "--pages-target-path",
        default=".",
        help="Destination path inside the pages branch where PhoneEval is copied.",
    )
    parser.add_argument(
        "--pages-commit-message",
        default=DEFAULT_PHONEEVAL_PAGES_COMMIT_TEMPLATE,
        help="Commit message template for PhoneEval branch updates (supports {url}).",
    )
    parser.add_argument(
        "--skip-tower",
        action="store_true",
        default=False,
        help="Do not manage (start/restart/stop) the tower process.",
    )
    parser.add_argument(
        "--tower-command",
        nargs="+",
        default=["python", "tower.py"],
        help="Command used to run the tower (default: python tower.py).",
    )
    parser.add_argument(
        "--tower-cwd",
        default=str(script_dir),
        help="Working directory for the tower command.",
    )

    args = parser.parse_args()
    if not args.config_paths:
        args.config_paths = [str(path) for path in default_config_paths]
    if args.print_default_configs:
        for path in default_config_paths:
            print(path)
        sys.exit(0)
    return args


def main() -> int:
    args = parse_args()

    cloudflared_path = resolve_cloudflared_path(args.cloudflared_path)
    if not cloudflared_path:
        log("ERROR: cloudflared executable not found. Set --cloudflared-path or HSST_CLOUDFLARED_PATH.")
        return 2

    config_paths = [Path(path).resolve() for path in args.config_paths]
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    auto_git_push = not args.skip_git_push
    git_branch = args.git_branch.strip() or None
    tower_command = list(args.tower_command) if args.tower_command else []
    tower_cwd = Path(args.tower_cwd).resolve()
    manage_tower = not args.skip_tower
    watchdog = QuickTunnelWatchdog(
        cloudflared_path=cloudflared_path,
        origin_url=args.origin_url,
        config_paths=config_paths,
        check_interval_seconds=args.check_interval,
        failure_threshold=args.failure_threshold,
        startup_timeout_seconds=args.startup_timeout,
        repo_root=repo_root,
        auto_git_push=auto_git_push,
        git_commit_message_template=args.git_commit_message,
        git_remote=args.git_remote,
        git_branch=git_branch,
        pages_branch=args.pages_branch,
        pages_remote=args.pages_remote,
        pages_source_dir=args.pages_source_dir,
        pages_target_path=args.pages_target_path,
        pages_commit_message_template=args.pages_commit_message,
        manage_tower=manage_tower,
        tower_command=tower_command,
        tower_cwd=tower_cwd,
    )

    try:
        return watchdog.run()
    except KeyboardInterrupt:
        log("received interrupt; shutting down")
        watchdog.request_stop()
        watchdog.stop_process()
        watchdog.stop_tower()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
