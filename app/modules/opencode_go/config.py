"""Resolve the OpenCode Go usage config from the dashboard settings row.

This is the *only* place the quota module touches settings, and it is a read.
Column ownership, migrations and credential storage belong to the OpenCode Go
backend integration (task codexlb-opencode-go-integration); duplicating a
migration or a secret store here would create a second source of truth for the
same subscription key.

Until the backend columns land, ``opencode_go_config_from_settings`` returns
``None``, which the service reports as ``not_configured`` and which issues no
upstream request at all. The removal condition for this shim is exactly "the
backend columns exist"; the decrypt path below is already the real one.
"""

from __future__ import annotations

import logging

from app.core.clients.opencode_go import DEFAULT_OPENCODE_GO_BASE_URL, OpenCodeGoConfig
from app.core.crypto import TokenEncryptor
from app.db.models import DashboardSettings

logger = logging.getLogger(__name__)

# Backend-owned settings columns this module reads. Named once so a rename by the
# backend owner is a single-line change here.
ENABLED_FIELD = "opencode_go_enabled"
API_KEY_FIELD = "opencode_go_api_key_encrypted"
BASE_URL_FIELD = "opencode_go_base_url"


def opencode_go_settings_available(settings: DashboardSettings) -> bool:
    """Has the backend owner's schema landed yet?

    ``hasattr`` is the honest test for "a sibling task has not shipped its
    columns", not a speculative fallback: there is exactly one canonical column
    name per value and no alternative is consulted.
    """
    return hasattr(settings, ENABLED_FIELD) and hasattr(settings, API_KEY_FIELD)


def opencode_go_config_from_settings(
    settings: DashboardSettings,
    *,
    encryptor: TokenEncryptor | None = None,
) -> OpenCodeGoConfig | None:
    """Build the usage config, or ``None`` when there is nothing to read.

    ``None`` means "do not contact upstream" and covers three cases the service
    maps to distinct statuses: schema not present, integration disabled, and no
    stored key. A decrypt failure also yields ``None`` - a key we cannot read is
    not a key we should send.
    """
    if not opencode_go_settings_available(settings):
        return None

    enabled = bool(getattr(settings, ENABLED_FIELD))
    encrypted_key = getattr(settings, API_KEY_FIELD, None)
    base_url = getattr(settings, BASE_URL_FIELD, None) or DEFAULT_OPENCODE_GO_BASE_URL

    if not enabled:
        # Returned rather than None so the service can report ``disabled``
        # distinctly from ``not_configured``. The service never fetches with a
        # disabled config, so no upstream request results.
        return OpenCodeGoConfig(enabled=False, base_url=base_url, api_key=None)
    if not encrypted_key:
        return OpenCodeGoConfig(enabled=True, base_url=base_url, api_key=None)

    try:
        api_key = (encryptor or TokenEncryptor()).decrypt(encrypted_key)
    except Exception:
        # Never log the ciphertext or the exception payload: a decrypt error can
        # carry key material in its repr.
        logger.warning("failed to decrypt the stored OpenCode Go API key")
        return OpenCodeGoConfig(enabled=True, base_url=base_url, api_key=None)

    return OpenCodeGoConfig(enabled=True, base_url=base_url, api_key=api_key.strip() or None)
