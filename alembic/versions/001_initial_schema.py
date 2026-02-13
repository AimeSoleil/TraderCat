"""Initial database schema

Revision ID: 001
Revises: 
Create Date: 2026-02-11 09:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create users table
    op.create_table('users',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('username', sa.String(length=100), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('role', sa.String(length=20), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('max_symbols', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=True)
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)

    # Create api_keys table
    op.create_table('api_keys',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('key_hash', sa.String(length=128), nullable=False),
        sa.Column('key_prefix', sa.String(length=12), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_api_keys_key_hash'), 'api_keys', ['key_hash'], unique=True)

    # Create watchlist_items table
    op.create_table('watchlist_items',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('symbol', sa.String(length=20), nullable=False),
        sa.Column('company_name', sa.String(length=255), nullable=True),
        sa.Column('added_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'symbol', name='uq_user_symbol')
    )
    op.create_index(op.f('ix_watchlist_items_symbol'), 'watchlist_items', ['symbol'])
    op.create_index(op.f('ix_watchlist_items_user_id'), 'watchlist_items', ['user_id'])

    # Create strategy_configs table
    op.create_table('strategy_configs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('strategy_name', sa.String(length=100), nullable=False),
        sa.Column('preset_name', sa.String(length=100), nullable=True),
        sa.Column('parameters', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'strategy_name', name='uq_user_strategy')
    )

    # Create signal_records table
    op.create_table('signal_records',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('run_date', sa.Date(), nullable=False),
        sa.Column('symbol', sa.String(length=20), nullable=False),
        sa.Column('strategy', sa.String(length=100), nullable=False),
        sa.Column('signal', sa.String(length=20), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('reason', sa.String(length=1000), nullable=True),
        sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('scope', sa.String(length=20), nullable=False),
        sa.Column('pipeline_run_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_signal_records_run_date'), 'signal_records', ['run_date'])
    op.create_index(op.f('ix_signal_records_symbol'), 'signal_records', ['symbol'])
    op.create_index(op.f('ix_signal_records_scope_run_date'), 'signal_records', ['scope', 'run_date'])

    # Create reports table
    op.create_table('reports',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('run_date', sa.Date(), nullable=False),
        sa.Column('symbol', sa.String(length=20), nullable=False),
        sa.Column('report_type', sa.String(length=50), nullable=False),
        sa.Column('content_md', sa.Text(), nullable=False),
        sa.Column('model_used', sa.String(length=100), nullable=True),
        sa.Column('persona_used', sa.String(length=50), nullable=True),
        sa.Column('input_context', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('pipeline_run_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_reports_user_run_date_symbol'), 'reports', ['user_id', 'run_date', 'symbol'])

    # Create pipeline_runs table
    op.create_table('pipeline_runs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('run_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('step', sa.String(length=50), nullable=True),
        sa.Column('total_symbols', sa.Integer(), nullable=True),
        sa.Column('processed_symbols', sa.Integer(), nullable=True),
        sa.Column('total_reports', sa.Integer(), nullable=True),
        sa.Column('processed_reports', sa.Integer(), nullable=True),
        sa.Column('error_log', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_pipeline_runs_run_date'), 'pipeline_runs', ['run_date'], unique=True)


def downgrade() -> None:
    # Drop all tables in reverse order of foreign key dependencies
    # First drop tables that reference others, then drop the referenced tables
    
    op.drop_index(op.f('ix_pipeline_runs_run_date'), table_name='pipeline_runs')
    op.drop_table('pipeline_runs')
    
    op.drop_index(op.f('ix_reports_user_run_date_symbol'), table_name='reports')
    op.drop_table('reports')
    
    op.drop_index(op.f('ix_signal_records_scope_run_date'), table_name='signal_records')
    op.drop_index(op.f('ix_signal_records_symbol'), table_name='signal_records')
    op.drop_index(op.f('ix_signal_records_run_date'), table_name='signal_records')
    op.drop_table('signal_records')
    
    op.drop_table('strategy_configs')
    
    op.drop_index(op.f('ix_watchlist_items_user_id'), table_name='watchlist_items')
    op.drop_index(op.f('ix_watchlist_items_symbol'), table_name='watchlist_items')
    op.drop_table('watchlist_items')
    
    op.drop_index(op.f('ix_api_keys_key_hash'), table_name='api_keys')
    op.drop_table('api_keys')
    
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_index(op.f('ix_users_username'), table_name='users')
    op.drop_table('users')
