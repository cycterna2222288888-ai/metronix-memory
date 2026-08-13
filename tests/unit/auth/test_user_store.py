"""Unit coverage for the must_change_password flag on UserStore."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from metronix.auth.user_store import UserStore


async def _store() -> UserStore:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    store = UserStore(engine)
    await store.ensure_schema()
    return store


@pytest.mark.asyncio
async def test_seed_admin_flags_default_admin_for_password_change() -> None:
    store = await _store()

    admin = await store.seed_admin(password="metronix")

    assert admin is not None
    assert admin["must_change_password"] is True


@pytest.mark.asyncio
async def test_create_user_defaults_must_change_password_to_false() -> None:
    store = await _store()

    user = await store.create_user(email="viewer@example.com", password="s3cret123")

    assert user["must_change_password"] is False


@pytest.mark.asyncio
async def test_update_user_can_toggle_must_change_password() -> None:
    store = await _store()
    user = await store.create_user(
        email="temp@example.com", password="s3cret123", must_change_password=True
    )

    # update_user re-reads the row via get_user_by_id, so on SQLite the boolean
    # comes back as an int (0/1) rather than True/False — assert on truthiness
    # so the test holds on both SQLite (tests) and Postgres (prod).
    updated = await store.update_user(user["id"], must_change_password=False)
    assert updated is not None
    assert not updated["must_change_password"]

    reverted = await store.update_user(user["id"], must_change_password=True)
    assert reverted is not None
    assert reverted["must_change_password"]


@pytest.mark.asyncio
async def test_must_change_password_round_trips_through_get_and_list() -> None:
    store = await _store()
    created = await store.create_user(
        email="flagged@example.com", password="s3cret123", must_change_password=True
    )

    by_email = await store.get_user_by_email("flagged@example.com")
    by_id = await store.get_user_by_id(created["id"])
    listed, _total = await store.list_users()

    assert by_email is not None
    assert by_email["must_change_password"]
    assert by_id is not None
    assert by_id["must_change_password"]
    listed_user = next(u for u in listed if u["id"] == created["id"])
    assert listed_user["must_change_password"]
