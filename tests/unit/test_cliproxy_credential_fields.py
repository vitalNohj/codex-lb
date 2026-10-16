from __future__ import annotations

import pytest

from app.core.exceptions import DashboardBadRequestError
from app.db.models import DashboardSettings
from app.modules.claude_sidecar.quota import SidecarAuthQuota
from app.modules.cliproxy_accounts.validation import (
    effective_prefixes,
    normalize_credential_prefix,
    prefix_conflict_message,
    routing_prefix_owners,
    validate_excluded_models,
    validate_priority,
    validate_weight,
)

pytestmark = pytest.mark.unit


def _auth(name: str, *, prefix: str | None = None) -> SidecarAuthQuota:
    return SidecarAuthQuota(
        name=name,
        auth_index="1",
        email=None,
        provider="xai",
        status="active",
        status_message=None,
        disabled=False,
        unavailable=False,
        quota_exceeded=False,
        next_recover_at=None,
        model_states=(),
        success=0,
        failed=0,
        last_refresh=None,
        prefix=prefix,
    )


def test_normalize_credential_prefix_accepts_short_slugs():
    assert normalize_credential_prefix(" acct2 ") == "acct2"
    assert normalize_credential_prefix("Acct10") == "acct10"


@pytest.mark.parametrize("raw", ["", "acct", "acct0", "claude", "acct1/grok", "acct 1", "acct-1"])
def test_normalize_credential_prefix_rejects_anything_else(raw: str):
    with pytest.raises(DashboardBadRequestError):
        normalize_credential_prefix(raw)


def test_weight_and_priority_bounds():
    assert validate_weight(0) == 0
    assert validate_priority(-5) == -5
    with pytest.raises(DashboardBadRequestError):
        validate_weight(True)  # type: ignore[arg-type]
    with pytest.raises(DashboardBadRequestError):
        validate_weight(1_000_001)
    with pytest.raises(DashboardBadRequestError):
        validate_priority(-1_000_001)


def test_excluded_models_must_already_be_normalized():
    assert validate_excluded_models(["grok-4", "other-*"]) == ("grok-4", "other-*")
    with pytest.raises(DashboardBadRequestError):
        validate_excluded_models(["grok-4,fast"])


def test_prefix_conflict_with_another_credential_and_an_orphan_registry_row():
    accounts = [_auth("live.json", prefix="acct2"), _auth("editing.json")]
    stored = {"gone.json": "acct3", "editing.json": "acct9"}

    occupied = effective_prefixes(accounts, stored)

    assert occupied["live.json"] == "acct2"
    assert occupied["gone.json"] == "acct3"
    assert occupied["editing.json"] == "acct9"
    assert (
        prefix_conflict_message(
            "acct3",
            credential_name="editing.json",
            effective=occupied,
            routing_owners={},
        )
        == "Prefix acct3 is already assigned to gone.json"
    )
    assert (
        prefix_conflict_message(
            "acct9",
            credential_name="editing.json",
            effective=occupied,
            routing_owners={},
        )
        is None
    )


def test_prefix_conflict_with_sidecar_routing_prefix_including_hyphen_twin():
    settings = DashboardSettings(
        id=1,
        claude_sidecar_model_prefixes_json=(
            '[{"prefix": "acct1", "strip": false}, {"prefix": "acct8-", "strip": false}]'
        ),
    )
    owners = routing_prefix_owners(settings)

    assert owners["acct1"] == "CLIProxyAPI"
    assert owners["acct8-"] == "CLIProxyAPI"
    assert owners["acct8_"] == "CLIProxyAPI"
    assert (
        prefix_conflict_message("acct1", credential_name="claude.json", effective={}, routing_owners=owners)
        == "Prefix acct1 clashes with the CLIProxyAPI routing prefix"
    )
    assert (
        prefix_conflict_message("acct8_", credential_name="claude.json", effective={}, routing_owners=owners)
        == "Prefix acct8_ clashes with the CLIProxyAPI routing prefix"
    )
    assert prefix_conflict_message("acct4", credential_name="claude.json", effective={}, routing_owners=owners) is None
