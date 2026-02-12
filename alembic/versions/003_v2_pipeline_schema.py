"""V2 pipeline schema: split reports, add user preferences

Revision ID: 003
Revises: 002
Create Date: 2026-02-12 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- 1. Add preference columns to users ---
    op.add_column('users', sa.Column('preferred_persona', sa.String(length=50), nullable=True))
    op.add_column('users', sa.Column('preferred_lang', sa.String(length=10), nullable=True))

    # --- 2. Create global_reports table ---
    op.create_table('global_reports',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('run_date', sa.Date(), nullable=False),
        sa.Column('symbol', sa.String(length=20), nullable=True),
        sa.Column('report_type', sa.String(length=50), nullable=False),
        sa.Column('content_md', sa.Text(), nullable=False),
        sa.Column('model_used', sa.String(length=100), nullable=True),
        sa.Column('persona_used', sa.String(length=50), nullable=True),
        sa.Column('input_context', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('pipeline_run_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_global_reports_run_date'), 'global_reports', ['run_date'])
    op.create_index('ix_global_report_run_date_type', 'global_reports', ['run_date', 'report_type'])
    op.create_index('ix_global_report_run_date_symbol', 'global_reports', ['run_date', 'symbol'])

    # --- 3. Create user_reports table ---
    op.create_table('user_reports',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('run_date', sa.Date(), nullable=False),
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
    op.create_index(op.f('ix_user_reports_user_id'), 'user_reports', ['user_id'])
    op.create_index(op.f('ix_user_reports_run_date'), 'user_reports', ['run_date'])
    op.create_index('ix_user_report_user_run_date', 'user_reports', ['user_id', 'run_date'])

    # --- 4. Migrate existing reports data to user_reports ---
    # Copy existing data from reports → user_reports (all existing reports are user-scoped)
    op.execute("""
        INSERT INTO user_reports (id, user_id, run_date, report_type, content_md,
                                  model_used, persona_used, input_context,
                                  pipeline_run_id, created_at)
        SELECT id, user_id, run_date, report_type, content_md,
               model_used, persona_used, input_context,
               pipeline_run_id, created_at
        FROM reports
    """)

    # --- 5. Drop old reports table ---
    op.drop_index(op.f('ix_reports_user_run_date_symbol'), table_name='reports')
    op.drop_table('reports')


def downgrade() -> None:
    # --- 1. Recreate old reports table ---
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

    # --- 2. Migrate user_reports data back to reports ---
    # Note: user_reports may not have 'symbol' column. Set symbol to 'N/A' for those.
    op.execute("""
        INSERT INTO reports (id, user_id, run_date, symbol, report_type, content_md,
                            model_used, persona_used, input_context,
                            pipeline_run_id, created_at)
        SELECT id, user_id, run_date, 'N/A', report_type, content_md,
               model_used, persona_used, input_context,
               pipeline_run_id, created_at
        FROM user_reports
    """)

    # --- 3. Drop new tables ---
    op.drop_index('ix_user_report_user_run_date', table_name='user_reports')
    op.drop_index(op.f('ix_user_reports_run_date'), table_name='user_reports')
    op.drop_index(op.f('ix_user_reports_user_id'), table_name='user_reports')
    op.drop_table('user_reports')

    op.drop_index('ix_global_report_run_date_symbol', table_name='global_reports')
    op.drop_index('ix_global_report_run_date_type', table_name='global_reports')
    op.drop_index(op.f('ix_global_reports_run_date'), table_name='global_reports')
    op.drop_table('global_reports')

    # --- 4. Remove user preference columns ---
    op.drop_column('users', 'preferred_lang')
    op.drop_column('users', 'preferred_persona')
