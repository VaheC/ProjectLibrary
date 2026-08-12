import os

# Set test environment variables before importing the app.
os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["ALGORITHM"] = "HS256"
os.environ["ACCESS_TOKEN_EXPIRE_MINUTES"] = "60"

os.environ["AWS_ACCESS_KEY_ID"] = "test-access-key"
os.environ["AWS_SECRET_ACCESS_KEY"] = "test-secret-key"
os.environ["AWS_REGION"] = "us-east-1"
os.environ["AWS_S3_BUCKET"] = "test-bucket"

import pytest
import pytest_asyncio

from httpx import AsyncClient, ASGITransport

from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
)
from sqlalchemy.pool import StaticPool

from unittest.mock import AsyncMock

from db.db import Base
from db.db_session import get_db

from main import app


# ---------------------------------------------------------------------
# Test database setup
# ---------------------------------------------------------------------

TEST_DATABASE_URL = "sqlite+aiosqlite://"

engine_test = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingSessionLocal = async_sessionmaker(
    bind=engine_test,
    expire_on_commit=False,
)


async def override_get_db():
    """
    Overrides the real get_db dependency.

    Tests use an isolated in-memory SQLite database.
    """
    async with TestingSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


app.dependency_overrides[get_db] = override_get_db


@pytest_asyncio.fixture(autouse=True)
async def setup_database():
    """
    Creates all tables before every test and drops them after every test.
    """
    async with engine_test.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield

    async with engine_test.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    """
    Async HTTP client for calling the FastAPI app.
    """
    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as ac:
        yield ac


# ---------------------------------------------------------------------
# Fake S3
# ---------------------------------------------------------------------

class FakeS3Client:
    def __init__(self):
        self.put_object = AsyncMock()
        self.delete_object = AsyncMock()
        self.get_object = AsyncMock()

        body = AsyncMock()
        body.read = AsyncMock(return_value=b"test-file-content")

        self.get_object.return_value = {
            "Body": body,
            "ContentType": "text/plain",
        }


class FakeS3ClientContext:
    def __init__(self, client):
        self.client = client

    async def __aenter__(self):
        return self.client

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.fixture
def fake_s3(monkeypatch):
    """
    Replaces get_s3_client() in routers with a fake S3 client.
    """
    client = FakeS3Client()

    def fake_get_s3_client():
        return FakeS3ClientContext(client)

    monkeypatch.setattr(
        "routers.projects.get_s3_client",
        fake_get_s3_client,
    )

    monkeypatch.setattr(
        "routers.documents.get_s3_client",
        fake_get_s3_client,
    )

    return client


# ---------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------

@pytest.fixture
def register_user(client):
    async def _register(
        username="owner",
        password="password123",
    ):
        response = await client.post(
            "/auth",
            json={
                "login": username,
                "password": password,
                "repeat_password": password,
            },
        )

        assert response.status_code == 200
        return response.json()

    return _register


@pytest.fixture
def login_user(client):
    async def _login(
        username="owner",
        password="password123",
    ):
        response = await client.post(
            "/login",
            json={
                "login": username,
                "password": password,
            },
        )

        assert response.status_code == 200
        return response.json()["access_token"]

    return _login


@pytest.fixture
def auth_headers():
    def _headers(token):
        return {
            "Authorization": f"Bearer {token}",
        }

    return _headers


# ---------------------------------------------------------------------
# Project helpers
# ---------------------------------------------------------------------

@pytest.fixture
def create_project(client, auth_headers):
    async def _create(
        token,
        name="Test Project",
        description="This is a test project description",
    ):
        response = await client.post(
            "/project",
            json={
                "name": name,
                "description": description,
            },
            headers=auth_headers(token),
        )

        assert response.status_code == 200
        return response.json()

    return _create


@pytest.fixture
def invite_user(client, auth_headers):
    async def _invite(
        owner_token,
        project_id,
        username,
        expected_status=200,
    ):
        response = await client.post(
            f"/project/{project_id}/invite",
            params={"user": username},
            headers=auth_headers(owner_token),
        )

        if expected_status is not None:
            assert response.status_code == expected_status

        return response

    return _invite


# ---------------------------------------------------------------------
# Document helpers
# ---------------------------------------------------------------------

@pytest.fixture
def upload_documents(client, auth_headers):
    async def _upload(
        token,
        project_id,
        files=None,
    ):
        if files is None:
            files = [
                (
                    "files",
                    (
                        "test.txt",
                        b"hello world",
                        "text/plain",
                    ),
                )
            ]

        response = await client.post(
            f"/project/{project_id}/documents",
            headers=auth_headers(token),
            files=files,
        )

        assert response.status_code == 200
        return response.json()

    return _upload