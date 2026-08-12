from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession
)
# from db import Base
from config.config import settings

# Create async engine
engine = create_async_engine(settings.DATABASE_URL)

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    # class_=AsyncSession,
    # expire_on_commit=False
)