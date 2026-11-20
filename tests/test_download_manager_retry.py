#!/usr/bin/env python3
"""
Regression test: failed MegaKino episodes must be marked as "failed" so the
retry endpoint can re-queue them.

Run with:
    python3 tests/test_download_manager_retry.py
"""

import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

# Redirect the database to a temporary location before importing the manager
import aniworld.web.database as db_module  # noqa: E402

db_module.get_database_path = lambda: os.path.join(tempfile.mkdtemp(), "aniworld.db")

import aniworld.web.download_manager as dm_module  # noqa: E402
from aniworld.web.download_manager import DownloadQueueManager  # noqa: E402

results = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    results.append((name, bool(condition)))
    print(f"[{status}] {name}{' - ' + detail if detail else ''}")


class FailingMegakinoClient:
    """Fake client that raises, simulating a 404/network error."""

    def __init__(self, *args, **kwargs):
        pass

    def get_details(self, url):
        raise RuntimeError("simulated MegaKino failure")


def wait_for_job(manager, queue_id, timeout=30):
    deadline = timeout
    while deadline > 0:
        status = manager.get_queue_status()
        for job in status["completed"]:
            if job["id"] == queue_id:
                return job
        deadline -= 0.25
        threading.Event().wait(0.25)
    return None


def main():
    # Simulate a MegaKino failure (exception path)
    dm_module.MegakinoClient = FailingMegakinoClient

    manager = DownloadQueueManager()
    url = "megakino:movie:https://megakino23.com/films/1-test.html"
    queue_id = manager.add_download(
        anime_title="Retry Test",
        episode_urls=[url],
        language="German Dub",
        provider="VOE",
        total_episodes=1,
    )

    job = wait_for_job(manager, queue_id)
    check("failed job recorded", job is not None and job["status"] == "failed", str(job and job["status"]))

    episodes = manager.get_job_episodes(queue_id) or []
    failed = [ep for ep in episodes if ep.get("status") == "failed"]
    check("episode marked as failed", len(failed) == 1, str([ep.get("status") for ep in episodes]))

    new_queue_id = manager.retry_download(queue_id)
    check("retry returns new queue id", bool(new_queue_id), str(new_queue_id))

    if new_queue_id:
        retried = wait_for_job(manager, new_queue_id)
        check("retried job processed", retried is not None, str(retried and retried["status"]))

    failed_checks = [name for name, ok in results if not ok]
    print("\n" + "=" * 60)
    if failed_checks:
        print(f"FAILED: {len(failed_checks)} check(s): {', '.join(failed_checks)}")
        return 1
    print(f"All {len(results)} checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
