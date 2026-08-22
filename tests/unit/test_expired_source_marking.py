"""Tests for marking expired (stale/superseded/archived) sources (MTRNIX-181).

Covers the three places a source's status reaches an outward-facing payload:
_collect_frags (per-fragment status/is_expired), _build_ctx (the short,
neutral marker fed into the LLM prompt), and _append_sources (the visible
citation list appended to the final answer).
"""

from __future__ import annotations


def _make_result(
    status: str | None = "active",
    title: str = "Doc",
    source_type: str = "confluence",
    url: str = "",
) -> dict:
    return {
        "memory": "some content",
        "data": "some content",
        "title": title,
        "type": source_type,
        "source_role": "knowledge_base",
        "doc_label": f"{source_type}:1",
        "url": url,
        "payload": {},
        **({"status": status} if status is not None else {}),
    }


class TestCollectFragsStatus:
    def test_stale_source_marked_expired(self) -> None:
        from metronix.retrieval.search import _collect_frags

        base = [_make_result(status="stale")]
        frags, _, _, _ = _collect_frags(base, set(), 0)
        assert frags[0]["status"] == "stale"
        assert frags[0]["is_expired"] is True

    def test_active_source_not_expired(self) -> None:
        from metronix.retrieval.search import _collect_frags

        base = [_make_result(status="active")]
        frags, _, _, _ = _collect_frags(base, set(), 0)
        assert frags[0]["is_expired"] is False

    def test_missing_status_defaults_to_active_and_not_expired(self) -> None:
        """A chunk with no status field at all must never be flagged expired."""
        from metronix.retrieval.search import _collect_frags

        base = [_make_result(status=None)]
        frags, _, _, _ = _collect_frags(base, set(), 0)
        assert frags[0]["status"] == "active"
        assert frags[0]["is_expired"] is False


class TestBuildCtxExpiryMarker:
    def _frag(self, status: str | None, is_expired: bool) -> dict:
        return {
            "text": "[CONFLUENCE] Doc\nSome content",
            "source_type": "confluence",
            "source_role": "knowledge_base",
            "title": "Doc",
            "date": "",
            "doc_label": "confluence:1",
            "evidence_marker": "SUPPORTING",
            "status": status,
            "is_expired": is_expired,
        }

    def test_expired_fragment_gets_neutral_marker(self) -> None:
        from metronix.retrieval.search import _build_ctx

        frags = [self._frag("stale", True)]
        ctx = _build_ctx("query", "en", frags, [], [], [])
        assert "(outdated)" in ctx

    def test_marker_is_short_and_neutral_not_alarmist(self) -> None:
        """The LLM-facing marker must never tell the model to distrust the
        source — that phrasing makes models prone to refusing to answer."""
        from metronix.retrieval.search import _build_ctx

        frags = [self._frag("archived", True)]
        ctx = _build_ctx("query", "en", frags, [], [], [])
        banned_phrases = [
            "do not trust",
            "don't trust",
            "unreliable",
            "warning",
            "caution",
            "untrustworthy",
        ]
        lower_ctx = ctx.lower()
        for phrase in banned_phrases:
            assert phrase not in lower_ctx, f"alarmist phrase leaked into LLM context: {phrase!r}"

    def test_active_fragment_has_no_marker(self) -> None:
        from metronix.retrieval.search import _build_ctx

        frags = [self._frag("active", False)]
        ctx = _build_ctx("query", "en", frags, [], [], [])
        assert "(outdated)" not in ctx

    def test_fragment_without_is_expired_key_has_no_marker(self) -> None:
        """Back-compat: frag dicts predating this field (e.g. hand-built in
        other tests) must not crash and must not render a marker."""
        from metronix.retrieval.search import _build_ctx

        frags = [
            {
                "text": "[JIRA] PROJ-1\nContent",
                "source_type": "jira",
                "source_role": "task_tracker",
                "title": "PROJ-1",
                "date": "",
                "doc_label": "jira:1",
                "evidence_marker": "PRIMARY",
            }
        ]
        ctx = _build_ctx("query", "en", frags, [], [], [])
        assert "(outdated)" not in ctx


class TestAppendSourcesExpiryLabel:
    def test_stale_source_labeled_outdated(self) -> None:
        from metronix.retrieval.search import _append_sources

        results = [_make_result(status="stale", title="Old Doc", url="https://x/1")]
        out = _append_sources("Answer text.", results)
        assert "⚠️ (outdated)" in out
        assert "Old Doc" in out

    def test_superseded_source_labeled_superseded(self) -> None:
        from metronix.retrieval.search import _append_sources

        results = [_make_result(status="superseded", title="Old Doc")]
        out = _append_sources("Answer text.", results)
        assert "⚠️ (superseded)" in out

    def test_archived_source_labeled_archived(self) -> None:
        from metronix.retrieval.search import _append_sources

        results = [_make_result(status="archived", title="Old Doc")]
        out = _append_sources("Answer text.", results)
        assert "⚠️ (archived)" in out

    def test_active_source_has_no_expiry_label(self) -> None:
        from metronix.retrieval.search import _append_sources

        results = [_make_result(status="active", title="Fresh Doc")]
        out = _append_sources("Answer text.", results)
        assert "⚠️" not in out

    def test_missing_status_has_no_expiry_label(self) -> None:
        from metronix.retrieval.search import _append_sources

        results = [_make_result(status=None, title="Legacy Doc")]
        out = _append_sources("Answer text.", results)
        assert "⚠️" not in out
