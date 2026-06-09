"""
E2E test fixtures for LankabelTV.

This module sets up:
1. A fake yt-dlp-compatible HTTP server (slow streaming endpoint) that
   runs inside the test process. yt-dlp inside the container can hit
   this server so we get a real long-running download without relying
   on the public internet.
2. A docker-compose stack that starts the LankabelTV container pointed
   at the fake server.
3. Playwright browser fixtures.
4. A screenshot helper that dumps the page on test failure.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

import pytest


# ---------------------------------------------------------------------------
# Fake "yt-dlp target" HTTP server
# ---------------------------------------------------------------------------
#
# yt-dlp's YoutubeDL.download() calls into a real HTTP server. We stand up
# a tiny local server that pretends to be an HLS stream / video segment
# server: it returns a fake playlist (or a slow-streaming response) so
# yt-dlp is busy reading bytes for as long as we want.
#
# This lets us reproduce the "long-running yt-dlp download" scenario
# in tests, without needing internet access or an actual anime site.

class _FakeYtdlpHandler(BaseHTTPRequestHandler):
    """HTTP handler that returns a slow-streaming fake video response.

    Endpoints:
        GET /ready          - returns 200 immediately (used to confirm the
                              server is up)
        GET /stream         - streams 64KB chunks slowly. Each chunk
                              takes ``CHUNK_DELAY`` seconds to send, so
                              the download takes roughly
                              (N_chunks * CHUNK_DELAY) seconds in total.
        GET /stream?dur=N   - same as /stream but the server sleeps for
                              N seconds in total before completing
                              (overrides CHUNK_DELAY).
    """

    CHUNK_DELAY = 0.5  # seconds between chunks (per 64KB)
    CHUNK_SIZE = 64 * 1024
    TOTAL_CHUNKS = 200  # ~12MB total per default stream
    REQUEST_LOG: List[Tuple[str, str, float]] = []  # (path, query, t)

    def log_message(self, format, *args):  # silence default logging
        pass

    def do_GET(self):  # noqa: N802 (BaseHTTPRequestHandler API)
        # Record the request for test introspection
        self.__class__.REQUEST_LOG.append(
            (self.path, time.strftime("%H:%M:%S"), time.time())
        )

        if self.path.startswith("/ready"):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ready")
            return

        if self.path.startswith("/stream"):
            # Parse optional ?dur=N query param
            dur = None
            if "?" in self.path:
                qs = self.path.split("?", 1)[1]
                for kv in qs.split("&"):
                    if kv.startswith("dur="):
                        try:
                            dur = float(kv.split("=", 1)[1])
                        except ValueError:
                            dur = None

            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(self.CHUNK_SIZE * self.TOTAL_CHUNKS))
            self.end_headers()

            try:
                if dur is not None:
                    # Send chunks as fast as possible, but throttle the
                    # *connection lifetime* to ``dur`` seconds by sleeping
                    # between chunks.
                    chunk_delay = dur / max(1, self.TOTAL_CHUNKS)
                else:
                    chunk_delay = self.CHUNK_DELAY

                chunk = b"\x00" * self.CHUNK_SIZE
                for _ in range(self.TOTAL_CHUNKS):
                    try:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    time.sleep(chunk_delay)
            except Exception:
                pass
            return

        self.send_response(404)
        self.end_headers()

    def do_HEAD(self):  # noqa: N802
        if self.path.startswith("/ready"):
            self.send_response(200)
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()


def _find_free_port() -> int:
    """Find a free TCP port on localhost."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="session")
def fake_ytdlp_server() -> Iterator[Tuple[str, int]]:
    """Start a fake yt-dlp server on a free port. Returns (host, port)."""
    port = _find_free_port()
    _FakeYtdlpHandler.REQUEST_LOG = []  # reset
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _FakeYtdlpHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True, name="fake-ytdlp")
    t.start()
    # Wait until /ready responds
    import urllib.request
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/ready", timeout=1).read()
            break
        except Exception:
            time.sleep(0.05)
    yield ("127.0.0.1", port)
    httpd.shutdown()
    httpd.server_close()


# ---------------------------------------------------------------------------
# Docker stack fixtures
# ---------------------------------------------------------------------------


