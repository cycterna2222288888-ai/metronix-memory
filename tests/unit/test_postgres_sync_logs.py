"""Tests for PostgresStore.create_sync_log / update_sync_log helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from metronix.core.config import Settings
from metronix.storage.pg_connection import get_engine, get_session
from metronix.storage.pg_models import SyncLogRow
from metronix.storage.postgres import PostgresStore

# Deliberately far past any reclaim threshold this repo has ever shipped
# (#425 review: age alone must never make a running row look free).
_A_LONG_TIME = timedelta(hours=6)


@pytest.fixture
async def store():
    s = Settings()
    yield PostgresStore(s.postgres_dsn)


@pytest.fixture
def seeded_ids():
    suffix = uuid4().hex[:10]
    ws_id = f"ws_sl_{suffix}"
    cid = f"conn_sl_{suffix}"
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug)"),
            {"id": ws_id, "name": "t", "slug": ws_id},
        )
        conn.execute(
            text(
                "INSERT INTO connections"
                " (id, workspace_id, connector_type, name, config_encrypted, status, enabled)"
                " VALUES (:id, :ws, 'jira', 'T', :cfg, 'active', true)"
            ),
            {"id": cid, "ws": ws_id, "cfg": b"x"},
        )
        conn.commit()
    yield ws_id, cid


async def test_create_sync_log_inserts_running_row(store, seeded_ids):
    ws, cid = seeded_ids
    sync_id = f"sync_create_{uuid4().hex[:10]}"

    await store.create_sync_log(
        sync_id=sync_id,
        workspace_id=ws,
        connection_id=cid,
        connector_type="jira",
    )

    with get_session() as s:
        row = s.query(SyncLogRow).filter_by(id=sync_id).first()
        assert row is not None
        assert row.status == "running"
        assert row.documents_fetched == 0
        assert row.qdrant_chunks == 0
        assert row.errors == []
        assert row.source_title == "Jira Sync"
        assert row.created_at is not None


async def test_update_sync_log_finalizes_row(store, seeded_ids):
    ws, cid = seeded_ids
    sync_id = f"sync_update_{uuid4().hex[:10]}"
    await store.create_sync_log(
        sync_id=sync_id,
        workspace_id=ws,
        connection_id=cid,
        connector_type="jira",
    )

    await store.update_sync_log(
        sync_id=sync_id,
        status="success",
        documents_fetched=297,
        documents_new=22,
        documents_updated=5,
        documents_skipped=270,
        qdrant_chunks=27,
        errors=[],
        duration_ms=6700.5,
    )

    with get_session() as s:
        row = s.query(SyncLogRow).filter_by(id=sync_id).first()
        assert row.status == "success"
        assert row.documents_fetched == 297
        assert row.documents_new == 22
        assert row.qdrant_chunks == 27
        assert row.duration_ms == pytest.approx(6700.5)


async def test_update_sync_log_accepts_failed_with_errors(store, seeded_ids):
    ws, cid = seeded_ids
    sync_id = f"sync_fail_{uuid4().hex[:10]}"
    await store.create_sync_log(
        sync_id=sync_id,
        workspace_id=ws,
        connection_id=cid,
        connector_type="jira",
    )

    await store.update_sync_log(
        sync_id=sync_id,
        status="failed",
        errors=["boom: 500"],
        duration_ms=100.0,
    )

    with get_session() as s:
        row = s.query(SyncLogRow).filter_by(id=sync_id).first()
        assert row.status == "failed"
        assert row.errors == ["boom: 500"]
        assert row.documents_fetched == 0  # unchanged — we didn't pass it


# ---------------------------------------------------------------------------
# has_running_sync (#401 / #425)
#
# No time window — see postgres.py's has_running_sync docstring for why.
# ---------------------------------------------------------------------------


def _insert_sync_log(*, ws: str, cid: str, status: str, created_at: datetime | None) -> str:
    sync_id = f"sync_sl_{uuid4().hex[:10]}"
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO sync_logs"
                " (id, workspace_id, connection_id, connector_type, status,"
                "  documents_fetched, documents_new, documents_updated,"
                "  documents_skipped, errors, duration_ms, qdrant_chunks, trigger, created_at)"
                " VALUES (:id, :ws, :cid, 'jira', :status,"
                "         0, 0, 0, 0, '[]'::jsonb, 0, 0, 'manual', :created_at)"
            ),
            {"id": sync_id, "ws": ws, "cid": cid, "status": status, "created_at": created_at},
        )
        conn.commit()
    return sync_id


async def test_has_running_sync_true_for_fresh_running_row(store, seeded_ids):
    ws, cid = seeded_ids
    _insert_sync_log(ws=ws, cid=cid, status="running", created_at=datetime.now(UTC))

    assert await store.has_running_sync(cid) is True


async def test_has_running_sync_true_regardless_of_age(store, seeded_ids):
    """The #425 review's core ask: a live task must never be preempted just
    because it has been running a long time. There is no age cutoff at all
    now — a 'running' row this old is exactly the shape of a healthy long
    Confluence/Jira sync, and must still block a retry."""
    ws, cid = seeded_ids
    _insert_sync_log(
        ws=ws,
        cid=cid,
        status="running",
        created_at=datetime.now(UTC) - _A_LONG_TIME,
    )

    assert await store.has_running_sync(cid) is True


async def test_has_running_sync_false_when_no_running_row(store, seeded_ids):
    ws, cid = seeded_ids
    # A finished run must not count — only 'running' does.
    _insert_sync_log(ws=ws, cid=cid, status="success", created_at=datetime.now(UTC))

    assert await store.has_running_sync(cid) is False
