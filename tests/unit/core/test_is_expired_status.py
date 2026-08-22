"""Tests for is_expired_status (MTRNIX-181 — highlight expired sources)."""

from __future__ import annotations

import pytest

from metronix.core.models import LifecycleStatus, is_expired_status


@pytest.mark.parametrize(
    "status",
    [LifecycleStatus.STALE, LifecycleStatus.SUPERSEDED, LifecycleStatus.ARCHIVED],
)
def test_expired_statuses_are_expired(status: LifecycleStatus) -> None:
    assert is_expired_status(status) is True
    # Also accepts the raw string value, as read from a Qdrant/Postgres payload.
    assert is_expired_status(status.value) is True


@pytest.mark.parametrize(
    "status",
    [
        LifecycleStatus.ACTIVE,
        LifecycleStatus.CANDIDATE,
        LifecycleStatus.CONFLICTED,
        LifecycleStatus.REVIEW_NEEDED,
    ],
)
def test_non_expired_statuses_are_not_expired(status: LifecycleStatus) -> None:
    assert is_expired_status(status) is False


def test_missing_status_defaults_to_not_expired() -> None:
    """A chunk with no status field at all (pre-MTRNIX-313 data) must never
    read as expired — absence of a status is not evidence of staleness."""
    assert is_expired_status(None) is False
    assert is_expired_status("") is False


def test_unrecognized_status_defaults_to_not_expired() -> None:
    """Garbage/forward-incompatible status strings fail closed (not expired)
    rather than raising, so a bad payload can never crash retrieval."""
    assert is_expired_status("some_future_status") is False