def _has_docker() -> bool:
    try:
        subprocess.run(
            ["docker", "version"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


@pytest.fixture(scope="session")
def docker_available() -> bool:
    return _has_docker()


@pytest.fixture(scope="session")
def lankabeltv_container(
    docker_available, fake_ytdlp_server, request
) -> Iterator[dict]:
    """Start the LankabelTV container for the test session.

    Skips the test session if docker is not available.
    The container is built (or reused) and started. We wait until the
    /api/test endpoint returns 200 before yielding.
    """
    if not docker_available:
        pytest.skip("docker is not available")

    repo_root = Path(__file__).resolve().parents[2]
    image_name = "lankabeltv-e2e-test"
    container_name = f"lankabeltv-e2e-{int(time.time())}"
    host_port = _find_free_port()
    series_dir = Path("/tmp/lankabeltv-e2e-series")
    movie_dir = Path("/tmp/lankabeltv-e2e-movies")
    series_dir.mkdir(parents=True, exist_ok=True)
    movie_dir.mkdir(parents=True, exist_ok=True)

    # Build the image (only once per session)
    build_marker = Path("/tmp/.lankabeltv-e2e-built")
    if not build_marker.exists():
        subprocess.run(
            ["docker", "build", "-t", image_name, "."],
            cwd=repo_root,
            check=True,
        )
        build_marker.touch()

    # Remove any leftover container with this name
    subprocess.run(
        ["docker", "rm", "-f", container_name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Start the container. We pass the fake server's host and port as
    # env vars so we can construct URLs that point to it. Note: the
    # container can reach the host via host.docker.internal on macOS /
    # Docker Desktop. On Linux this would need --network=host or
    # different routing.
    host, port = fake_ytdlp_server
    cmd = [
        "docker", "run", "-d",
        "--name", container_name,
        "-p", f"{host_port}:8080",
        "-e", f"SERIES_DOWNLOAD_DIR={series_dir}",
        "-e", f"MOVIE_DOWNLOAD_DIR={movie_dir}",
        "-v", f"{series_dir}:/app/downloads/series",
        "-v", f"{movie_dir}:/app/downloads/movies",
        image_name,
    ]
    subprocess.run(cmd, check=True)

    # Wait for the server to come up
    base_url = f"http://127.0.0.1:{host_port}"
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            import urllib.request
            r = urllib.request.urlopen(f"{base_url}/api/test", timeout=1)
            if r.status == 200:
                break
        except Exception:
            time.sleep(0.5)
    else:
        # capture logs for debugging
        logs = subprocess.run(
            ["docker", "logs", container_name],
            capture_output=True, text=True,
        )
        pytest.fail(
            f"Container did not become ready within 60s. Logs:\n{logs.stdout}\n{logs.stderr}"
        )

    info = {
        "container_name": container_name,
        "image_name": image_name,
        "host_port": host_port,
        "base_url": base_url,
        "fake_ytdlp_host": host,
        "fake_ytdlp_port": port,
    }

    yield info

    # Cleanup: stop + remove container (but keep the image for next run)
    subprocess.run(
        ["docker", "rm", "-f", container_name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# ---------------------------------------------------------------------------
# Playwright fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def base_url(lankabeltv_container) -> str:
    return lankabeltv_container["base_url"]


@pytest.fixture(scope="function")
async def browser_page():
    """Provides a fresh Playwright browser page for each test."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context()
        page = await context.new_page()
        try:
            yield page
        finally:
            try:
                await context.close()
            except Exception:
                pass
            try:
                await browser.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Screenshot helper
# ---------------------------------------------------------------------------


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Capture a screenshot of the browser page on test failure."""
    outcome = yield
    rep = outcome.get_result()
    if rep.when == "call" and rep.failed:
        page = item.funcargs.get("browser_page") if hasattr(item, "funcargs") else None
        if page is not None:
            try:
                import asyncio
                screenshots_dir = (
                    Path(__file__).resolve().parent / "screenshots"
                )
                screenshots_dir.mkdir(parents=True, exist_ok=True)
                fname = (
                    screenshots_dir
                    / f"{item.name}_{int(time.time())}.png"
                )
                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(page.screenshot(path=str(fname)))
                finally:
                    loop.close()
                print(f"\n[FAILURE] Screenshot saved to {fname}")
            except Exception as e:
                print(f"\n[FAILURE] Could not save screenshot: {e}")


# ---------------------------------------------------------------------------
# Convenience helpers used by tests
# ---------------------------------------------------------------------------


def make_episode_url(fake_host: str, fake_port: int, season: int = 1, episode: int = 1, dur: Optional[float] = None) -> str:
    """Construct a URL that points to the fake yt-dlp server's /stream endpoint."""
    url = f"http://{fake_host}:{fake_port}/stream"
    if dur is not None:
        url += f"?dur={dur}"
    # The path is shaped like a real episode URL so the parser's regex
    # recognises the season/episode markers.
    return url
