"""What an API key holder may see beyond its own usage.

Every API-key-authenticated endpoint that reveals pool, account or upstream
data decides through :func:`api_key_visibility`, so the rules live in one
place:

- ``upstream_limits`` shows pool-wide upstream quota: aggregate Codex credit
  windows and CLIProxyAPI credential quota.
- ``account_pool_usage`` shows the key's Codex account pool: the account list
  and pooled remaining capacity.
- Per-account Codex usage windows and account identity (email, display name)
  need both sections, because they are the pool's upstream quota broken down
  by account.
- ``reset_credits`` lets the key list and redeem ChatGPT reset credits of its
  account pool. It is off unless an admin enables it for the key.

The global ``hide_upstream_quota_from_api_keys`` setting hides everything the
first three rules grant, whatever the key's sections say. It does not change
``reset_credits``, which an admin grants explicitly per key.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.core.config.settings_cache import get_settings_cache

if TYPE_CHECKING:
    from app.modules.api_keys.service import ApiKeyData

USAGE_SECTION_UPSTREAM_LIMITS = "upstream_limits"
USAGE_SECTION_ACCOUNT_POOL_USAGE = "account_pool_usage"
USAGE_SECTION_RESET_CREDITS = "reset_credits"
VALID_USAGE_SECTIONS = frozenset(
    {
        USAGE_SECTION_UPSTREAM_LIMITS,
        USAGE_SECTION_ACCOUNT_POOL_USAGE,
        USAGE_SECTION_RESET_CREDITS,
    }
)
# New keys get pool visibility but not reset credits.
DEFAULT_USAGE_SECTIONS = f"{USAGE_SECTION_UPSTREAM_LIMITS},{USAGE_SECTION_ACCOUNT_POOL_USAGE}"


def parse_usage_sections(raw: str | None) -> frozenset[str]:
    if raw is None or not raw.strip():
        return frozenset()
    return frozenset(section.strip() for section in raw.split(",") if section.strip())


@dataclass(frozen=True, slots=True)
class ApiKeyVisibility:
    upstream_limits: bool
    account_pool: bool
    account_usage: bool
    reset_credits: bool


def api_key_can_use_reset_credits(api_key: ApiKeyData) -> bool:
    return USAGE_SECTION_RESET_CREDITS in parse_usage_sections(api_key.usage_sections)


async def upstream_quota_hidden_from_api_keys() -> bool:
    settings = await get_settings_cache().get()
    return bool(getattr(settings, "hide_upstream_quota_from_api_keys", False))


async def api_key_visibility(api_key: ApiKeyData) -> ApiKeyVisibility:
    sections = parse_usage_sections(api_key.usage_sections)
    hidden = await upstream_quota_hidden_from_api_keys()
    upstream_limits = not hidden and USAGE_SECTION_UPSTREAM_LIMITS in sections
    account_pool = not hidden and USAGE_SECTION_ACCOUNT_POOL_USAGE in sections
    return ApiKeyVisibility(
        upstream_limits=upstream_limits,
        account_pool=account_pool,
        account_usage=upstream_limits and account_pool,
        reset_credits=api_key_can_use_reset_credits(api_key),
    )
