"""Credential redaction for the text sidecar health checks persist and serve.

Reported on https://github.com/vitalNohj/codex-lb/pull/59: the generic
OpenAI-compat service (and the since-removed NVIDIA clone) replaced only the literal ``"Bearer "``
prefix, so an upstream echoing the Authorization header produced
``Bearer [redacted]<the-key>`` - the key survived intact. That text is persisted
to the recorded health message and returned verbatim by the status and test APIs,
so the redaction is the only thing standing between an echoing upstream and an
operator-visible credential.

The service now delegates to the project's existing credential-aware sanitizer, which is
also what free-model discovery reuses for non-OrcaRouter providers (see
``app/modules/free_model_discovery/probe.redact_provider_text``).
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from app.modules.openai_compat.service import _sanitize_message as sanitize_openai_compat_message

pytestmark = pytest.mark.unit

_SANITIZERS: tuple[tuple[str, Callable[..., str]], ...] = (("openai_compat", sanitize_openai_compat_message),)


@pytest.fixture(params=_SANITIZERS, ids=[name for name, _ in _SANITIZERS])
def sanitize(request: pytest.FixtureRequest) -> Callable[..., str]:
    _, func = request.param
    return func


@pytest.mark.parametrize(
    "key",
    [
        pytest.param("nvapi-7fQ2xLm9ZbT4vR1nK8sYpWcE", id="nvidia-shaped"),
        pytest.param("sk-proj-abc123DEF456", id="openai-shaped"),
        pytest.param("a1b2c3d4e5f6a7b8", id="opaque-hex"),
    ],
)
def test_an_echoed_bearer_credential_is_replaced_whole(sanitize, key: str) -> None:
    """The whole token goes, not just the word in front of it.

    The old implementation returned ``Bearer [redacted]<key>``: it inserted the
    marker and left the secret immediately after it, which is worse than no
    redaction at all because the message now *looks* redacted.
    """

    sanitized = sanitize(f"401 Unauthorized: Bearer {key} rejected", api_key=key)

    assert key not in sanitized
    assert "[redacted]" in sanitized


def test_the_credential_is_removed_even_when_it_is_not_the_configured_one(sanitize) -> None:
    """A rotated key the upstream still echoes must not leak either.

    The ``Bearer`` pattern runs unconditionally, so redaction does not depend on
    the echoed value still matching what is configured.
    """

    sanitized = sanitize("upstream said: Bearer nvapi-stale-key-9f2a is revoked", api_key="nvapi-current-key")

    assert "nvapi-stale-key-9f2a" not in sanitized


def test_a_bare_echo_of_the_configured_key_is_removed(sanitize) -> None:
    """Some upstreams echo the key with no ``Bearer`` in front of it at all."""

    key = "nvapi-7fQ2xLm9ZbT4vR1nK8sYpWcE"

    sanitized = sanitize(f"invalid api key {key}", api_key=key)

    assert key not in sanitized


def test_ordinary_upstream_prose_survives_unchanged(sanitize) -> None:
    """Redaction must not garble the message an operator has to act on.

    A credential-free diagnostic is the common case; mangling it would trade one
    unreadable surface for another.
    """

    message = "Failed to fetch models: Connection refused to vllm.internal:8000"

    assert sanitize(message, api_key="nvapi-7fQ2xLm9ZbT4vR1nK8sYpWcE") == message


def test_redaction_still_applies_with_no_configured_credential(sanitize) -> None:
    """A missing configured key weakens redaction but must not disable it.

    ``api_key`` defaults to ``None`` on paths that have not decrypted one, and an
    echoed bearer token is still a credential there.
    """

    sanitized = sanitize("Bearer nvapi-7fQ2xLm9ZbT4vR1nK8sYpWcE rejected")

    assert "nvapi-7fQ2xLm9ZbT4vR1nK8sYpWcE" not in sanitized
