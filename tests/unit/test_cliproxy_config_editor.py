from __future__ import annotations

import pytest

from app.modules.cliproxy_accounts.config_editor import (
    REDACTED_CHANGED,
    REDACTED_PLACEHOLDER,
    REDACTION_MARK,
    CliproxyConfigPlaceholderError,
    CliproxyConfigYamlError,
    prepare_config_edit,
    redact_config_yaml,
    routing_flags,
)

pytestmark = pytest.mark.unit

_SECRET = "sk-live-config-secret"
_MANAGEMENT = "mgmt-live-secret"
_CLIENT_KEY = "client-live-key"
_GITHUB = "ghp-live-token"
_TURN_USER = "turn-live-user"
_TURN_SECRET = "turn-live-secret"
_PROXY = "socks5://proxy-user:proxy-pass@10.1.2.3:1080/"

_CONFIG = f"""\
config-version: 8
server:
  port: 8317
  github-token: "{_GITHUB}"
management:
  secret-key: "{_MANAGEMENT}"
access:
  api-keys:
    - "{_CLIENT_KEY}"
    - 424242
routing:
  strategy: round-robin
  session-affinity: true
requests:
  proxy-url: "{_PROXY}"
providers:
  codex:
    live-media-relay:
      ice-servers:
        - urls:
            - "turn:turn.example.com:3478"
            - "turn:{_TURN_USER}:{_TURN_SECRET}@turn.example.com:3478"
          username: "{_TURN_USER}"
          credential: "{_TURN_SECRET}"
debug: false
"""

_SECRETS = (_SECRET, _MANAGEMENT, _CLIENT_KEY, _GITHUB, _TURN_USER, _TURN_SECRET, "proxy-pass", "424242")


def test_redacts_api_keys_management_secret_tokens_and_turn_credentials() -> None:
    redacted = redact_config_yaml(_CONFIG)

    for secret in _SECRETS:
        assert secret not in redacted
    assert f"{REDACTION_MARK}:0»" in redacted
    assert "port: 8317" in redacted
    assert "session-affinity: true" in redacted
    assert "turn:turn.example.com:3478" in redacted
    assert "strategy: round-robin" in redacted


def test_placeholder_round_trip_keeps_the_existing_secret() -> None:
    redacted = redact_config_yaml(_CONFIG)
    submitted = redacted.replace("debug: false", "debug: true", 1)
    edit = prepare_config_edit(_CONFIG, submitted)

    assert edit.changed
    assert REDACTION_MARK not in edit.restored
    assert REDACTED_CHANGED not in edit.restored
    assert _CLIENT_KEY in edit.restored
    assert _MANAGEMENT in edit.restored
    assert _TURN_SECRET in edit.restored
    assert _PROXY in edit.restored
    assert "debug: true" in edit.restored
    assert "debug: false" not in edit.restored
    for secret in _SECRETS:
        assert secret not in edit.diff
    assert "debug: true" in edit.diff


def test_a_replaced_secret_is_written_and_stays_out_of_the_diff() -> None:
    redacted = redact_config_yaml(_CONFIG)
    submitted = redacted.replace(f'"{REDACTION_MARK}:0»"', '"brand-new-key"', 1)
    edit = prepare_config_edit(_CONFIG, submitted)

    assert "brand-new-key" in edit.restored
    assert "brand-new-key" not in edit.diff
    assert _CLIENT_KEY not in edit.diff
    assert REDACTED_CHANGED in edit.diff
    assert REDACTION_MARK not in edit.restored


def test_deleting_one_list_placeholder_keeps_the_other_secret() -> None:
    current = 'access:\n  api-keys:\n    - "first-key"\n    - "second-key"\n'
    redacted = redact_config_yaml(current)
    submitted = "".join(line for line in redacted.splitlines(keepends=True) if f"{REDACTION_MARK}:0»" not in line)
    edit = prepare_config_edit(current, submitted)

    assert "first-key" not in edit.restored
    assert '"second-key"' in edit.restored
    assert REDACTION_MARK not in edit.restored


def test_deleting_a_plain_turn_url_keeps_the_credential_url() -> None:
    current = """\
providers:
  codex:
    live-media-relay:
      ice-servers:
        - urls:
            - "turn:turn.example.com:3478"
            - "turn:turn-live-user:turn-live-secret@turn.example.com:3478"
"""
    redacted = redact_config_yaml(current)
    assert "turn-live-secret" not in redacted
    assert "turn:turn.example.com:3478" in redacted
    submitted = "".join(line for line in redacted.splitlines(keepends=True) if "turn:turn.example.com:3478" not in line)

    edit = prepare_config_edit(current, submitted)

    assert "turn:turn-live-user:turn-live-secret@turn.example.com:3478" in edit.restored
    assert "turn:turn.example.com:3478" not in edit.restored
    assert REDACTION_MARK not in edit.restored


