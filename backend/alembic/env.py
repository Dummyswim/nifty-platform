from alembic import context

from nifty.db.base import Base
from nifty.db.session import get_engine

target_metadata = Base.metadata

# Tests pass their own connection (config.attributes["connection"]) so they never touch the dev DB.
connection = context.config.attributes.get("connection")
if connection is not None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()
else:
    with get_engine().connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        connection.commit()
