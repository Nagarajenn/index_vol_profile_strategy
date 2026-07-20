from collections.abc import AsyncIterator

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings


def _build_async_url() -> str:
    url = make_url(settings.DATABASE_URL).set(drivername="postgresql+asyncpg")
    # asyncpg doesn't understand libpq's sslmode query param -- if a future
    # deployment adds one, it must move to connect_args={"ssl": ...} instead.
    # Verified empty for the current local DATABASE_URL.
    if url.query:
        raise ValueError(
            f"DATABASE_URL has query params {dict(url.query)!r} -- asyncpg needs these "
            "passed via connect_args (e.g. ssl=...), not the URL. Update _build_async_url()."
        )
    return url.render_as_string(hide_password=False)


engine = create_async_engine(
    _build_async_url(),
    connect_args={"server_settings": {"search_path": f"{settings.DB_SCHEMA},public"}},
    pool_size=3,
    max_overflow=2,
)

async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session
