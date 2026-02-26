"""Split signal_records.details into ohlcv + indicators

Revision ID: 010
Revises: 009
Create Date: 2026-02-26 00:00:00.000000

"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

# revision identifiers, used by Alembic.
revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add new columns
    op.add_column(
        "signal_records",
        sa.Column("ohlcv", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "signal_records",
        sa.Column("indicators", postgresql.JSONB(), nullable=True),
    )

    # 2. Migrate existing data — split details into ohlcv and indicators.
    #    OHLCV keys: open, high, low, close, volume, plus any key starting with
    #    avg_volume_, rel_volume_, vol_zscore_, or bar_change_pct.
    #    Everything else goes to indicators.
    conn = op.get_bind()
    conn.execute(sa.text("""
        UPDATE signal_records
        SET
            ohlcv = (
                SELECT jsonb_object_agg(key, value)
                FROM jsonb_each(details)
                WHERE key IN ('open', 'high', 'low', 'close', 'volume', 'bar_change_pct')
                   OR key LIKE 'avg_volume_%'
                   OR key LIKE 'rel_volume_%'
                   OR key LIKE 'vol_zscore_%'
            ),
            indicators = (
                SELECT jsonb_object_agg(key, value)
                FROM jsonb_each(details)
                WHERE key NOT IN ('open', 'high', 'low', 'close', 'volume', 'bar_change_pct')
                  AND key NOT LIKE 'avg_volume_%'
                  AND key NOT LIKE 'rel_volume_%'
                  AND key NOT LIKE 'vol_zscore_%'
            )
        WHERE details IS NOT NULL
    """))

    # 3. Drop old column
    op.drop_column("signal_records", "details")


def downgrade() -> None:
    # 1. Re-create details column
    op.add_column(
        "signal_records",
        sa.Column("details", postgresql.JSONB(), nullable=True),
    )

    # 2. Merge ohlcv + indicators back into details
    conn = op.get_bind()
    conn.execute(sa.text("""
        UPDATE signal_records
        SET details = COALESCE(ohlcv, '{}'::jsonb) || COALESCE(indicators, '{}'::jsonb)
        WHERE ohlcv IS NOT NULL OR indicators IS NOT NULL
    """))

    # 3. Drop new columns
    op.drop_column("signal_records", "indicators")
    op.drop_column("signal_records", "ohlcv")
