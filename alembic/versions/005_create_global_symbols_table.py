"""Create global_symbols table and seed from config

Revision ID: 006
Revises: 005
Create Date: 2026-02-13 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from datetime import datetime
from uuid import uuid4

# revision identifiers, used by Alembic.
revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None

# Seed data — matches the original config.global_symbols list, classified by type
SEED_SYMBOLS = [
    # Macro benchmarks
    ("SPY", "macro", "S&P 500 ETF"),
    ("QQQ", "macro", "Nasdaq 100 ETF"),
    ("DIA", "macro", "Dow Jones ETF"),
    ("IWM", "macro", "Russell 2000 ETF"),
    ("TLT", "macro", "20+ Year Treasury"),
    ("VIX", "macro", "CBOE Volatility Index"),
    # Sector ETFs
    ("XLK", "sector", "Technology Select Sector"),
    ("XLF", "sector", "Financial Select Sector"),
    ("XLY", "sector", "Consumer Discretionary"),
    ("XLV", "sector", "Health Care Select Sector"),
    ("XLE", "sector", "Energy Select Sector"),
    ("XLI", "sector", "Industrial Select Sector"),
    ("XLP", "sector", "Consumer Staples"),
]


def upgrade() -> None:
    # Create table
    op.create_table(
        'global_symbols',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('symbol', sa.String(length=20), nullable=False),
        sa.Column('symbol_type', sa.String(length=20), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('added_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('symbol', name='uq_global_symbol'),
    )
    op.create_index('ix_global_symbols_symbol', 'global_symbols', ['symbol'])
    op.create_index('ix_global_symbols_symbol_type', 'global_symbols', ['symbol_type'])

    # Seed data
    connection = op.get_bind()
    now = datetime.utcnow()
    for sym, sym_type, desc in SEED_SYMBOLS:
        connection.execute(
            sa.text("""
                INSERT INTO global_symbols (id, symbol, symbol_type, description, added_at)
                VALUES (:id, :symbol, :symbol_type, :description, :added_at)
                ON CONFLICT (symbol) DO NOTHING
            """),
            {
                "id": uuid4(),
                "symbol": sym,
                "symbol_type": sym_type,
                "description": desc,
                "added_at": now,
            },
        )
    print(f"✅  Seeded {len(SEED_SYMBOLS)} global symbols (macro + sector)")


def downgrade() -> None:
    op.drop_index('ix_global_symbols_symbol_type', 'global_symbols')
    op.drop_index('ix_global_symbols_symbol', 'global_symbols')
    op.drop_table('global_symbols')
