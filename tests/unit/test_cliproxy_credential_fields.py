from __future__ import annotations

import pytest

from app.core.exceptions import DashboardBadRequestError
from app.modules.claude_sidecar.quota import SidecarAuthQuota
from app.modules.cliproxy_accounts.validation import (
    disabling_last_enabled_account,
    validate_excluded_models,
    validate_priority,
    validate_weight,
)

pytestmark = pytest.mark.unit


def _auth(name: str, *, disabled: bool = False) -> SidecarAuthQuota:
    return SidecarAuthQuota(
        name=name,
        auth_index="1",
        email=None,
        provider="xai",
        status="active",
        status_message=None,
        disabled=disabled,
        unavailable=False,
        quota_exceeded=False,
        next_recover_at=None,
        model_states=(),
        success=0,
        failed=0,
        last_refresh=None,
        prefix=None,
    )


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


def test_only_disabling_the_last_enabled_account_needs_confirmation():
    accounts = (_auth("one"), _auth("two", disabled=True))

    assert disabling_last_enabled_account(accounts, name="one", disabled=True) is True
    assert disabling_last_enabled_account(accounts, name="two", disabled=True) is False
    assert disabling_last_enabled_account(accounts, name="one", disabled=False) is False
    assert disabling_last_enabled_account((_auth("one"), _auth("two")), name="one", disabled=True) is False
