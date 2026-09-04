"""Unit tests for connection_sync.release_unstarted_sync_claim (#401/#425).

Shared by every sync entry point (autosync tick, REST trigger_sync,
metronix_source_sync) to undo a claim that never handed off to a running
run_connection_sync task. Tested in isolation here with a fake store; each
call site's own test (test_autosync.py, test_connections_sync.py,
test_mcp_source_tools.py) verifies it is actually invoked on a spawn failure.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from metronix.connectors.connection_sync import release_unstarted_sync_claim


class _FakeStore:
    def __init__(self) -> None:
        self.update_connection_status = AsyncMock()
        self.update_sync_log = AsyncMock()


async def test_releases_connection_status_and_finalizes_the_log_row() -> None:
    store = _FakeStore()

    await release_unstarted_sync_claim(
        store, "conn-1", sync_id="sync-1", message="could not start"
    )

    store.update_connection_status.assert_awaited_once_with(
        "conn-1", status="error", error_message="could not start"
    )
    store.update_sync_log.assert_awaited_once_with(
        "sync-1", status="failed", errors=["could not start"]
    )


async def test_skips_the_log_write_when_no_row_was_ever_created() -> None:
    """create_sync_log can fail before a claim is released (non-fatal at the
    call site) — sync_id is then None and there is no row to finalize."""
    store = _FakeStore()

    await release_unstarted_sync_claim(store, "conn-1", sync_id=None, message="could not start")

    store.update_connection_status.assert_awaited_once()
    store.update_sync_log.assert_not_awaited()


async def test_connection_status_failure_does_not_prevent_the_log_write() -> None:
    """Releasing the claim is itself best-effort — one failing write must not
    stop the other, and neither may raise into the caller's own error path."""
    store = _FakeStore()
    store.update_connection_status.side_effect = RuntimeError("db down")

    await release_unstarted_sync_claim(store, "conn-1", sync_id="sync-1", message="msg")

    store.update_sync_log.assert_awaited_once()


async def test_log_write_failure_is_swallowed() -> None:
    store = _FakeStore()
    store.update_sync_log.side_effect = RuntimeError("db down")

    # Must not raise.
    await release_unstarted_sync_claim(store, "conn-1", sync_id="sync-1", message="msg")
