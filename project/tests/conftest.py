import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"
os.environ["SECRET_KEY"] = "test-secret-key-that-is-at-least-32-bytes-long"
os.environ["ALGORITHM"] = "HS256"
os.environ["ACCESS_TOKEN_EXPIRE_MINUTES"] = "60"

os.environ["AWS_ACCESS_KEY_ID"] = "test-access-key"
os.environ["AWS_SECRET_ACCESS_KEY"] = "test-secret-key"
os.environ["AWS_REGION"] = "us-east-1"
os.environ["AWS_S3_BUCKET"] = "test-bucket"

from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock

import pytest

from main import app
from db.db_session import get_db


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def mock_db_execute_none():
    """
    Mocked async database session.

    db.execute() returns a result where scalar_one_or_none() is None.
    This simulates the case where the username does not exist yet.
    """

    db = MagicMock()

    result = MagicMock()
    result.scalar_one_or_none.return_value = None

    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    return db


@pytest.fixture()
def client_with_mock_db_execute_none(client, mock_db_execute_none):
    """
    Overrides the real get_db dependency with the mocked database session.
    """

    async def override_get_db():
        yield mock_db_execute_none

    app.dependency_overrides[get_db] = override_get_db

    yield client

    app.dependency_overrides.clear()