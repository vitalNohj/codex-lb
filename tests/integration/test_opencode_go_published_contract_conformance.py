"""Conformance of the shipped code to the two published sibling contracts.

The backend lane published ``contract.md`` and the quota lane published
``quota-contract.md``. Both are interface promises that five other lanes are
building against, so the promises themselves need to be executable rather than
prose the implementations may quietly drift from.

Each test below is skipped while the module it checks does not exist, and is
**strict** the moment it does. That is deliberate: a conformance test that
passes vacuously forever is worse than no test, so every skip names the exact
missing symbol, and the suite as a whole reports how much of each contract is
actually live (``test_contract_coverage_is_reported_honestly``).

One conflict between the two published contracts is encoded here as a failing
condition rather than resolved unilaterally - see
``test_the_two_contracts_agree_on_the_settings_column_names``. Resolving it is
the owning lanes' call, coordinated through Firstmate; detecting it is this
lane's job.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest

pytestmark = pytest.mark.integration


def _try_import(module: str) -> Any | None:
    try:
        return importlib.import_module(module)
    except ModuleNotFoundError:
        return None


def _require(module: str) -> Any:
    loaded = _try_import(module)
    if loaded is None:
        pytest.skip(f"not implemented yet: {module}")
    return loaded


# ---------------------------------------------------------------------------
# contract.md section 1: exact identifier strings
# ---------------------------------------------------------------------------

# Copied verbatim from contract.md section 1. Paraphrasing any of these would
# defeat the point: five lanes are keying off the exact spelling.
PROVIDER_KEY = "opencode_go"
LOG_SOURCE = "opencode_go_sidecar"
ACCOUNT_ID = "opencode-go-sidecar"
MODEL_PREFIX = "opencode-go/"
DEFAULT_BASE_URL = "https://opencode.ai/zen/go/v1"


def test_the_routing_provider_id_is_registered_with_the_exact_contract_spelling():
    from app.modules.proxy.sidecar_routing import SIDECAR_PROVIDER_ORDER

    if PROVIDER_KEY not in SIDECAR_PROVIDER_ORDER:
        pytest.skip("not implemented yet: opencode_go in SIDECAR_PROVIDER_ORDER")

    # contract.md section 11: appended AFTER ollama, so the deterministic
    # tiebreak cannot change any existing provider's precedence.
    assert SIDECAR_PROVIDER_ORDER.index(PROVIDER_KEY) > SIDECAR_PROVIDER_ORDER.index("ollama")


def test_existing_provider_order_is_not_disturbed_by_the_new_entry():
    """Regression guard that is meaningful today, before the Go code lands."""
    from app.modules.proxy.sidecar_routing import SIDECAR_PROVIDER_ORDER

    existing = [p for p in SIDECAR_PROVIDER_ORDER if p != PROVIDER_KEY]
    assert existing == ["claude", "openrouter", "orcarouter", "omniroute", "ollama"], (
        "the relative order of the existing integrations is load-bearing for "
        "prefix tiebreaks and must not be reshuffled to insert a new provider"
    )


def test_the_pricing_provider_key_and_log_source_are_registered_together():
    from app.core.usage.external_pricing import providers

    if not hasattr(providers, "PROVIDER_OPENCODE_GO"):
        pytest.skip("not implemented yet: PROVIDER_OPENCODE_GO")

    assert providers.PROVIDER_OPENCODE_GO == PROVIDER_KEY
    assert providers.PROVIDER_OPENCODE_GO in providers.EXTERNAL_PRICED_PROVIDERS
    # contract.md section 5 item 2: both halves, or a priced request cannot be
    # traced from its log row back to the provider that owns its cost.
    assert LOG_SOURCE in providers.EXTERNAL_PRICED_LOG_SOURCES
    assert providers.external_priced_provider_for_log_source(LOG_SOURCE) == PROVIDER_KEY


def test_the_underscore_spelling_of_the_prefix_does_not_route():
    """contract.md section 1 records this as a correction verified by test.

    ``prefix_variants`` interchanges ``-``/``_`` only when the separator is the
    prefix's final character. ``opencode-go/`` ends in ``/``, so its hyphen is
    literal and ``opencode_go/glm-5.3`` must not resolve. The UI has to present
    the prefix exactly, so this is a user-visible promise.
    """
    from app.modules.proxy.sidecar_routing import prefix_variants

    variants = prefix_variants(MODEL_PREFIX)
    assert variants == (MODEL_PREFIX,)
    assert "opencode_go/" not in variants


# ---------------------------------------------------------------------------
# contract.md section 4: honest model advertisement
# ---------------------------------------------------------------------------


def test_the_model_protocol_map_classifies_every_id_and_advertises_only_chat():
    models = _try_import("app.modules.proxy.opencode_go_models")
    if models is None or not hasattr(models, "OPENCODE_GO_MODEL_PROTOCOLS"):
        pytest.skip("not implemented yet: OPENCODE_GO_MODEL_PROTOCOLS")

    protocols = models.OPENCODE_GO_MODEL_PROTOCOLS
    allowed = {"chat_completions", "messages", "responses", "unknown"}
    for model_id, entry in protocols.items():
        protocol = entry if isinstance(entry, str) else entry.get("protocol")
        assert protocol in allowed, f"{model_id} carries an unrecognized protocol {protocol!r}"

    # contract.md section 4: exactly the /chat/completions ids are dispatchable
    # at this milestone. A /messages or /responses id marked supported would be
    # advertising a combination nobody has tested.
    for model_id, entry in protocols.items():
        if isinstance(entry, dict) and "supported" in entry:
            if entry["supported"]:
                assert entry.get("protocol") == "chat_completions", (
                    f"{model_id} is advertised as supported on {entry.get('protocol')!r}; "
                    "only chat_completions is dispatchable at this milestone"
                )


def test_the_privacy_sensitive_models_are_flagged_and_not_dispatchable():
    """Training-enabled, non-ZDR models must not be silently enabled."""
    models = _try_import("app.modules.proxy.opencode_go_models")
    if models is None or not hasattr(models, "OPENCODE_GO_MODEL_PROTOCOLS"):
        pytest.skip("not implemented yet: OPENCODE_GO_MODEL_PROTOCOLS")

    protocols = models.OPENCODE_GO_MODEL_PROTOCOLS
    for model_id in ("muse-spark-1.3-contributor", "muse-spark-1.2-contributor"):
        entry = protocols.get(model_id)
        if entry is None or not isinstance(entry, dict):
            continue
        assert entry.get("supported") is not True, f"{model_id} must not be dispatchable"
        if "privacy_sensitive" in entry:
            assert entry["privacy_sensitive"] is True


def test_an_unknown_model_id_is_not_treated_as_chat_completions_by_default():
    """contract.md section 4.1: unknown must be visibly unavailable, not guessed.

    The most common Go bug in the surveyed prior art is exactly this - an
    unclassified id falling through to a default endpoint the provider does not
    serve it on.
    """
    models = _try_import("app.modules.proxy.opencode_go_models")
    if models is None or not hasattr(models, "protocol_for_model"):
        pytest.skip("not implemented yet: protocol_for_model")

    assert models.protocol_for_model("definitely-not-a-real-go-model") in {"unknown", None}


# ---------------------------------------------------------------------------
# contract.md section 6 / quota-contract.md section 6: the credential seam
# ---------------------------------------------------------------------------


def test_the_credential_is_decrypted_in_exactly_one_place():
    """contract.md section 6: "Do not invent credential storage."

    The guarantee has teeth only if there is one decryption site. Several would
    mean several places to get redaction, caching, and key rotation wrong.
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[2] / "app"
    go_files = [p for p in root.rglob("*opencode_go*.py")]
    if not go_files:
        pytest.skip("not implemented yet: no app/**/*opencode_go*.py")

    decrypting = [p for p in go_files if re.search(r"TokenEncryptor|\.decrypt\(", p.read_text())]
    assert len(decrypting) <= 1, (
        "the OpenCode Go credential is decrypted in more than one place: "
        f"{[p.name for p in decrypting]}; contract.md section 6 promises exactly one"
    )


