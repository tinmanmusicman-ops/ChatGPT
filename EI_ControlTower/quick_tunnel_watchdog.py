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
from typing import Iterable, Optional


URL_PATTERN = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com", re.IGNORECASE)


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
    ) -> None:
        self.cloudflared_path = cloudflared_path
        self.origin_url = normalize_url(origin_url)
        self.origin_health_url = f"{self.origin_url}/health"
        self.config_paths = config_paths
        self.check_interval_seconds = max(check_interval_seconds, 1.0)
        self.failure_threshold = max(failure_threshold, 1)
        self.startup_timeout_seconds = max(startup_timeout_seconds, 5.0)

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

    def _configs_match_current_url(self, tunnel_base_url: str) -> bool:
        expected = normalize_url(tunnel_base_url)
        for path in self.config_paths:
            current = read_config_tower_base(path)
            if current != expected:
                return False
        return True

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

    def run(self) -> int:
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
    watchdog = QuickTunnelWatchdog(
        cloudflared_path=cloudflared_path,
        origin_url=args.origin_url,
        config_paths=config_paths,
        check_interval_seconds=args.check_interval,
        failure_threshold=args.failure_threshold,
        startup_timeout_seconds=args.startup_timeout,
    )

    try:
        return watchdog.run()
    except KeyboardInterrupt:
        log("received interrupt; shutting down")
        watchdog.request_stop()
        watchdog.stop_process()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
