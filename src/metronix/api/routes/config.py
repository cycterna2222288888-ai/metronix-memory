"""Application config endpoint — /api/v1/config."""

from __future__ import annotations

from fastapi import APIRouter, Request

from metronix.connectors.schemas import CONNECTOR_SCHEMAS

router = APIRouter(tags=["config"])


@router.get("/config")
def get_config(request: Request) -> dict:
    """Return application configuration including installed plugins.

    Public endpoint (no auth required). Used by UI to detect
    enterprise features and to know which connector types exist before
    the authenticated schema details (``/api/v1/connections/schemas/``)
    have loaded.
    """
    plugins: list[str] = []
    pm = getattr(request.app.state, "plugin_manager", None)
    if pm:
        plugins = pm.loaded_plugins
    connector_types = sorted(t for t, s in CONNECTOR_SCHEMAS.items() if s.category == "connector")
    return {"plugins": plugins, "connector_types": connector_types}
