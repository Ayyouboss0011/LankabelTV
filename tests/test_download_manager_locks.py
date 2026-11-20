#!/usr/bin/env python3
"""
Regression tests for the download queue lock handling.

Covers the two self-deadlock paths that previously froze the whole queue:
- cancelling a queued job (cancel_download -> _update_download_status)
- removing the last episode of a job (stop_episode -> cancel_download)

Run with:
    python3 tests/test_download_manager_locks.py
"""

import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

# Redirect the database to a temporary location before importing the manager
import aniworld.web.database as db_module  # noqa: E402

db_module.get_database_path = lambda: os.path.join(tempfile.mkdtemp(), "aniworld.db")

from aniworld.web.download_manager import DownloadQueueManager  # noqa: E402

TIMEOUT = 5.0
results = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    results.append((name, bool(condition)))
    print(f"[{status}] {name}{' - ' + detail if detail else ''}")


def run_with_timeout(fn, timeout=TIMEOUT):
    """Run fn in a thread; returns (finished, value)."""
    box = {}

    def target():
        box["value"] = fn()

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout)
    return (not thread.is_alive()), box.get("value")


def make_manager():
    """Create a manager with a non-reentrant lock so the logic itself is tested."""
    manager = DownloadQueueManager()
    # Keep jobs queued: pretend the processor is running without actually starting it
    manager.is_processing = True
    # Force a plain Lock (not RLock) to catch nested lock acquisitions
    manager._queue_lock = threading.Lock()
    return manager


def test_cancel_queued_job():
    manager = make_manager()
    queue_id = manager.add_download(
        anime_title="Test Movie",
        episode_urls=["megakino:movie:https://megakino23.com/films/1-test.html"],
        language="German Dub",
        provider="VOE",
        total_episodes=1,
    )

    finished, value = run_with_timeout(lambda: manager.cancel_download(queue_id))
    check("cancel queued job returns", finished, "deadlock!" if not finished else f"returned {value}")
    check("cancel queued job reports success", value is True)

    finished, status = run_with_timeout(lambda: manager.get_queue_status())
    check("queue lock usable after cancel", finished and status is not None)


def test_stop_last_episode():
    manager = make_manager()
    episodes = [
        "megakino:series:https://megakino23.com/serials/1-test-1-staffel.html::ep1",
        "megakino:series:https://megakino23.com/serials/1-test-1-staffel.html::ep2",
    ]
    queue_id = manager.add_download(
        anime_title="Test Series",
        episode_urls=episodes,
        language="German Dub",
        provider="VOE",
        total_episodes=len(episodes),
    )

    finished, _ = run_with_timeout(lambda: manager.stop_episode(queue_id, episodes[0]))
    check("stop first episode returns", finished, "deadlock!" if not finished else "")

    # Removing the last episode triggers cancel_download internally
    finished, value = run_with_timeout(lambda: manager.stop_episode(queue_id, episodes[1]))
    check("stop last episode returns", finished, "deadlock!" if not finished else f"returned {value}")
    check("stop last episode reports success", value is True)

    finished, status = run_with_timeout(lambda: manager.get_queue_status())
    check("queue lock usable after stop", finished and status is not None)


def main():
    for test in (test_cancel_queued_job, test_stop_last_episode):
        print(f"\n=== {test.__name__} ===")
        test()

    failed = [name for name, ok in results if not ok]
    print("\n" + "=" * 60)
    if failed:
        print(f"FAILED: {len(failed)} check(s): {', '.join(failed)}")
        return 1
    print(f"All {len(results)} checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
