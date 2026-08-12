from fastapi import FastAPI
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from db.db import Base
from routers import auth, projects, documents, other
from config.config import settings
from db.db_session import engine, AsyncSessionLocal

# # Create async engine
# engine = create_async_engine(settings.DATABASE_URL)

# # Create async session factory
# AsyncSessionLocal = async_sessionmaker(bind=engine)

# Create database tables during application startup
async def create_db_and_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# FastAPI lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_db_and_tables()
    yield

app = FastAPI(lifespan=lifespan)

# Include routers
app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(documents.router)
app.include_router(other.router)

@app.get("/")
async def root():
    return {"message": "API is running"}