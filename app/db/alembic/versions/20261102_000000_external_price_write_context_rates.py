"""Persist published cache-write and long-context rates for external models.

Existing rows retain their rates and use NULL for the new optional fields;
normal catalog maintenance populates them on its next successful refresh.
Downgrade deliberately preserves these optional columns: normal operation may
have populated them, and the migration cannot prove ownership of those values.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261102_000000_external_price_write_context_rates"
down_revision = "20261029_010000_api_key_limit_reasoning_effort"
branch_labels = None
depends_on = None

_TABLE = "external_model_prices"
_COLUMNS = (
    "cache_write_input_per_1m",
    "cache_write_input_1h_per_1m",
    "long_context_threshold_tokens",
    "long_context_input_per_1m",
    "long_context_output_per_1m",
    "long_context_cached_input_per_1m",
    "long_context_cache_write_input_per_1m",
    "long_context_cache_write_input_1h_per_1m",
)


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns(_TABLE)}
    for name in _COLUMNS:
        if name not in columns:
            op.add_column(_TABLE, sa.Column(name, sa.Float(), nullable=True))


def downgrade() -> None:
    # Older application versions ignore these nullable columns. Keep prices
    # populated by normal catalog refreshes rather than destructively deleting
    # writes whose ownership this migration cannot establish.
    pass
