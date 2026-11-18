"""Shared catalog value types. Rates are USD per million tokens."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPrice:
    input_per_1m: float
    output_per_1m: float
    cached_input_per_1m: float | None = None
    priority_multiplier: float | None = None
    priority_input_per_1m: float | None = None
    priority_output_per_1m: float | None = None
    priority_cached_input_per_1m: float | None = None
    flex_input_per_1m: float | None = None
    flex_output_per_1m: float | None = None
    flex_cached_input_per_1m: float | None = None
    long_context_threshold_tokens: float | None = None
    long_context_input_per_1m: float | None = None
    long_context_output_per_1m: float | None = None
    long_context_cached_input_per_1m: float | None = None
    priority_long_context_input_per_1m: float | None = None
    priority_long_context_output_per_1m: float | None = None
    priority_long_context_cached_input_per_1m: float | None = None
    flex_long_context_input_per_1m: float | None = None
    flex_long_context_output_per_1m: float | None = None
    flex_long_context_cached_input_per_1m: float | None = None
    cache_write_input_per_1m: float | None = None
    cache_write_input_1h_per_1m: float | None = None
    long_context_cache_write_input_per_1m: float | None = None
    long_context_cache_write_input_1h_per_1m: float | None = None
    priority_cache_write_input_per_1m: float | None = None
    priority_long_context_cache_write_input_per_1m: float | None = None
    flex_cache_write_input_per_1m: float | None = None
    flex_long_context_cache_write_input_per_1m: float | None = None
    batch_input_per_1m: float | None = None
    batch_output_per_1m: float | None = None
    batch_cached_input_per_1m: float | None = None
    batch_cache_write_input_per_1m: float | None = None
    batch_long_context_input_per_1m: float | None = None
    batch_long_context_output_per_1m: float | None = None
    batch_long_context_cached_input_per_1m: float | None = None
    batch_long_context_cache_write_input_per_1m: float | None = None
    cache_write_input_12h_per_1m: float | None = None
    long_context_cache_write_input_12h_per_1m: float | None = None
    priority_cache_write_input_12h_per_1m: float | None = None
    priority_long_context_cache_write_input_12h_per_1m: float | None = None
    flex_cache_write_input_12h_per_1m: float | None = None
    flex_long_context_cache_write_input_12h_per_1m: float | None = None
    batch_cache_write_input_12h_per_1m: float | None = None
    batch_long_context_cache_write_input_12h_per_1m: float | None = None
