"""CLIProxyAPI OAuth providers the panel can sign in.

The panel slug is what the dashboard shows. ``callback_provider`` is the value
CLIProxyAPI records on the OAuth session, which is ``anthropic`` for Claude.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

OauthMethod = Literal["browser", "device"]


@dataclass(frozen=True, slots=True)
class OauthProvider:
    panel: str
    management_path: str
    callback_provider: str
    method: OauthMethod


_PROVIDERS: dict[str, OauthProvider] = {
    provider.panel: provider
    for provider in (
        OauthProvider("claude", "/v0/management/anthropic-auth-url", "anthropic", "browser"),
        OauthProvider("anthropic", "/v0/management/anthropic-auth-url", "anthropic", "browser"),
        OauthProvider("codex", "/v0/management/codex-auth-url", "codex", "browser"),
        OauthProvider("antigravity", "/v0/management/antigravity-auth-url", "antigravity", "browser"),
        OauthProvider("devin", "/v0/management/devin-auth-url", "devin", "browser"),
        OauthProvider("xai", "/v0/management/xai-auth-url", "xai", "device"),
        OauthProvider("meta", "/v0/management/meta-auth-url", "meta", "device"),
        OauthProvider("kimi", "/v0/management/kimi-auth-url", "kimi", "device"),
        OauthProvider("kimi-ai", "/v0/management/kimi-ai-auth-url", "kimi-ai", "device"),
    )
}

UPLOAD_TYPES = frozenset(_PROVIDERS)


def oauth_provider(slug: str) -> OauthProvider | None:
    return _PROVIDERS.get(slug.strip().lower())


def panel_oauth_providers() -> tuple[OauthProvider, ...]:
    """Providers the sign-in dialog offers, one row per CLIProxyAPI auth URL."""

    seen: set[str] = set()
    ordered: list[OauthProvider] = []
    for provider in _PROVIDERS.values():
        if provider.management_path in seen:
            continue
        seen.add(provider.management_path)
        ordered.append(provider)
    return tuple(ordered)
