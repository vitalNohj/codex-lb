"""make unpriced external price records due for one more lookup

Revision ID: 20261104_000000_retry_unpriced_external_prices
Revises: 20261102_000000_external_price_write_context_rates
Create Date: 2026-11-04 00:00:00.000000

OrcaRouter's catalog parser dropped the published input-size tier. Its
``grok/grok-4.7`` entry therefore differed from OpenRouter's ``x-ai/grok-4.7``,
and every Grok 4.7 id (including ``cc/grok-4.7-build-fast`` and the
``lb<hex>/`` account-alias forms) was recorded as ambiguous between the two.
Each failed lookup lengthened the row's backoff, up to a day, and the model
list only re-looks-up a row once its deadline passes. A deploy that fixes the
parser would then wait up to a day before the list showed a price.

This clears that backoff for rows that hold no rate, so the first model list or
request after the deploy looks them up again under the fixed parser. A row
that still cannot be priced records a fresh backoff from its first attempt, so
the extra work is one lookup per row, bounded by the lookup coordinator.
Priced rows are not touched. Downgrade is a no-op: the cleared deadlines were
retry timing, not data.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261104_000000_retry_unpriced_external_prices"
down_revision = "20261102_000000_external_price_write_context_rates"
branch_labels = None
depends_on = None

_TABLE = "external_model_prices"


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TABLE):
        return
    # A live lease (``lookup_token`` set) belongs to a worker that will write
    # its own outcome; clearing its deadline would let a second worker claim it.
    bind.execute(
        sa.text(
            f"UPDATE {_TABLE} SET attempt_count = 0, next_retry_at = NULL "
            "WHERE lookup_token IS NULL AND ("
            "status IN ('unresolved', 'ambiguous') "
            "OR (status = 'not_token_priced' AND input_per_1m IS NULL AND output_per_1m IS NULL)"
            ")"
        )
    )


def downgrade() -> None:
    pass
