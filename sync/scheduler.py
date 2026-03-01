"""
Background sync scheduler: runs run_sync() on a daemon thread every hour.
"""

import threading
import time

_sync_thread: threading.Thread | None = None
_stop_event = threading.Event()


def start_background_sync(interval_seconds: int = 3600) -> None:
    """
    Start a daemon thread that calls run_sync() immediately, then every
    `interval_seconds`. Safe to call multiple times — only one thread runs.
    """
    global _sync_thread

    if _sync_thread is not None and _sync_thread.is_alive():
        return  # already running

    _stop_event.clear()

    def loop():
        # Import here to avoid circular imports at module level
        from sync.truelayer import run_sync

        while not _stop_event.is_set():
            try:
                run_sync()
            except Exception:
                pass  # errors are already logged inside run_sync
            _stop_event.wait(interval_seconds)

    _sync_thread = threading.Thread(target=loop, daemon=True, name="finance-sync")
    _sync_thread.start()


def stop_background_sync() -> None:
    _stop_event.set()


def trigger_manual_sync() -> dict:
    """Run a sync immediately (blocking) and return the result summary."""
    from sync.truelayer import run_sync
    return run_sync()
