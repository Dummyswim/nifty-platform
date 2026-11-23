"""engine_configs, engine_runs, plot_points, events, overlay_elements

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE engine_configs (
          user_id int NOT NULL DEFAULT 1,
          config_hash text NOT NULL,
          engine_id text NOT NULL,
          engine_version text NOT NULL,
          params jsonb NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (user_id, config_hash)
        )
        """
    )
    # run_key = sha256(engine_id|engine_version|config_hash|snapshot_id|timeframe): the timeframe is
    # part of the key because config_hash does not cover it (D07 deviation, logged in STATE)
    op.execute(
        """
        CREATE TABLE engine_runs (
          run_id text PRIMARY KEY,
          run_key text NOT NULL UNIQUE,
          engine_id text NOT NULL,
          engine_version text NOT NULL,
          config_hash text NOT NULL,
          instrument_id text NOT NULL,
          timeframe text NOT NULL,
          source_id text NOT NULL,
          n_bars int NOT NULL,
          panel jsonb,
          created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE plot_points (
          run_id text NOT NULL REFERENCES engine_runs (run_id) ON DELETE CASCADE,
          bar_start_utc timestamptz NOT NULL,
          values jsonb NOT NULL,
          PRIMARY KEY (run_id, bar_start_utc)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE events (
          run_id text NOT NULL REFERENCES engine_runs (run_id) ON DELETE CASCADE,
          ord int NOT NULL,
          event_id uuid NOT NULL,
          event_type text NOT NULL,
          bar_start_utc timestamptz NOT NULL,
          available_at_utc timestamptz NOT NULL,
          confirmed_or_provisional text NOT NULL,
          envelope jsonb NOT NULL,
          PRIMARY KEY (run_id, event_id)
        )
        """
    )
    op.execute("CREATE INDEX events_avail_idx ON events (run_id, available_at_utc)")
    op.execute(
        """
        CREATE TABLE overlay_elements (
          run_id text NOT NULL REFERENCES engine_runs (run_id) ON DELETE CASCADE,
          ord int NOT NULL,
          id text NOT NULL,
          ver int NOT NULL,
          avail_at_utc timestamptz NOT NULL,
          deleted boolean NOT NULL DEFAULT false,
          element jsonb NOT NULL,
          PRIMARY KEY (run_id, id, ver)
        )
        """
    )


def downgrade() -> None:
    for t in ("overlay_elements", "events", "plot_points", "engine_runs", "engine_configs"):
        op.execute(f"DROP TABLE {t}")
