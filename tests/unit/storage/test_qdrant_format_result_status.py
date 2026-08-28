"""Tests for status/freshness_score surfacing in _format_result (MTRNIX-181).

Covers both QdrantVectorStore (sync) and AsyncQdrantVectorStore (async) —
their ``_format_result`` bodies are intentionally kept in lockstep.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from metronix.storage.qdrant import AsyncQdrantVectorStore, QdrantVectorStore


def _make_point(payload: dict | None = None):
    """A fake Qdrant point object, matching what the client SDK returns."""
    return SimpleNamespace(id="p1", payload=payload or {}, score=0.9)


# `_format_result` reads only `point`/`score`; bypass __init__ (which for the
# sync store makes a real network call) via __new__ so no client is needed.
@pytest.fixture(params=[QdrantVectorStore, AsyncQdrantVectorStore])
def store(request):
    cls = request.param
    return cls.__new__(cls)


class TestFormatResultStatus:
    def test_surfaces_status_from_payload(self, store) -> None:
        point = _make_point({"status": "stale", "title": "T"})
        result = store._format_result(point, 0.5)
        assert result["status"] == "stale"

    def test_missing_status_defaults_to_active(self, store) -> None:
        """No status field at all (pre-MTRNIX-313 chunk) must default to
        'active', never a false-positive expired status."""
        point = _make_point({"title": "T"})
        result = store._format_result(point, 0.5)
        assert result["status"] == "active"

    def test_empty_string_status_defaults_to_active(self, store) -> None:
        point = _make_point({"status": "", "title": "T"})
        result = store._format_result(point, 0.5)
        assert result["status"] == "active"

    def test_surfaces_freshness_score_from_payload(self, store) -> None:
        point = _make_point({"freshness_score": 0.42})
        result = store._format_result(point, 0.5)
        assert result["freshness_score"] == 0.42

    def test_missing_freshness_score_is_none(self, store) -> None:
        point = _make_point({})
        result = store._format_result(point, 0.5)
        assert result["freshness_score"] is None

    def test_existing_fields_unaffected(self, store) -> None:
        """New fields are additive — the pre-existing result shape is unchanged."""
        point = _make_point({"title": "T", "type": "confluence", "status": "archived"})
        result = store._format_result(point, 0.9)
        assert result["title"] == "T"
        assert result["type"] == "confluence"
        assert result["payload"]["status"] == "archived"
