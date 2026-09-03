"""Regression coverage for #434: the Prompt 1 -> Prompt 2 onboarding contract.

Codex/Hermes prompt-2 now gates its AGENTS.md/SOUL.md write on a
``metronix_memory_list`` preflight call (see docs/integrations/{codex,hermes}
/prompt-2-memory.md, step 3). This proves the two outcomes that preflight
depends on, at the real tool boundary rather than the transport layer alone:

- a shared-key (no-principal) caller is denied with AUTH_REQUIRED before any
  store access, so a prompt-following agent stops before writing the file;
- an authenticated administrator (admin_override, no explicit grant needed)
  gets a clean, error-free response — including when the workspace/agent has
  no memory yet, so an empty list is never misread as denial.

Exercises the real ``AuthorizationEvaluator`` (not a stub) for the admin path
so the ``admin_override`` reasoning documented in #432 is actually proven, not
assumed. Deterministic and secret-free: no live network, no real Codex/Hermes
installation, no credential ever leaves this process.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest

from metronix.auth.policy import AuthorizationEvaluator
from metronix.mcp.principal import MCPPrincipal, bind_principal, reset_principal


@dataclass(frozen=True)
class _Grant:
    workspace_id: str
    agent_id: str
    principal_user_id: str
    capability: str
    grant_type: str


class _EmptyGrantStore:
    """No grants — admin path never consults this; non-admin paths would deny."""

    async def list_active_grants(
        self, workspace_id: str, agent_id: str, principal_user_id: str
    ) -> list[_Grant]:
        return []


class _AuditStore:
    """In-memory stand-in — the real store opens a Postgres engine lazily."""

    async def insert(self, row: object) -> None:
        return None


@pytest.fixture
def real_evaluator(monkeypatch: pytest.MonkeyPatch) -> AuthorizationEvaluator:
    """Wire the real shared evaluator (#314's deliverable) in for these tests."""
    from metronix.mcp.tools import _agent_access

    evaluator = AuthorizationEvaluator(_EmptyGrantStore())
    monkeypatch.setattr(_agent_access, "get_authorization_evaluator", lambda: evaluator)
    monkeypatch.setattr(_agent_access, "get_agent_access_audit_store", lambda: _AuditStore())
    return evaluator


def _empty_memory_service() -> AsyncMock:
    service = AsyncMock()
    service.pg_store.list_records = AsyncMock(return_value=[])
    service.pg_store.count_records = AsyncMock(return_value=0)
    return service


@pytest.mark.asyncio
async def test_shared_key_preflight_is_denied_before_store_access(
    real_evaluator: AuthorizationEvaluator,
) -> None:
    """No bound principal == a shared METRONIX_MCP_API_KEY request.

    This is the exact call docs/integrations/{codex,hermes}/prompt-2-memory.md
    step 3 makes. It must fail closed with AUTH_REQUIRED, and never reach the
    memory store — proving prompt-2's remediation branch (STOP, do not edit
    AGENTS.md/SOUL.md) has something real to key off.
    """
    from metronix.mcp.tools.memory_list import metronix_memory_list

    with patch(
        "metronix.mcp.tools.memory_list._memory_deps.build_memory_service_for_workspace",
        new=AsyncMock(),
    ) as build_service:
        out = await metronix_memory_list(
            workspace_id="MTRNIX", agent_id="onboarding-agent", limit=1
        )

    assert out["error"]["code"] == "AUTH_REQUIRED"
    build_service.assert_not_awaited()


@pytest.mark.asyncio
async def test_admin_principal_preflight_succeeds_via_admin_override(
    real_evaluator: AuthorizationEvaluator,
) -> None:
    """Administrator, no explicit agent-access grant needed (#432's supported flow).

    Proves the real evaluator's ``admin_override`` reasoning, not a mocked
    allow. The MCPPrincipal shape (role="admin", workspace_ids=("*",)) mirrors
    what mcp/auth.py actually derives for a freshly seeded first-run admin —
    see auth.py's ``if role == "admin" and not normalized_workspace_ids:
    normalized_workspace_ids = ("*",)``.
    """
    from metronix.mcp.tools.memory_list import metronix_memory_list

    token = bind_principal(
        MCPPrincipal("admin-1", "admin", ("*",), auth_method="personal_api_key")
    )
    try:
        with patch(
            "metronix.mcp.tools.memory_list._memory_deps.build_memory_service_for_workspace",
            new=AsyncMock(return_value=_empty_memory_service()),
        ):
            out = await metronix_memory_list(
                workspace_id="MTRNIX", agent_id="onboarding-agent", limit=1
            )
    finally:
        reset_principal(token)

    assert "error" not in out
    assert out["records"] == []
