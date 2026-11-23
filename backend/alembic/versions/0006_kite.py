"""instrument_masters, kite_tokens

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE instrument_masters (
          version text PRIMARY KEY,
          fetched_at timestamptz NOT NULL DEFAULT now(),
          sha256 text NOT NULL,
          n_rows int NOT NULL,
          n_used int NOT NULL,
          content bytea NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE kite_tokens (
          user_id int PRIMARY KEY DEFAULT 1,
          ciphertext bytea NOT NULL,
          kite_user_id text,
          created_at timestamptz NOT NULL DEFAULT now(),
          expires_at timestamptz NOT NULL,
          validated_at timestamptz,
          last_error text
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE kite_tokens")
    op.execute("DROP TABLE instrument_masters")
