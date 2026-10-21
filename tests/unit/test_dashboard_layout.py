from __future__ import annotations

import json

import pytest
from sqlalchemy.dialects import sqlite

from app.db.models import DashboardSettings
from app.modules.settings.dashboard_layout import (
    DEFAULT_DASHBOARD_LAYOUT_JSON,
    DashboardLayoutVisibility,
    dump_dashboard_layout,
    merge_dashboard_layout,
    parse_dashboard_layout,
    sql_dashboard_layout_default,
)
from app.modules.settings.schemas import DashboardLayoutVisibilitySchema, DashboardLayoutVisibilityUpdate

pytestmark = pytest.mark.unit


def test_default_layout_hides_only_active_conversations() -> None:
    layout = DashboardLayoutVisibility()

    assert layout.conversations is False
    assert layout.requests is True
    assert layout.tokens is True
    assert layout.estimated_cost is True
    assert layout.error_rate is True
    assert layout.usage is True
    assert layout.accounts is True
    assert layout.request_logs is True
    assert json.loads(DEFAULT_DASHBOARD_LAYOUT_JSON)["conversations"] is False
    assert DashboardSettings.dashboard_layout_json.default.arg == DEFAULT_DASHBOARD_LAYOUT_JSON
    # text() would compile :true/:false as binds and persist NULL. The stored
    # DDL literal has to keep the JSON booleans.
    default_sql = str(
        DashboardSettings.__table__.c.dashboard_layout_json.server_default.arg.compile(dialect=sqlite.dialect())
    )
    assert default_sql == sql_dashboard_layout_default()
    assert ":true" in default_sql
    assert ":false" in default_sql
    assert "NULL" not in default_sql


def test_parse_dashboard_layout_keeps_defaults_for_unset_and_missing_keys() -> None:
    assert parse_dashboard_layout(None) == DashboardLayoutVisibility()
    assert parse_dashboard_layout("") == DashboardLayoutVisibility()

    parsed = parse_dashboard_layout('{"requests":false}')

    assert parsed.requests is False
    assert parsed.conversations is False
    assert parsed.tokens is True


def test_parse_dashboard_layout_rejects_corrupt_values() -> None:
    with pytest.raises(ValueError, match="must be an object"):
        parse_dashboard_layout("[]")
    with pytest.raises(ValueError, match="conversations must be a boolean"):
        parse_dashboard_layout('{"conversations":"yes"}')


def test_merge_dashboard_layout_updates_only_the_supplied_flags() -> None:
    merged = merge_dashboard_layout(DashboardLayoutVisibility(), {"conversations": True, "request_logs": False})

    assert merged.conversations is True
    assert merged.request_logs is False
    assert merged.requests is True
    assert parse_dashboard_layout(dump_dashboard_layout(merged)) == merged


def test_merge_dashboard_layout_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError, match="unknown dashboard layout field"):
        merge_dashboard_layout(DashboardLayoutVisibility(), {"active_conversations": False})


def test_settings_schema_round_trips_camel_case_and_defaults_conversations_off() -> None:
    response = DashboardLayoutVisibilitySchema().model_dump(by_alias=True)

    assert response["conversations"] is False
    assert response["estimatedCost"] is True
    assert response["requestLogs"] is True
    assert "estimated_cost" not in response

    patch = DashboardLayoutVisibilityUpdate.model_validate({"conversations": True})

    assert patch.model_fields_set == {"conversations"}
    assert patch.conversations is True