def test_reordering_provider_entries_keeps_each_proxy_url() -> None:
    current = """\
providers:
  - name: first
    proxy-url: "socks5://alpha:alpha-pass@10.0.0.1:1080/"
  - name: second
    proxy-url: "socks5://beta:beta-pass@10.0.0.2:1080/"
"""
    submitted = f"""\
providers:
  - name: second
    proxy-url: "{REDACTION_MARK}:1»"
  - name: first
    proxy-url: "{REDACTION_MARK}:0»"
"""

    edit = prepare_config_edit(current, submitted)

    assert edit.restored.index("beta-pass") < edit.restored.index("alpha-pass")
    assert "socks5://beta:beta-pass@10.0.0.2:1080/" in edit.restored
    assert "socks5://alpha:alpha-pass@10.0.0.1:1080/" in edit.restored
    assert REDACTION_MARK not in edit.restored


def test_a_credential_url_placeholder_cannot_be_pasted_onto_a_plain_field() -> None:
    current = 'proxy-url: "socks5://alpha:alpha-pass@10.0.0.1:1080/"\n'
    submitted = f'label: "{REDACTION_MARK}:0»"\n'

    with pytest.raises(CliproxyConfigPlaceholderError, match="cannot be moved"):
        prepare_config_edit(current, submitted)


def test_a_placeholder_cannot_be_moved_onto_a_nonsecret_field() -> None:
    current = 'access:\n  api-keys:\n    - "first-key"\n'
    redacted = redact_config_yaml(current)
    submitted = redacted + f'label: "{REDACTION_MARK}:0»"\n'

    with pytest.raises(CliproxyConfigPlaceholderError, match="cannot be moved"):
        prepare_config_edit(current, submitted)


def test_restoring_a_block_scalar_placeholder_keeps_the_next_key() -> None:
    current = "token: |\n  secret-line\nnext: 1\n"
    submitted = f"token: |\n  {REDACTION_MARK}:0»\nnext: 1\n"
    edit = prepare_config_edit(current, submitted)

    assert "secret-line" in edit.restored
    assert "next: 1" in edit.restored
    assert "secret-linenext" not in edit.restored
    assert REDACTION_MARK not in edit.restored


def test_a_block_scalar_secret_keeps_the_following_key() -> None:
    current = "token: |\n  secret-line\n  second-line\nnext: 1\n"
    redacted = redact_config_yaml(current)

    assert "secret-line" not in redacted
    assert "second-line" not in redacted
    assert redacted.index(f"{REDACTION_MARK}:0»") < redacted.index("next: 1")
    edit = prepare_config_edit(current, redacted)
    assert edit.changed is False
    assert edit.restored == current


def test_leaving_every_placeholder_is_not_a_change() -> None:
    edit = prepare_config_edit(_CONFIG, redact_config_yaml(_CONFIG))

    assert edit.changed is False
    assert edit.restored == _CONFIG
    assert edit.diff == ""


def test_a_new_document_rejects_a_placeholder_with_nothing_to_keep() -> None:
    submitted = f'management:\n  secret-key: "{REDACTED_PLACEHOLDER}"\n'

    with pytest.raises(CliproxyConfigPlaceholderError):
        prepare_config_edit("", submitted)


def test_a_new_document_is_accepted_when_it_contains_real_secrets() -> None:
    submitted = 'management:\n  secret-key: "fresh-secret"\n'
    edit = prepare_config_edit(None, submitted)

    assert edit.restored == submitted
    assert "fresh-secret" in edit.restored
    assert "fresh-secret" not in edit.diff


def test_invalid_yaml_is_rejected() -> None:
    with pytest.raises(CliproxyConfigYamlError, match="Invalid YAML"):
        redact_config_yaml("routing: [\n")


def test_a_root_that_is_not_a_mapping_is_rejected() -> None:
    with pytest.raises(CliproxyConfigYamlError, match="single YAML mapping"):
        redact_config_yaml("- just-a-list\n")


def test_authorization_and_cookie_headers_are_redacted() -> None:
    current = 'headers:\n  Authorization: "Bearer sk-live"\n  Cookie: "session=abc"\n  Host: example.com\n'
    redacted = redact_config_yaml(current)

    assert "sk-live" not in redacted
    assert "session=abc" not in redacted
    assert "Host: example.com" in redacted
    edit = prepare_config_edit(current, redacted)
    assert edit.changed is False
    assert edit.restored == current


def test_boolean_like_secrets_are_redacted_and_routing_flags_stay_visible() -> None:
    current = "password: on\napi-key: true\nrouting:\n  session-affinity: true\n"
    redacted = redact_config_yaml(current)

    assert "password: on" not in redacted
    assert "api-key: true" not in redacted
    assert "session-affinity: true" in redacted
    edit = prepare_config_edit(current, redacted)
    assert edit.changed is False
    assert edit.restored == current


def test_routing_flags_read_booleans_and_default_missing_ones_to_false() -> None:
    assert routing_flags(_CONFIG) == (True, False)
    assert routing_flags("routing:\n  force-model-prefix: true\n") == (False, True)
    assert routing_flags("port: 1\n") == (False, False)
    assert routing_flags("routing: [\n") == (None, None)