def test_the_outbound_header_builder_sets_auth_and_an_honest_user_agent():
    client = _try_import("app.core.clients.opencode_go_sidecar")
    if client is None or not hasattr(client, "opencode_go_request_headers"):
        pytest.skip("not implemented yet: opencode_go_request_headers")

    config = client.OpenCodeGoSidecarConfig(
        enabled=True,
        base_url=DEFAULT_BASE_URL,
        api_key="sk-go-conformance-Zq7SvT2pLm9K",
        prefixes=(),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
    )
    headers = client.opencode_go_request_headers(config)

    assert headers["Authorization"] == "Bearer sk-go-conformance-Zq7SvT2pLm9K"
    user_agent = headers.get("User-Agent", "")
    # Go docs obligation 2, and the explicit non-reuse of the prior art's
    # impersonation workaround.
    assert user_agent.startswith("codex-lb/")
    assert "opencode-cli" not in user_agent
    assert "Mozilla" not in user_agent, "a browser user agent impersonation was copied from prior art"


def test_an_unconfigured_config_produces_no_authorization_header():
    client = _try_import("app.core.clients.opencode_go_sidecar")
    if client is None or not hasattr(client, "opencode_go_request_headers"):
        pytest.skip("not implemented yet: opencode_go_request_headers")

    config = client.OpenCodeGoSidecarConfig(
        enabled=True,
        base_url=DEFAULT_BASE_URL,
        api_key=None,
        prefixes=(),
        connect_timeout_seconds=8.0,
        request_timeout_seconds=600.0,
        models_cache_ttl_seconds=60.0,
    )
    assert "Authorization" not in client.opencode_go_request_headers(config)


