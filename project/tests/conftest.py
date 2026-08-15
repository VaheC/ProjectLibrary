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

import pytest
from unittest.mock import AsyncMock, MagicMock

from main import app
from db.db_session import get_db
from dependencies.auth import get_current_user
from models.auth import TokenData

import bcrypt

from datetime import datetime, timezone


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

@pytest.fixture()
def mock_db_execute_present():
    """
    Mocked async database session.
    Simulates the case where the username ALREADY EXISTS in the database.
    """
    db = MagicMock()

    real_password = "testpassword1"
    real_hash = bcrypt.hashpw(
        real_password.encode("utf-8"),
        bcrypt.gensalt()
    ).decode("utf-8")

    user = MagicMock()
    user.user_id = 1
    user.username = 'existinguser'
    user.password_hash = real_hash

    result = MagicMock()
    result.scalar_one_or_none.return_value = user

    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    return db

@pytest.fixture()
def client_with_mock_db_execute_present(client, mock_db_execute_present):
    """
    Overrides the real get_db dependency with the 'user exists' mock.
    """
    async def override_get_db():
        yield mock_db_execute_present

    app.dependency_overrides[get_db] = override_get_db
    yield client
    app.dependency_overrides.clear()

@pytest.fixture()
def mock_current_user():
    """
    Returns a TokenData object that simulates an authenticated user.
    This bypasses JWT verification entirely.
    """
    return TokenData(user_id=1, username="existinguser")

@pytest.fixture()
def mock_db_execute_project_present():
    """
    Mocked async database session that returns a project.
    """
    db = MagicMock()

    project = MagicMock()
    project.project_id = 1
    project.name = 'project'
    project.description = 'The project relates to construction.'
    project.user_id = 1
    project.created_at = datetime(2030, 12, 31, tzinfo=timezone.utc)

    result = MagicMock()
    result.scalar_one_or_none.return_value = project

    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    return db

@pytest.fixture()
def client_with_project_db_and_auth(
    client,
    mock_db_execute_project_present,
    mock_current_user,
):
    """
    Overrides both the database and authentication dependencies.
    """

    async def override_get_db():
        yield mock_db_execute_project_present

    async def override_get_current_user():
        return mock_current_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    yield client

    app.dependency_overrides.clear()

@pytest.fixture()
def client_with_project_db_and_auth_with_unique_project(
    client,
    mock_db_execute_none,
    mock_current_user,
):
    """
    Overrides both the database and authentication dependencies.
    """

    async def override_get_db():
        yield mock_db_execute_none

    async def override_get_current_user():
        return mock_current_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    yield client

    app.dependency_overrides.clear()