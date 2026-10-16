"""Dashboard payloads for the CLIProxyAPI config editor.

The YAML field on a view is always the redacted document. A replace body may
still contain placeholders; the service splices the live secrets back in and
never returns that restored document.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.modules.shared.schemas import DashboardModel

CliproxyConfigStatus = Literal["healthy", "disabled", "not_configured", "unreachable", "unauthorized", "error"]
_SHA256 = r"^[0-9a-f]{64}$"


class CliproxyConfigView(DashboardModel):
    status: CliproxyConfigStatus
    message: str | None = None
    yaml: str | None = None
    content_sha256: str | None = None
    session_affinity: bool | None = None
    force_model_prefix: bool | None = None
    rollback_available: bool = False


class CliproxyConfigPreview(DashboardModel):
    status: CliproxyConfigStatus
    message: str | None = None
    diff: str = ""
    changed: bool = False
    content_sha256: str | None = None


class CliproxyConfigDocumentRequest(DashboardModel):
    yaml: str = Field(max_length=1_000_000)
    content_sha256: str = Field(pattern=_SHA256)


class CliproxyConfigReplaceRequest(CliproxyConfigDocumentRequest):
    confirm: Literal[True]


class CliproxyConfigRollbackRequest(DashboardModel):
    confirm: Literal[True]


class CliproxyConfigRoutingFlagUpdate(DashboardModel):
    enabled: bool
    content_sha256: str = Field(pattern=_SHA256)
