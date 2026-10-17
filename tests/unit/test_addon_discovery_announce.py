"""Tests for the add-on's Supervisor discovery announce (docker/addon/discovery_announce.sh, design D13).

The script runs against a local HTTP server that plays both hassette (``/api/health/live``) and Supervisor
(``/discovery``), so the order of its requests and what it posts are observed directly.
"""

import json
import os
import socket
import subprocess
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ANNOUNCE_SH = REPO_ROOT / "docker" / "addon" / "discovery_announce.sh"
ADDON_RUN_SH = REPO_ROOT / "docker" / "addon" / "run.sh"
SUPERVISOR_TOKEN = "supervisor-token"
SCRIPT_TIMEOUT_SECS = 30


@dataclass
class FakeAddonHost:
    """What the fake hassette + Supervisor server saw, and how it answers."""

    # Called on each liveness probe with the probe's 1-based count; returns the HTTP status to answer with.
    live_status: Callable[[int], int] = lambda _count: 200
    discovery_status: int = 200
    events: list[str] = field(default_factory=list)
    discovery_posts: list[tuple[dict[str, str], dict]] = field(default_factory=list)
    port: int = 0


@pytest.fixture
def addon_host() -> Iterator[FakeAddonHost]:
    host = FakeAddonHost()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path != "/api/health/live":
                self.send_error(404)
                return
            host.events.append("live")
            self.send_response(host.live_status(host.events.count("live")))
            self.end_headers()

        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers["Content-Length"]))
            host.events.append("discovery")
            host.discovery_posts.append((dict(self.headers), json.loads(body)))
            self.send_response(host.discovery_status)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    host.port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield host
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def run_announce(host: FakeAddonHost, token_file: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(ANNOUNCE_SH), f"http://127.0.0.1:{host.port}", str(host.port), str(token_file)],
        env={**os.environ, "SUPERVISOR_TOKEN": SUPERVISOR_TOKEN},
        capture_output=True,
        text=True,
        timeout=SCRIPT_TIMEOUT_SECS,
        check=False,
    )


def test_announces_only_after_hassette_serves(addon_host: FakeAddonHost, tmp_path: Path) -> None:
    """The announce waits for /api/health/live and reads the token file only then, the way hassette writes
    it just before serving.
    """
    token_file = tmp_path / ".web_api_token"

    def live_on_second_probe(count: int) -> int:
        if count == 1:
            return 503
        token_file.write_text("served-token\n", encoding="utf-8")
        return 200

    addon_host.live_status = live_on_second_probe

    result = run_announce(addon_host, token_file)

    assert result.returncode == 0, result.stdout + result.stderr
    assert addon_host.events == ["live", "live", "discovery"]
    headers, payload = addon_host.discovery_posts[0]
    assert headers["Authorization"] == f"Bearer {SUPERVISOR_TOKEN}"
    assert payload == {
        "service": "hassette",
        "config": {"host": socket.gethostname(), "port": addon_host.port, "auth_token": "served-token"},
    }


def test_a_rotated_token_is_announced(addon_host: FakeAddonHost, tmp_path: Path) -> None:
    token_file = tmp_path / ".web_api_token"
    for token in ("old-token", "rotated-token"):
        token_file.write_text(token, encoding="utf-8")
        assert run_announce(addon_host, token_file).returncode == 0

    assert [payload["config"]["auth_token"] for _, payload in addon_host.discovery_posts] == [
        "old-token",
        "rotated-token",
    ]


def test_a_rejected_post_is_logged_and_exits_cleanly(addon_host: FakeAddonHost, tmp_path: Path) -> None:
    token_file = tmp_path / ".web_api_token"
    token_file.write_text("served-token", encoding="utf-8")
    addon_host.discovery_status = 500

    result = run_announce(addon_host, token_file)

    assert result.returncode == 0
    assert "WARNING: couldn't announce hassette" in result.stdout
    assert "500" in result.stdout


def test_a_missing_token_file_is_logged_and_skips_the_post(addon_host: FakeAddonHost, tmp_path: Path) -> None:
    token_file = tmp_path / ".web_api_token"

    result = run_announce(addon_host, token_file)

    assert result.returncode == 0
    assert f"WARNING: couldn't announce hassette to Home Assistant (reading {token_file} failed)" in result.stdout
    assert addon_host.discovery_posts == []


def test_run_sh_starts_the_announce_in_the_background_before_handing_off() -> None:
    script = ADDON_RUN_SH.read_text(encoding="utf-8")
    start = script.index("/app/docker/addon/discovery_announce.sh")
    handoff = script.index("exec /app/scripts/docker_start.sh")

    assert start < handoff
    assert script[start:handoff].rstrip().endswith("&")
    assert os.access(ANNOUNCE_SH, os.X_OK), "run.sh execs discovery_announce.sh directly"
