"""instruments, bars (hypertable), datasets, calendar_days

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE instruments (
          instrument_id text PRIMARY KEY,
          provider text NOT NULL,
          provider_token bigint,
          exchange text,
          segment text,
          instrument_type text NOT NULL,
          tradingsymbol text NOT NULL,
          underlying text,
          expiry date,
          strike double precision,
          option_type text,
          tick_size double precision,
          lot_size int,
          currency text NOT NULL DEFAULT 'INR',
          metadata_version text,
          provider_meta jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX instruments_symbol_idx ON instruments (tradingsymbol)")
    # prices are double precision on purpose: source data carries float32 artefacts and is never rounded
    op.execute(
        """
        CREATE TABLE bars (
          instrument_id text NOT NULL REFERENCES instruments (instrument_id),
          timeframe text NOT NULL,
          bar_start_utc timestamptz NOT NULL,
          bar_end_utc timestamptz NOT NULL,
          revision int NOT NULL DEFAULT 0,
          provider text NOT NULL,
          open double precision NOT NULL,
          high double precision NOT NULL,
          low double precision NOT NULL,
          close double precision NOT NULL,
          volume double precision NOT NULL,
          volume_kind text NOT NULL,
          finalized boolean NOT NULL DEFAULT true,
          received_at_utc timestamptz NOT NULL,
          quality_flags text[] NOT NULL DEFAULT '{}',
          PRIMARY KEY (instrument_id, timeframe, bar_start_utc, revision)
        )
        """
    )
    op.execute(
        "SELECT create_hypertable('bars', 'bar_start_utc', chunk_time_interval => INTERVAL '30 days')"
    )
    op.execute(
        """
        CREATE TABLE datasets (
          snapshot_id text PRIMARY KEY,
          instrument_id text NOT NULL REFERENCES instruments (instrument_id),
          timeframe text NOT NULL,
          from_utc timestamptz NOT NULL,
          to_utc timestamptz NOT NULL,
          sha256 text NOT NULL,
          n_rows int NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE calendar_days (
          day date NOT NULL,
          version text NOT NULL,
          status text NOT NULL,
          open_ist time,
          close_ist time,
          verified boolean NOT NULL DEFAULT false,
          PRIMARY KEY (day, version)
        )
        """
    )


def downgrade() -> None:
    for t in ("calendar_days", "datasets", "bars", "instruments"):
        op.execute(f"DROP TABLE {t}")
