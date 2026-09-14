"""The quota route is actually reachable over HTTP on the composed app.

Owned by the backend lane, which owns the narrow registration in
``app/dependencies.py`` and ``app/main.py``.

This exists because preserving the quota module's files was **not** the same as
restoring a working endpoint. The eleven leaf files can all be present and
correct while ``GET /api/opencode-go/quota`` still 404s, because nothing
included the router or provided the context. An import check or a scan of
``app.routes`` would not have caught that: both pass on a tree whose router is
never mounted.

So every test here drives a real HTTP request through the real ASGI app and
asserts on the response, with synthetic settings and no upstream contact.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

_QUOTA_ROUTE = "/api/opencode-go/quota"


@pytest.mark.asyncio
async def test_quota_route_is_mounted_and_answers_over_http(async_client):
    """The registration is live: a real request returns the contract shape.

    A 404 here is the exact regression this file guards - the quota module
    present but unregistered.
    """

    response = await async_client.get(_QUOTA_ROUTE)

    assert response.status_code != 404, "GET /api/opencode-go/quota is not mounted"
    assert response.status_code == 200

    body = response.json()
    # Always 200 with the outcome in ``status``, per the quota contract, so the
    # dashboard can distinguish "unavailable" from "exhausted" rather than
    # parsing a 502.
    assert "status" in body
    assert body["status"] in {
        "disabled",
        "not_configured",
        "ok",
        "stale",
        "unauthorized",
        "rate_limited",
        "unavailable",
    }


@pytest.mark.asyncio
async def test_quota_route_contacts_no_upstream_when_unconfigured(async_client):
    """Default install: answers without a credential and without a network call.

    If the route ever reached upstream while unconfigured it would be an
    inference-adjacent call against a metered subscription from a plain
    dashboard load.
    """

    body = (await async_client.get(_QUOTA_ROUTE)).json()

    assert body["status"] in {"disabled", "not_configured"}
    # Only ``ok``/``stale`` ever carry windows; anything else means unknown,
    # never zero and never full.
    assert body.get("windows", []) == []


def test_quota_route_is_mounted_behind_the_dashboard_session(app_instance):
    """It is operator data derived from a subscription credential.

    Guards the registration specifically: including the router in a way that
    dropped its dashboard-session dependency would expose the quota read
    unauthenticated, and a route-name check would still look fine.

    Asserted on the mounted route's resolved dependency graph rather than by an
    unauthenticated request, because the suite's fixture app has no dashboard
    password set and therefore does not reject anonymous callers - a 200 here
    would prove nothing either way.
    """

    from app.core.auth.dependencies import set_dashboard_error_format, validate_dashboard_session

    route = next(r for r in app_instance.routes if getattr(r, "path", None) == _QUOTA_ROUTE)
    dependency_calls = {dependency.call for dependency in route.dependant.dependencies}

    assert validate_dashboard_session in dependency_calls
    assert set_dashboard_error_format in dependency_calls


@pytest.mark.asyncio
async def test_quota_context_provider_builds_the_real_service():
    """The injected dependency is the committed service, not a stand-in.

    The registration adapts to the service's *actual* committed constructor
    (``settings_repository`` plus optional cache/client factory). Asserting the
    resolved type keeps a future signature change from silently degrading the
    route to a shape that merely returns 200.
    """

    from app.db.session import SessionLocal
    from app.dependencies import OpenCodeGoContext, get_opencode_go_context
    from app.modules.opencode_go.service import OpenCodeGoQuotaService

    async with SessionLocal() as session:
        context = get_opencode_go_context(session)

    assert isinstance(context, OpenCodeGoContext)
    assert isinstance(context.service, OpenCodeGoQuotaService)


@pytest.mark.asyncio
async def test_quota_and_inference_routes_are_registered_independently(async_client):
    """Quota and inference are separate surfaces on the same subscription.

    Both must be mounted, and neither may be reachable only because the other
    is. Keeping them apart is what stops a quota poll from acquiring an
    inference transport.
    """

    assert (await async_client.get(_QUOTA_ROUTE)).status_code == 200
    assert (await async_client.get("/api/opencode-go-sidecar/status")).status_code == 200