def test_the_credential_scrubber_removes_an_echoed_key():
    client = _try_import("app.core.clients.opencode_go_sidecar")
    if client is None or not hasattr(client, "sanitize_opencode_go_message"):
        pytest.skip("not implemented yet: sanitize_opencode_go_message")

    key = "sk-go-conformance-Zq7SvT2pLm9K"
    echoed = f"Invalid credentials: Authorization: Bearer {key}"
    sanitized = client.sanitize_opencode_go_message(echoed, api_key=key)
    assert key not in sanitized
    # Still useful to an operator: scrubbing must not blank the whole message.
    assert "Invalid credentials" in sanitized


# ---------------------------------------------------------------------------
# contract.md section 1 + section 11: Go is not Zen, and stays off by default
# ---------------------------------------------------------------------------


def test_a_zen_base_url_is_rejected_rather_than_silently_billing_payg_credits():
    """contract.md section 1: the base URL must carry a ``/go/`` segment.

    A Go key pointed at the Zen path bills pay-as-you-go credits, and the two
    paths are reported not to share auth conventions. This is the one validation
    whose absence costs real money.
    """
    schemas = _try_import("app.modules.settings.schemas")
    validator = getattr(schemas, "_normalize_opencode_go_sidecar_base_url", None)
    if validator is None:
        pytest.skip("not implemented yet: _normalize_opencode_go_sidecar_base_url")

    assert validator(DEFAULT_BASE_URL) == DEFAULT_BASE_URL
    for rejected in ("https://opencode.ai/zen/v1", "https://opencode.ai/v1", "not-a-url", ""):
        with pytest.raises(ValueError):
            validator(rejected)


def test_the_integration_defaults_to_disabled_and_unconfigured():
    from app.db.models import DashboardSettings

    column_names = set(DashboardSettings.__table__.columns.keys())
    enabled_column = next((c for c in column_names if "opencode_go" in c and c.endswith("enabled")), None)
    if enabled_column is None:
        pytest.skip("not implemented yet: opencode_go enabled column")

    default = DashboardSettings.__table__.columns[enabled_column].default
    server_default = DashboardSettings.__table__.columns[enabled_column].server_default
    rendered = str(getattr(default, "arg", "")) + str(getattr(server_default, "arg", ""))
    assert "true" not in rendered.lower(), "OpenCode Go must ship disabled until deliberately enabled"


# ---------------------------------------------------------------------------
# Cross-contract consistency
# ---------------------------------------------------------------------------


