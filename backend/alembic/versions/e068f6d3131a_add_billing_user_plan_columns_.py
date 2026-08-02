"""add billing: user plan columns, subscriptions, usage_events

Revision ID: e068f6d3131a
Revises: 453348d81a12
Create Date: 2026-08-02 04:58:15.493106

Adds the Stripe paywall schema:

- users: plan ('free' | 'pro', default 'free'), plan_grandfathered (bool,
  default False), stripe_customer_id (nullable, indexed)
- subscriptions: one row per user; carries Stripe subscription state
- usage_events: one row per successful generation; counted monthly for cap

Grandfather backfill: every existing user at upgrade time is set to
plan='pro', plan_grandfathered=TRUE, gated by a schema_migrations row so
re-running the migration is a no-op.

This replaces the hand-rolled ALTER TABLE block that previously lived in
models._run_alembic_upgrade (removed in the same commit). See
AGENTS.md "Never hand-write ALTER TABLE" rule.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e068f6d3131a'
down_revision: Union[str, None] = '453348d81a12'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # New tables
    op.create_table(
        'subscriptions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('stripe_customer_id', sa.String(length=128), nullable=True),
        sa.Column('stripe_subscription_id', sa.String(length=128), nullable=True),
        sa.Column('stripe_price_id', sa.String(length=128), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='incomplete'),
        sa.Column('current_period_start', sa.DateTime(), nullable=True),
        sa.Column('current_period_end', sa.DateTime(), nullable=True),
        sa.Column('cancel_at_period_end', sa.Boolean(), nullable=False, server_default=sa.text('FALSE')),
        sa.Column('canceled_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('stripe_subscription_id', name='uq_subscriptions_stripe_subscription_id'),
    )
    op.create_index(op.f('ix_subscriptions_id'), 'subscriptions', ['id'], unique=False)
    op.create_index(op.f('ix_subscriptions_user_id'), 'subscriptions', ['user_id'], unique=True)
    op.create_index(op.f('ix_subscriptions_stripe_customer_id'), 'subscriptions', ['stripe_customer_id'], unique=False)

    op.create_table(
        'usage_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('event_type', sa.String(length=64), nullable=False, server_default='resume_generation'),
        sa.Column('job_id', sa.Integer(), nullable=True),
        sa.Column('plan_at_event', sa.String(length=32), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_usage_events_id'), 'usage_events', ['id'], unique=False)
    op.create_index(op.f('ix_usage_events_user_id'), 'usage_events', ['user_id'], unique=False)
    op.create_index(op.f('ix_usage_events_created_at'), 'usage_events', ['created_at'], unique=False)

    # New users columns. plan and plan_grandfathered are NOT NULL with
    # server defaults so existing rows backfill automatically. New users
    # created at the application layer also pick up these defaults via the
    # SQLAlchemy model declarations.
    op.add_column('users', sa.Column('plan', sa.String(length=32), nullable=False, server_default='free'))
    op.add_column('users', sa.Column('plan_grandfathered', sa.Boolean(), nullable=False, server_default=sa.text('FALSE')))
    op.add_column('users', sa.Column('stripe_customer_id', sa.String(length=128), nullable=True))
    op.create_index(op.f('ix_users_plan'), 'users', ['plan'], unique=False)
    op.create_index(op.f('ix_users_stripe_customer_id'), 'users', ['stripe_customer_id'], unique=False)

    # Grandfather backfill: every existing user at upgrade time is set to
    # plan='pro', plan_grandfathered=TRUE. Gated by a schema_migrations
    # row so re-running the upgrade is a no-op. Webhook handlers MUST
    # never override plan_grandfathered users (see backend/billing.py
    # _apply_subscription_state).
    bind = op.get_bind()
    if bind.dialect.name != 'sqlite':
        # Postgres / Cloud SQL: schema_migrations is real
        bind.execute(sa.text(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "  name VARCHAR(128) PRIMARY KEY,"
            "  applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
            ")"
        ))
        already = bind.execute(sa.text(
            "SELECT 1 FROM schema_migrations WHERE name = 'grandfather_users_to_pro'"
        )).first()
    else:
        # SQLite (local dev): no equivalent; use a pragma flag table to
        # keep the gate portable.
        bind.execute(sa.text(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "  name VARCHAR(128) PRIMARY KEY,"
            "  applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
            ")"
        ))
        already = bind.execute(sa.text(
            "SELECT 1 FROM schema_migrations WHERE name = 'grandfather_users_to_pro'"
        )).first()

    if not already:
        result = bind.execute(sa.text(
            "UPDATE users SET plan = 'pro', plan_grandfathered = TRUE "
            "WHERE plan_grandfathered = FALSE AND created_at IS NOT NULL"
        ))
        if result.rowcount:
            print(f"[billing-migration] grandfathered {result.rowcount} user(s) to pro plan")
        bind.execute(sa.text(
            "INSERT INTO schema_migrations (name) VALUES ('grandfather_users_to_pro')"
        ))


def downgrade() -> None:
    op.drop_index(op.f('ix_users_stripe_customer_id'), table_name='users')
    op.drop_index(op.f('ix_users_plan'), table_name='users')
    op.drop_column('users', 'stripe_customer_id')
    op.drop_column('users', 'plan_grandfathered')
    op.drop_column('users', 'plan')

    op.drop_index(op.f('ix_usage_events_created_at'), table_name='usage_events')
    op.drop_index(op.f('ix_usage_events_user_id'), table_name='usage_events')
    op.drop_index(op.f('ix_usage_events_id'), table_name='usage_events')
    op.drop_table('usage_events')

    op.drop_index(op.f('ix_subscriptions_stripe_customer_id'), table_name='subscriptions')
    op.drop_index(op.f('ix_subscriptions_user_id'), table_name='subscriptions')
    op.drop_index(op.f('ix_subscriptions_id'), table_name='subscriptions')
    op.drop_table('subscriptions')
