"""Phase 0 storage factory — the single construction seam for the relational stores.

Behaviour must stay byte-identical to calling the concrete constructors directly
for the only supported backend (``postgres``); the guard rejects anything else.
"""

from __future__ import annotations

import pytest

from metronix.core import config as config_mod
from metronix.storage import factory
from metronix.storage.memory_postgres import MemoryPostgresStore
from metronix.storage.postgres import PostgresStore

_DSN = "postgresql+asyncpg://user:pw@localhost:5432/metronix"


class _FakeSettings:
    def __init__(self, backend: str) -> None:
        self.storage_backend = backend


def test_require_supported_backend_returns_postgres_by_default() -> None:
    assert factory.require_supported_backend() == "postgres"


def test_build_document_store_returns_postgres_store() -> None:
    assert isinstance(factory.build_document_store(_DSN), PostgresStore)


def test_build_memory_store_wraps_the_given_engine() -> None:
    sentinel = object()
    store = factory.build_memory_store(sentinel)  # type: ignore[arg-type]
    assert isinstance(store, MemoryPostgresStore)
    assert store._engine is sentinel


@pytest.mark.parametrize("entrypoint", ["require_supported_backend", "build_document_store"])
def test_unsupported_backend_is_rejected_at_the_seam(monkeypatch, entrypoint: str) -> None:
    monkeypatch.setattr(factory, "get_settings", lambda: _FakeSettings("sqlite"))

    with pytest.raises(ValueError, match=r"STORAGE_BACKEND.*docs/STORAGE\.md"):
        if entrypoint == "require_supported_backend":
            factory.require_supported_backend()
        else:
            factory.build_document_store(_DSN)


def test_settings_validator_rejects_unknown_backend(monkeypatch) -> None:
    monkeypatch.setenv("STORAGE_BACKEND", "mongodb")
    monkeypatch.setattr(config_mod, "_settings", None)
    with pytest.raises(ValueError, match="storage_backend must be one of"):
        config_mod.Settings()
    monkeypatch.setattr(config_mod, "_settings", None)
