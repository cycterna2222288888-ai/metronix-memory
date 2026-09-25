"""`.env.example` must survive Docker Compose's env_file parser (issue #458).

Compose parses `env_file` with compose-spec/compose-go's `dotenv` package. For an
unquoted line it:

  1. strips leading whitespace from the value (`locateKeyName`), then
  2. removes an inline comment only at the first literal " #" — a space
     immediately followed by '#' (`extractVarValue`: `strings.Cut(value, " #")`),
     then trims trailing whitespace.

So `KEY=value   # note` -> `value`, but `KEY=   # note` -> the leading spaces are
gone first, the value now *starts* with '#', there is no " #" to cut, and the
whole `# note` becomes the value.

This project keeps every comment on its own line above the assignment, so the
check here is strict: no assignment line may carry an inline `#` at all.
"""

from __future__ import annotations

import re
from pathlib import Path

ENV_EXAMPLE = Path(".env.example")

# compose-go dotenv `isSpace`: space, tab, vertical tab, form feed, CR, NEL, NBSP.
_COMPOSE_WHITESPACE = " \t\v\f\r\x85\xa0"

_ASSIGNMENT = re.compile(r"^(?:export\s+)?([A-Za-z0-9_.\-\[\]]+)=(.*)$")

# Keys that #458 caught resolving to their comment text — anchor them explicitly.
_PREVIOUSLY_BROKEN = (
    "QDRANT_API_KEY",
    "AUTH_PASSWORD",
    "OLLAMA_REQUEST_TIMEOUT",
    "METRONIX_FRESHNESS_LLM_PROVIDER",
    "LLM_FALLBACK_PROVIDER",
    "LLM_PROVIDER_API_KEY",
    "LLM_PROVIDER_MODEL",
)


def _assignments() -> dict[str, tuple[int, str]]:
    """{key: (line_number, raw_rhs)} for every KEY=... line in .env.example."""
    out: dict[str, tuple[int, str]] = {}
    for n, line in enumerate(ENV_EXAMPLE.read_text().splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = _ASSIGNMENT.match(line)
        assert m, f".env.example line {n} is neither blank, a comment, nor KEY=VALUE: {line!r}"
        out[m.group(1)] = (n, m.group(2))
    return out


def _compose_value(rhs: str) -> str:
    """Resolve a raw right-hand side the way compose-go's dotenv parser would."""
    value = rhs.lstrip(_COMPOSE_WHITESPACE)
    if value[:1] in ('"', "'"):
        # quoted values are a different code path; .env.example uses none
        return value
    value, _, _ = value.partition(" #")
    return value.rstrip(_COMPOSE_WHITESPACE)


def test_no_assignment_line_carries_an_inline_comment() -> None:
    offenders = [(n, key, rhs) for key, (n, rhs) in _assignments().items() if "#" in rhs]
    assert not offenders, (
        "inline `#` after a value — move the comment to its own line above "
        f"(issue #458): {[f'L{n} {k}' for n, k, _ in offenders]}"
    )


def test_no_value_resolves_to_comment_text_under_compose() -> None:
    leaked = {
        key: _compose_value(rhs)
        for key, (_, rhs) in _assignments().items()
        if _compose_value(rhs).startswith("#") or " #" in _compose_value(rhs)
    }
    assert not leaked, f"compose would read these as comment text: {leaked}"


def test_previously_broken_keys_now_resolve_empty() -> None:
    values = _assignments()
    for key in _PREVIOUSLY_BROKEN:
        assert key in values, f"{key} vanished from .env.example"
        n, rhs = values[key]
        assert _compose_value(rhs) == "", f"L{n} {key} -> {_compose_value(rhs)!r}, expected empty"
