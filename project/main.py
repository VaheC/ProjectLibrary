from fastapi import FastAPI
from contextlib import asynccontextmanager
from fastapi.openapi.utils import get_openapi

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


app = FastAPI(lifespan=lifespan)

app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(documents.router)


def _fix_binary_file_schemas(node):
    """
    Swagger UI works better with OpenAPI 3.0-style file schemas.

    FastAPI/OpenAPI 3.1 may generate:

        {
            "type": "string",
            "contentMediaType": "application/octet-stream"
        }

    This function converts that into:

        {
            "type": "string",
            "format": "binary"
        }
    """
    if isinstance(node, dict):
        if (
            node.get("type") == "string"
            and node.get("contentMediaType") == "application/octet-stream"
        ):
            node.pop("contentMediaType", None)
            node["format"] = "binary"

        for value in list(node.values()):
            _fix_binary_file_schemas(value)

    elif isinstance(node, list):
        for item in node:
            _fix_binary_file_schemas(item)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        routes=app.routes,
        openapi_version="3.0.3",
    )

    _fix_binary_file_schemas(openapi_schema)

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi