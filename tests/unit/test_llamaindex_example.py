"""Regression checks for examples/llamaindex_metronix_example.py.

The example doubles as the LlamaIndex guide's "Verify" step, so it must exit
non-zero when a pass fails — a shell/CI caller otherwise reads a failed memory
round-trip or an empty retrieval as success (toomij99, PR #439).

llama-index is intentionally *not* a project dependency (the guide installs the
client packages in a separate venv), so the module's top-level imports are
stubbed here to load it without that tree.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import pytest

_EXAMPLE_PATH = Path(__file__).resolve().parents[2] / "examples" / "llamaindex_metronix_example.py"


def _llama_index_stubs() -> dict[str, types.ModuleType]:
    """Minimal stand-ins for the llama_index names the example imports."""

    def _mod(name: str, **attrs: object) -> types.ModuleType:
        m = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(m, key, value)
        return m

    class _BaseRetriever:  # subclassed by MetronixRetriever at import time
        def __init__(self, *args: object, **kwargs: object) -> None: ...

    return {
        "llama_index": types.ModuleType("llama_index"),
        "llama_index.core": _mod(
            "llama_index.core",
            QueryBundle=type("QueryBundle", (), {}),
            get_response_synthesizer=lambda **_: None,
        ),
        "llama_index.core.async_utils": _mod(
            "llama_index.core.async_utils", asyncio_run=lambda coro: None
        ),
        "llama_index.core.query_engine": _mod(
            "llama_index.core.query_engine",
            RetrieverQueryEngine=type("RetrieverQueryEngine", (), {}),
        ),
        "llama_index.core.retrievers": _mod(
            "llama_index.core.retrievers", BaseRetriever=_BaseRetriever
        ),
        "llama_index.core.schema": _mod(
            "llama_index.core.schema",
            NodeWithScore=type("NodeWithScore", (), {}),
            TextNode=type("TextNode", (), {}),
        ),
        "llama_index.llms": types.ModuleType("llama_index.llms"),
        "llama_index.llms.openai_like": _mod(
            "llama_index.llms.openai_like", OpenAILike=type("OpenAILike", (), {})
        ),
        "llama_index.tools": types.ModuleType("llama_index.tools"),
        "llama_index.tools.mcp": _mod(
            "llama_index.tools.mcp", BasicMCPClient=type("BasicMCPClient", (), {})
        ),
    }


@pytest.fixture
def example(monkeypatch: pytest.MonkeyPatch) -> object:
    for name, module in _llama_index_stubs().items():
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location("_llamaindex_example_under_test", _EXAMPLE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestVerificationFailures:
    def test_both_passes_ok_is_empty(self, example: object) -> None:
        assert example._verification_failures(3, True) == []

    def test_zero_nodes_is_a_failure(self, example: object) -> None:
        failures = example._verification_failures(0, True)
        assert len(failures) == 1
        assert "no nodes" in failures[0]

    def test_memory_miss_is_a_failure(self, example: object) -> None:
        failures = example._verification_failures(5, False)
        assert len(failures) == 1
        assert "memory round-trip" in failures[0]

    def test_both_failing_reports_both(self, example: object) -> None:
        assert len(example._verification_failures(0, False)) == 2


class TestMainExitStatus:
    def _wire(
        self,
        example: object,
        monkeypatch: pytest.MonkeyPatch,
        *,
        nodes: int,
        retrieved: bool,
    ) -> None:
        monkeypatch.setattr(example, "METRONIX_MCP_TOKEN", "mtk_test")
        monkeypatch.setattr(example, "_build_client", lambda: object())
        monkeypatch.setattr(example.sys, "argv", ["example", "a question"])

        async def _retrieval_pass(_client: object, _question: str) -> int:
            return nodes

        async def _memory_pass(_client: object, _fact: str) -> bool:
            return retrieved

        monkeypatch.setattr(example, "retrieval_pass", _retrieval_pass)
        monkeypatch.setattr(example, "memory_pass", _memory_pass)

    def test_exits_nonzero_when_memory_round_trip_fails(
        self, example: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._wire(example, monkeypatch, nodes=3, retrieved=False)
        with pytest.raises(SystemExit) as exc_info:
            asyncio.run(example.main())
        assert exc_info.value.code == 1

    def test_exits_nonzero_when_retrieval_returns_no_nodes(
        self, example: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._wire(example, monkeypatch, nodes=0, retrieved=True)
        with pytest.raises(SystemExit) as exc_info:
            asyncio.run(example.main())
        assert exc_info.value.code == 1

    def test_exits_zero_when_both_passes_succeed(
        self, example: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._wire(example, monkeypatch, nodes=3, retrieved=True)
        asyncio.run(example.main())  # no SystemExit