def test_the_two_contracts_agree_on_the_settings_column_names():
    """A real, currently-open conflict between the two published contracts.

    ``contract.md`` section 1 declares the settings column prefix
    ``opencode_go_sidecar_`` and lists ``opencode_go_sidecar_enabled`` /
    ``opencode_go_sidecar_api_key_encrypted``. ``quota-contract.md`` section 6
    asks the backend for ``opencode_go_enabled`` /
    ``opencode_go_api_key_encrypted`` - the same two fields without ``sidecar``.
    The quota lane's own adapter says it reports ``not_configured`` until "the
    backend columns exist", so on the current spellings it would report
    not-configured against a fully configured integration.

    The column names are the backend lane's to choose. This test does not pick a
    winner; it fails if the shipped schema satisfies neither shape, and passes as
    soon as one consistent set exists, so the conflict cannot reach an operator
    as a permanently empty quota card.
    """
    from app.db.models import DashboardSettings

    columns = set(DashboardSettings.__table__.columns.keys())
    go_columns = {c for c in columns if "opencode_go" in c}
    if not go_columns:
        pytest.skip("not implemented yet: no opencode_go columns")

    sidecar_shape = {"opencode_go_sidecar_enabled", "opencode_go_sidecar_api_key_encrypted"}
    bare_shape = {"opencode_go_enabled", "opencode_go_api_key_encrypted"}
    assert sidecar_shape <= go_columns or bare_shape <= go_columns, (
        "neither published column shape is present. contract.md expects "
        f"{sorted(sidecar_shape)}; quota-contract.md expects {sorted(bare_shape)}; "
        f"the schema has {sorted(go_columns)}. The quota lane's adapter reads the "
        "second shape and will report not_configured against a configured "
        "integration until the two lanes agree."
    )


def test_the_quota_endpoint_never_carries_windows_for_a_no_data_status():
    """quota-contract.md section 2.1: only ``ok`` and ``stale`` carry windows.

    Every other status must carry ``windows: []``, meaning unknown - not zero
    and not full. This is the single rule that keeps an operator from reading a
    failed usage fetch as an exhausted subscription.
    """
    schemas = _try_import("app.modules.opencode_go_quota.schemas")
    if schemas is None:
        schemas = _try_import("app.modules.opencode_go.quota_schemas")
    if schemas is None:
        pytest.skip("not implemented yet: opencode go quota schemas")

    builder = getattr(schemas, "quota_response_for_status", None)
    if builder is None:
        pytest.skip("not implemented yet: quota_response_for_status")

    for status in ("disabled", "not_configured", "unauthorized", "rate_limited", "unavailable"):
        response = builder(status)
        assert response.windows == [], f"status={status} must carry no windows"
        assert response.models == []
        assert response.model_breakdown_available is False


def test_the_quota_scope_is_reported_as_unknown_rather_than_guessed():
    """quota-contract.md sections 2.2 and 3: no manufactured granularity.

    Nobody has established whether the usage windows are per-model or
    account-wide, so neither label may be emitted from the current parser.
    """
    service = _try_import("app.modules.opencode_go_quota.service")
    if service is None:
        pytest.skip("not implemented yet: opencode go quota service")

    parser = getattr(service, "parse_usage_payload", None)
    if parser is None:
        pytest.skip("not implemented yet: parse_usage_payload")

    parsed = parser(
        {
            "usage": {
                "rolling": {"status": "ok", "percent": 42, "resetsAt": 1789360000000},
                "weekly": {"status": "ok", "percent": 13, "resetsAt": 1789900000000},
                "monthly": {"status": "ok", "percent": 4, "resetsAt": 1792000000000},
            }
        }
    )
    assert parsed.scope == "unknown", (
        "the upstream payload carries three unlabelled windows and no model "
        "dimension; labelling it account-wide or per-model manufactures a fact"
    )
    assert parsed.model_breakdown_available is False


def test_contract_coverage_is_reported_honestly(capsys):
    """Prints which contract surfaces exist, so skips are never mistaken for passes.

    Without this, a fully-skipped conformance suite reports green and reads as
    "the contracts are satisfied" when it means "none of it is built yet".
    """
    surfaces = {
        "backend client": "app.core.clients.opencode_go_sidecar",
        "backend dispatch": "app.modules.proxy.opencode_go_sidecar_dispatch",
        "model protocol map": "app.modules.proxy.opencode_go_models",
        "session resolution": "app.modules.proxy.opencode_go_session",
        "dashboard api": "app.modules.opencode_go_sidecar.api",
        "accounts summary": "app.modules.accounts.opencode_go_sidecar_summary",
    }
    live = {name: _try_import(module) is not None for name, module in surfaces.items()}
    with capsys.disabled():
        print("\nOpenCode Go contract surfaces present in this build:")
        for name, present in live.items():
            print(f"  [{'x' if present else ' '}] {name} ({surfaces[name]})")
        print(f"  {sum(live.values())}/{len(live)} implemented\n")

    # Always passes; it is a report, not a gate. The gates are the strict-when-
    # present tests above.
    assert set(live) == set(surfaces)
