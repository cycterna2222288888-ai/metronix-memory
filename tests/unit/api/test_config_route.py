"""Tests for the public /api/v1/config endpoint (issue #300)."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from starlette.testclient import TestClient

from metronix.api.routes.config import router as config_router
from metronix.connectors.schemas import CONNECTOR_SCHEMAS


def _app(plugin_manager=None) -> FastAPI:
    app = FastAPI()
    if plugin_manager is not None:
        app.state.plugin_manager = plugin_manager
    app.include_router(config_router, prefix="/api/v1")
    return app


def test_config_no_plugin_manager_returns_empty_plugins():
    client = TestClient(_app())
    r = client.get("/api/v1/config")
    assert r.status_code == 200
    assert r.json()["plugins"] == []


def test_config_reports_loaded_plugins():
    pm = SimpleNamespace(loaded_plugins=["enterprise"])
    client = TestClient(_app(plugin_manager=pm))
    r = client.get("/api/v1/config")
    assert r.json()["plugins"] == ["enterprise"]


def test_config_connector_types_matches_connector_category_schemas():
    client = TestClient(_app())
    r = client.get("/api/v1/config")
    body = r.json()

    expected = sorted(t for t, s in CONNECTOR_SCHEMAS.items() if s.category == "connector")
    assert body["connector_types"] == expected
    # Channel-category types (e.g. telegram/discord/slack) must not leak in.
    channel_types = {t for t, s in CONNECTOR_SCHEMAS.items() if s.category == "channel"}
    assert channel_types.isdisjoint(body["connector_types"])


def test_config_connector_types_are_plain_strings_only():
    client = TestClient(_app())
    body = client.get("/api/v1/config").json()
    assert all(isinstance(t, str) for t in body["connector_types"])
    # No leakage of label/fields/category — public endpoint, keys only.
    assert body["connector_types"] == sorted(set(body["connector_types"]))
