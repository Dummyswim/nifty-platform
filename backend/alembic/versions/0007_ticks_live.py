"""ticks (hypertable, compressed after 7 days), collector_status

Revision ID: 0007
Revises: 0006
"""

from alembic import op

revision = "0007"
down_revision = "0006"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE ticks (
          instrument_id text NOT NULL,
          ts_exchange timestamptz NOT NULL,
          ts_received timestamptz NOT NULL,
          ltp double precision NOT NULL,
          volume_traded double precision,
          oi double precision,
          bid double precision,
          ask double precision,
          bid_qty double precision,
          ask_qty double precision
        )
        """
    )
    op.execute(
        "SELECT create_hypertable('ticks', 'ts_exchange', chunk_time_interval => INTERVAL '1 day')"
    )
    op.execute("CREATE INDEX ticks_inst_ts_idx ON ticks (instrument_id, ts_exchange DESC)")
    op.execute(
        "ALTER TABLE ticks SET (timescaledb.compress, timescaledb.compress_segmentby = 'instrument_id', "
        "timescaledb.compress_orderby = 'ts_exchange DESC')"
    )
    op.execute("SELECT add_compression_policy('ticks', INTERVAL '7 days')")
    op.execute(
        """
        CREATE TABLE collector_status (
          id int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
          data jsonb NOT NULL,
          updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE collector_status")
    op.execute("DROP TABLE ticks")
