"""timescaledb extension + prefs

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    op.execute(
        """
        CREATE TABLE prefs (
          user_id int NOT NULL DEFAULT 1,
          key text NOT NULL,
          value jsonb NOT NULL,
          updated_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (user_id, key)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE prefs")
