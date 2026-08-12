from fastapi import FastAPI
from contextlib import asynccontextmanager

from db.db import Base
from db.db_session import engine

from routers import auth, projects, documents


async def create_db_and_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_db_and_tables()
    yield


app = FastAPI(
    lifespan=lifespan
)

app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(documents.router)