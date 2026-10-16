"""Map CLIProxyAPI OAuth payloads onto the panel's sign-in state machine.

Upstream responses can carry tokens. These functions copy only the fields the
dialog needs.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Literal
from urllib.parse import urlsplit

from app.core.exceptions import DashboardBadRequestError, DashboardUpstreamError
from app.core.types import JsonValue
from app.core.utils.json_guards import is_json_mapping
from app.modules.cliproxy_accounts.providers import OauthMethod, OauthProvider
from app.modules.cliproxy_accounts.redaction import public_message
from app.modules.cliproxy_accounts.schemas import (
    CliproxyOauthCallbackResponse,
    CliproxyOauthCancelResponse,
    CliproxyOauthStartResponse,
    CliproxyOauthStatus,
    CliproxyOauthStatusResponse,
)

_STATE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_USER_CODE = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_POLL_SECONDS = 2
_MAX_CALLBACK_URL = 4096

PanelOauthStatus = Literal["pending", "success", "error"]
_completed_states: set[str] = set()
_providers_by_state: dict[str, str] = {}


def reset_oauth_completion() -> None:
    _completed_states.clear()
    _providers_by_state.clear()


def remember_oauth_provider(state: str, provider: str) -> None:
    if len(_providers_by_state) > 1024:
        _providers_by_state.clear()
    _providers_by_state[state] = provider


def remembered_oauth_provider(state: str) -> str | None:
    return _providers_by_state.get(state)


def claim_oauth_completion(state: str) -> bool:
    """Return whether this is the first time ``state`` reached success."""

    if state in _completed_states:
        return False
    if len(_completed_states) > 1024:
        _completed_states.clear()
    _completed_states.add(state)
    return True


def validate_oauth_state(state: str) -> str:
    trimmed = state.strip()
    if ".." in trimmed or _STATE.fullmatch(trimmed) is None:
        raise DashboardBadRequestError("Invalid sign-in state")
    return trimmed


def project_start(provider: OauthProvider, payload: Mapping[str, JsonValue]) -> CliproxyOauthStartResponse:
    if not is_json_mapping(payload):
        raise DashboardUpstreamError("CLIProxyAPI sign-in response could not be read")
    state = payload.get("state")
    if not isinstance(state, str):
        raise DashboardUpstreamError("CLIProxyAPI sign-in response did not include a state")
    try:
        safe_state = validate_oauth_state(state)
    except DashboardBadRequestError as exc:
        raise DashboardUpstreamError("CLIProxyAPI sign-in response included an unusable state") from exc
    url = _http_url(payload.get("url"))
    method = _method(provider, payload.get("flow"))
    user_code = _user_code(payload.get("user_code"))
    return CliproxyOauthStartResponse(
        state=safe_state,
        provider=provider.panel,
        method=method,
        authorization_url=url if method == "browser" else None,
        verification_url=url if method == "device" else None,
        user_code=user_code,
        interval_seconds=_POLL_SECONDS,
        expires_in_seconds=_expires_in(payload.get("expires_in")),
    )


def project_status(payload: Mapping[str, JsonValue]) -> CliproxyOauthStatusResponse:
    status, message = _status(payload)
    return CliproxyOauthStatusResponse(status=status, error_message=message)


def project_cancel(payload: Mapping[str, JsonValue]) -> CliproxyOauthCancelResponse:
    cancelled = is_json_mapping(payload) and payload.get("cancelled") is True
    return CliproxyOauthCancelResponse(status="ok", cancelled=cancelled)


def callback_body(provider: OauthProvider, state: str, callback_url: str) -> dict[str, JsonValue]:
    """Build the CLIProxyAPI callback body without keeping the URL around.

    The pasted URL can carry an authorization code. It is forwarded once and
    is not returned to the panel.
    """

    trimmed = callback_url.strip()
    if not trimmed or len(trimmed) > _MAX_CALLBACK_URL:
        raise DashboardBadRequestError("Sign-in callback must be an http(s) URL")
    parsed = urlsplit(trimmed)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise DashboardBadRequestError("Sign-in callback must be an http(s) URL")
    return {
        "provider": provider.callback_provider,
        "state": state,
        "redirect_url": trimmed,
    }


def project_callback(payload: Mapping[str, JsonValue]) -> CliproxyOauthCallbackResponse:
    """An accepted callback is still pending until ``get-auth-status`` says ok.

    CLIProxyAPI writes the callback and finishes the token exchange in the
    background. ``status: ok`` here means the callback was stored, not that a
    credential file exists yet.
    """

    if not is_json_mapping(payload):
        return CliproxyOauthCallbackResponse(status="error", error_message="Sign-in callback could not be read")
    status = payload.get("status")
    if status == "ok":
        return CliproxyOauthCallbackResponse(status="pending")
    if status == "error":
        error = payload.get("error")
        message = error if isinstance(error, str) and error.strip() else "Sign-in callback was rejected"
        return CliproxyOauthCallbackResponse(status="error", error_message=public_message(message))
    return CliproxyOauthCallbackResponse(status="error", error_message="Sign-in callback could not be read")


def _status(payload: Mapping[str, JsonValue]) -> tuple[CliproxyOauthStatus, str | None]:
    if not is_json_mapping(payload):
        return "error", "Sign-in status could not be read"
    status = payload.get("status")
    if status == "wait":
        return "pending", None
    if status == "ok":
        return "success", None
    if status == "error":
        error = payload.get("error")
        message = error if isinstance(error, str) and error.strip() else "Sign-in failed"
        return "error", public_message(message)
    return "error", "Sign-in status could not be read"


def _method(provider: OauthProvider, flow: JsonValue | None) -> OauthMethod:
    if flow == "device":
        return "device"
    if flow == "browser":
        return "browser"
    return provider.method


def _http_url(value: JsonValue | None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DashboardUpstreamError("CLIProxyAPI sign-in response did not include a URL")
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise DashboardUpstreamError("CLIProxyAPI returned a sign-in URL the panel cannot use")
    return value.strip()


def _user_code(value: JsonValue | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _USER_CODE.fullmatch(value.strip()) is None:
        raise DashboardUpstreamError("CLIProxyAPI returned a sign-in code the panel cannot show")
    return value.strip()


def _expires_in(value: JsonValue | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0 or value > 86_400:
        return None
    return value
