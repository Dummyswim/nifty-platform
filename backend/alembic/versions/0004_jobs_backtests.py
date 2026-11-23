"""jobs, backtests, trades

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE jobs (
          id bigserial PRIMARY KEY,
          kind text NOT NULL,
          key text NOT NULL UNIQUE,
          payload jsonb NOT NULL,
          status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','done','failed')),
          attempts int NOT NULL DEFAULT 0,
          error text,
          result_ref text,
          created_at timestamptz NOT NULL DEFAULT now(),
          started_at timestamptz,
          finished_at timestamptz,
          heartbeat_at timestamptz
        )
        """
    )
    op.execute("CREATE INDEX jobs_queue_idx ON jobs (status, id)")
    op.execute(
        """
        CREATE TABLE backtests (
          backtest_id text PRIMARY KEY,
          user_id int NOT NULL DEFAULT 1,
          run_id text NOT NULL REFERENCES engine_runs (run_id),
          engine_id text NOT NULL,
          instrument_id text NOT NULL,
          snapshot_id text NOT NULL,
          timeframe text NOT NULL,
          mode text NOT NULL CHECK (mode IN ('tv','conservative')),
          qty double precision NOT NULL,
          cost_pts double precision NOT NULL,
          params jsonb NOT NULL,
          summary jsonb NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX backtests_user_idx ON backtests (user_id, created_at DESC)")
    op.execute(
        """
        CREATE TABLE trades (
          backtest_id text NOT NULL REFERENCES backtests (backtest_id) ON DELETE CASCADE,
          ord int NOT NULL,
          trade_id text NOT NULL,
          side text NOT NULL,
          signal_bar_start timestamptz,
          entry_time timestamptz NOT NULL,
          exit_time timestamptz NOT NULL,
          entry_px double precision NOT NULL,
          exit_px double precision NOT NULL,
          exit_reason text NOT NULL,
          net_pts double precision NOT NULL,
          trade jsonb NOT NULL,
          PRIMARY KEY (backtest_id, ord),
          UNIQUE (backtest_id, trade_id)
        )
        """
    )


def downgrade() -> None:
    for t in ("trades", "backtests", "jobs"):
        op.execute(f"DROP TABLE {t}")
