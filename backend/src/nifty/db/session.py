from functools import lru_cache

from sqlalchemy import Engine, create_engine

from nifty.config import get_settings


@lru_cache
def get_engine() -> Engine:
    """Lazy: no connection is made until first use."""
    return create_engine(get_settings().database_url, pool_pre_ping=True)
