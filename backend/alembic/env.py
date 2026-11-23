from alembic import context

from nifty.db.base import Base
from nifty.db.session import get_engine

target_metadata = Base.metadata

with get_engine().connect() as connection:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()
