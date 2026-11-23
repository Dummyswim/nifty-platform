"""drawings

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE drawings (
          id text PRIMARY KEY,
          user_id int NOT NULL DEFAULT 1,
          instrument_id text NOT NULL REFERENCES instruments (instrument_id) ON DELETE CASCADE,
          kind text NOT NULL CHECK (kind IN ('trendline','hline','rect','text')),
          data jsonb NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX drawings_inst_idx ON drawings (user_id, instrument_id)")


def downgrade() -> None:
    op.execute("DROP TABLE drawings")
