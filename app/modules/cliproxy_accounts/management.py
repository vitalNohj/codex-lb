"""CLIProxyAPI management calls for sign-in, refresh, upload, and delete.

Responses are returned to the service, which copies the few fields the panel
is allowed to see. This client does not log response bodies.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import cast
from urllib.parse import quote

import aiohttp

from app.core.clients.claude_sidecar import ClaudeSidecarClient, ClaudeSidecarError, ClaudeSidecarUnavailableError
from app.core.clients.http import lease_http_session
from app.core.types import JsonValue
from app.core.utils.json_guards import is_json_mapping
from app.modules.cliproxy_accounts.redaction import public_message


def build_management(client: ClaudeSidecarClient) -> CliproxyManagement:
    return CliproxyManagement(client)


class CliproxyManagement:
    def __init__(self, client: ClaudeSidecarClient) -> None:
        self._client = client

    async def start_oauth(self, path: str) -> Mapping[str, JsonValue]:
        return await self._request("GET", path)

    async def auth_status(self, state: str) -> Mapping[str, JsonValue]:
        return await self._request("GET", f"/v0/management/get-auth-status?state={quote(state, safe='')}")

    async def cancel_oauth(self, state: str) -> Mapping[str, JsonValue]:
        return await self._request("DELETE", f"/v0/management/oauth-session?state={quote(state, safe='')}")

    async def submit_callback(self, payload: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
        return await self._request("POST", "/v0/management/oauth-callback", json_body=dict(payload))

    async def delete_auth_file(self, name: str) -> None:
        await self._request("DELETE", f"/v0/management/auth-files?name={quote(name, safe='')}")

    async def refresh_auth_file(self, name: str, auth_index: str | None) -> None:
        body: dict[str, JsonValue] = {"name": name}
        if auth_index:
            body["auth_index"] = auth_index
        # The upstream body includes the refreshed auth, tokens included.
        # Discard it. The panel polls our own status record instead.
        await self._request("POST", "/v0/management/auth-files/refresh", json_body=body)

    async def upload_auth_file(self, name: str, data: bytes) -> None:
        await self._request(
            "POST",
            f"/v0/management/auth-files?name={quote(name, safe='')}",
            raw_body=data,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Mapping[str, JsonValue] | None = None,
        raw_body: bytes | None = None,
    ) -> Mapping[str, JsonValue]:
        url = f"{self._client.base_url}{path}"
        headers = _headers(self._client)
        if raw_body is not None:
            headers["Content-Type"] = "application/json"
        try:
            async with lease_http_session() as session:
                response_cm = _open(session, method, url, headers, self._client, json_body, raw_body)
                async with response_cm as resp:
                    data = await _read_json(resp)
                    if resp.status >= 400:
                        raise ClaudeSidecarError(resp.status, _error_message(resp.status, data))
        except ClaudeSidecarError:
            raise
        except (asyncio.TimeoutError, aiohttp.ClientError, OSError) as exc:
            detail = str(exc) or exc.__class__.__name__
            raise ClaudeSidecarUnavailableError(public_message(f"Failed to call CLIProxyAPI: {detail}")) from exc
        if data is None:
            return {}
        if not is_json_mapping(data):
            raise ClaudeSidecarError(502, "CLIProxyAPI returned a response the panel cannot read")
        return data


def _headers(client: ClaudeSidecarClient) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "codex-lb/claude-sidecar-management",
    }
    management_key = (client.config.management_key or "").strip()
    if management_key:
        headers["Authorization"] = f"Bearer {management_key}"
    return headers


def _open(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    headers: Mapping[str, str],
    client: ClaudeSidecarClient,
    json_body: Mapping[str, JsonValue] | None,
    raw_body: bytes | None,
) -> aiohttp.client._RequestContextManager:
    timeout = aiohttp.ClientTimeout(
        total=client.config.request_timeout_seconds,
        connect=client.config.connect_timeout_seconds,
        sock_connect=client.config.connect_timeout_seconds,
    )
    if method == "GET":
        return session.get(url, headers=dict(headers), timeout=timeout)
    if method == "DELETE":
        return session.delete(url, headers=dict(headers), timeout=timeout)
    if raw_body is not None:
        return session.post(url, headers=dict(headers), data=raw_body, timeout=timeout)
    payload = None if json_body is None else dict(json_body)
    return session.post(url, headers=dict(headers), json=payload, timeout=timeout)


async def _read_json(resp: aiohttp.ClientResponse) -> JsonValue | None:
    text = await resp.text()
    if not text:
        return None
    try:
        return cast(JsonValue, json.loads(text))
    except json.JSONDecodeError:
        return {"message": public_message(text[:200])}


def _error_message(status_code: int, body: JsonValue | None) -> str:
    if is_json_mapping(body):
        error = body.get("error")
        if isinstance(error, str) and error.strip():
            return public_message(error)
        if is_json_mapping(error):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return public_message(message)
    return f"CLIProxyAPI returned HTTP {status_code}"
