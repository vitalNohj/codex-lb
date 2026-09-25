"""The API key a proxy request authenticated with, carried on the ASGI scope.

A leaf module on purpose: the proxy auth dependency writes the value and
response middleware reads it, and neither may import the other.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from starlette.types import Scope

if TYPE_CHECKING:
    from app.modules.api_keys.service import ApiKeyData

_AUTHENTICATED_API_KEY_STATE: Final = "codex_lb_authenticated_api_key"


def set_authenticated_api_key(scope: Scope, api_key: ApiKeyData | None) -> None:
    """Record the request's API key on ``scope["state"]``.

    Starlette's ``request.state`` is a view over ``scope["state"]``, so the
    value stays visible to middleware after the route has returned.
    """

    state = scope.setdefault("state", {})
    state[_AUTHENTICATED_API_KEY_STATE] = api_key


def get_authenticated_api_key(scope: Scope) -> ApiKeyData | None:
    state = scope.get("state")
    if not isinstance(state, dict):
        return None
    return state.get(_AUTHENTICATED_API_KEY_STATE)
