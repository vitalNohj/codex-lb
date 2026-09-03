from __future__ import annotations

from typing import cast as typing_cast

from app.core.usage.logs import (
    CANCELLED_STATUS,
    RequestLogLike,
    cached_input_tokens_from_log,
    cost_breakdown_from_log,
    output_tokens_from_log,
    total_tokens_from_log,
)
from app.db.models import RequestLog
from app.modules.request_logs.schemas import RequestLogCostBreakdown, RequestLogEntry

RATE_LIMIT_CODES = {"rate_limit_exceeded", "usage_limit_reached"}
QUOTA_CODES = {"insufficient_quota", "usage_not_included", "quota_exceeded"}


def normalize_log_status(status: str, error_code: str | None) -> str:
    if status == "success":
        return "ok"
    if status == CANCELLED_STATUS:
        return "cancelled"
    if error_code in RATE_LIMIT_CODES:
        return "rate_limit"
    if error_code in QUOTA_CODES:
        return "quota"
    return "error"


def log_status(log: RequestLog) -> str:
    return normalize_log_status(log.status, log.error_code)


def to_request_log_entry(
    log: RequestLog,
    *,
    api_key_name: str | None = None,
    sidecar_account_label: str | None = None,
    display_price_status: str | None = None,
    include_sensitive_metadata: bool,
) -> RequestLogEntry:
    log_like = typing_cast(RequestLogLike, log)
    cost_breakdown = cost_breakdown_from_log(log_like, precision=6)
    reference_cost_usd = round(log.reference_cost_usd, 6) if log.reference_cost_usd is not None else None
    price_status = display_price_status if display_price_status is not None else log.price_status
    savings_usd = _savings_usd(
        actual=cost_breakdown.total_usd,
        reference=reference_cost_usd,
        cost_is_unknown=cost_breakdown.total_usd is None and price_status is not None,
    )
    return RequestLogEntry(
        requested_at=log.requested_at,
        conversation_id=log.conversation_id if include_sensitive_metadata else None,
        account_id=log.account_id,
        plan_type=log.plan_type,
        api_key_id=log.api_key_id,
        api_key_name=api_key_name,
        request_id=log.request_id,
        archive_request_id=log.archive_request_id if include_sensitive_metadata else None,
        request_kind=log.request_kind,
        connection_request_kind=log.connection_request_kind,
        model=log.model,
        source=log.source,
        sidecar_account_label=sidecar_account_label,
        model_source_id=log.model_source_id,
        model_source_kind=log.model_source_kind,
        useragent=log.useragent if include_sensitive_metadata else None,
        useragent_group=log.useragent_group,
        client_ip=log.client_ip if include_sensitive_metadata else None,
        transport=log.transport,
        upstream_transport=log.upstream_transport,
        upstream_proxy_route_mode=log.upstream_proxy_route_mode,
        upstream_proxy_pool_id=log.upstream_proxy_pool_id,
        upstream_proxy_endpoint_id=log.upstream_proxy_endpoint_id,
        upstream_proxy_fallback_used=log.upstream_proxy_fallback_used,
        upstream_proxy_fail_closed_reason=log.upstream_proxy_fail_closed_reason,
        service_tier=log.service_tier,
        requested_service_tier=log.requested_service_tier,
        actual_service_tier=log.actual_service_tier,
        reasoning_effort=log.reasoning_effort,
        requested_reasoning_effort=log.requested_reasoning_effort,
        status=log_status(log),
        error_code=log.error_code,
        error_message=log.error_message,
        failure_phase=log.failure_phase,
        failure_detail=log.failure_detail,
        failure_exception_type=log.failure_exception_type,
        upstream_status_code=log.upstream_status_code,
        upstream_error_code=log.upstream_error_code,
        bridge_stage=log.bridge_stage,
        tokens=total_tokens_from_log(log_like),
        input_tokens=log.input_tokens,
        output_tokens=output_tokens_from_log(log_like),
        output_tokens_raw=log.output_tokens,
        reasoning_tokens=log.reasoning_tokens,
        cached_input_tokens=cached_input_tokens_from_log(log_like),
        cost_usd=cost_breakdown.total_usd,
        cost_source=log.cost_source,
        price_status=price_status,
        cost_breakdown=RequestLogCostBreakdown(**cost_breakdown.__dict__),
        reference_cost_usd=reference_cost_usd,
        savings_usd=savings_usd,
        latency_ms=log.latency_ms,
        latency_first_token_ms=log.latency_first_token_ms,
        latency_queue_ms=log.latency_queue_ms,
    )


def _savings_usd(*, actual: float | None, reference: float | None, cost_is_unknown: bool = False) -> float | None:
    if reference is None:
        return None
    if cost_is_unknown:
        # The row participates in external price resolution and the resolver
        # deliberately recorded no cost. Treating that unknown as $0 spent would
        # report the whole reference as money saved, which is a fabricated figure
        # rather than a missing one.
        return None
    savings = reference - (actual or 0.0)
    if savings <= 0:
        return 0.0
    return round(savings, 6)
