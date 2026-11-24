"""research_runs, research_labels

Revision ID: 0008
Revises: 0007
"""

from alembic import op

revision = "0008"
down_revision = "0007"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE research_runs (
          research_id text PRIMARY KEY,
          snapshot_id text NOT NULL,
          instrument_id text NOT NULL,
          config_hash text NOT NULL UNIQUE,
          seed int NOT NULL,
          cost_pts double precision NOT NULL,
          splits jsonb NOT NULL,
          variants jsonb NOT NULL,
          code_version text NOT NULL,
          thresholds jsonb NOT NULL,
          progress jsonb NOT NULL DEFAULT '{}'::jsonb,
          result jsonb,
          status text NOT NULL DEFAULT 'running' CHECK (status IN ('running','done','failed')),
          error text,
          created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE research_labels (
          id bigserial PRIMARY KEY,
          research_id text NOT NULL REFERENCES research_runs (research_id) ON DELETE CASCADE,
          engine_id text NOT NULL,
          config_hash text NOT NULL,
          instrument_id text NOT NULL,
          signal_bar_start timestamptz NOT NULL,
          side text NOT NULL,
          variant text NOT NULL,
          experiment text NOT NULL,
          split text NOT NULL,
          run_id text NOT NULL,
          label text NOT NULL,
          trade jsonb NOT NULL,
          UNIQUE (engine_id, config_hash, instrument_id, signal_bar_start, side)
        )
        """
    )
    op.execute("CREATE INDEX research_labels_run_idx ON research_labels (research_id, id)")


def downgrade() -> None:
    op.execute("DROP TABLE research_labels")
    op.execute("DROP TABLE research_runs")
