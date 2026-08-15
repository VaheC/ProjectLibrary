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
from fastapi import HTTPException

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

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
    result.scalars.return_value.all.return_value = []


    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.delete = AsyncMock()

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
    db.delete = AsyncMock()

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
    db.delete = AsyncMock()

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

@pytest.fixture()
def mock_db_execute_projects_present():
    """
    Mocked async database session that returns all projects.
    """
    db = MagicMock()

    projects_list = []

    for i in range(3):
        project = MagicMock()
        project.project_id = i + 1
        project.name = f'project{i + 1}'
        project.description = f'The project relates to construction {i + 1}.'
        project.user_id = 1
        project.created_at = datetime(2030, 12, 25 + i, tzinfo=timezone.utc)

        project.user = MagicMock()
        project.user.username = 'existinguser'

        project.documents = []
        for j in range(i + 1):
            document = MagicMock()
            document.document_id = j + 1
            document.document_url = f'url_{j + 1}'
            project.documents.append(document)

        projects_list.append(project)

    result = MagicMock()
    result.scalars.return_value.all.return_value = projects_list

    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.delete = AsyncMock()

    return db

@pytest.fixture()
def client_with_all_projects_db_and_auth(
    client,
    mock_db_execute_projects_present,
    mock_current_user,
):
    """
    Overrides both the database and authentication dependencies.
    """

    async def override_get_db():
        yield mock_db_execute_projects_present

    async def override_get_current_user():
        return mock_current_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    yield client

    app.dependency_overrides.clear()

@pytest.fixture()
def client_with_empty_projects_db_and_auth(
    client,
    mock_db_execute_none,
    mock_current_user,
):
    """
    Overrides DB to return no projects and authenticates the user.
    Used for testing GET /projects when user has no projects.
    """

    async def override_get_db():
        yield mock_db_execute_none

    async def override_get_current_user():
        return mock_current_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    yield client

    app.dependency_overrides.clear()

@pytest.fixture()
def mock_accessible_project():
    """
    Returns a mock project object that simulates
    what get_accessible_project would return.
    """
    project = MagicMock()
    project.project_id = 1
    project.name = 'Test Project'
    project.description = 'A test project description.'
    project.user_id = 1
    project.created_at = datetime(2030, 12, 25, tzinfo=timezone.utc)

    # Mock the owner relationship
    project.user = MagicMock()
    project.user.username = 'existinguser'

    # Mock the documents relationship
    document1 = MagicMock()
    document1.document_id = 1
    document1.document_url = 'https://example.com/doc1.pdf'

    document2 = MagicMock()
    document2.document_id = 2
    document2.document_url = 'https://example.com/doc2.pdf'

    project.documents = [document1, document2]

    return project

@pytest.fixture()
def client_with_accessible_project(
    client,
    mock_current_user,
    mock_accessible_project,
):
    """
    Overrides auth and patches get_accessible_project
    to return a mock project.
    """

    async def override_get_current_user():
        return mock_current_user

    app.dependency_overrides[get_current_user] = override_get_current_user

    with patch(
        'routers.projects.get_accessible_project',
        new_callable=AsyncMock,
        return_value=mock_accessible_project,
    ):
        yield client

    app.dependency_overrides.clear()

@pytest.fixture()
def client_with_inaccessible_project(
    client,
    mock_current_user,
):
    async def override_get_current_user():
        return mock_current_user

    app.dependency_overrides[get_current_user] = override_get_current_user

    with patch(
        'routers.projects.get_accessible_project',
        new_callable=AsyncMock,
        side_effect=HTTPException(
            status_code=404, 
            detail="Project not found"
        ),
    ):
        yield client

    app.dependency_overrides.clear()

@pytest.fixture()
def client_with_forbidden_project(
    client,
    mock_current_user,
):
    """
    Overrides auth and patches get_accessible_project
    to raise 403 Forbidden.
    """

    async def override_get_current_user():
        return mock_current_user

    app.dependency_overrides[get_current_user] = override_get_current_user

    with patch(
        'routers.projects.get_accessible_project',
        new_callable=AsyncMock,
        side_effect=HTTPException(
            status_code=403,
            detail="You do not have access to this project",
        ),
    ):
        yield client

    app.dependency_overrides.clear()

@pytest.fixture()
def client_with_accessible_project_and_mock_db(
    client,
    mock_current_user,
    mock_accessible_project,
    mock_db_execute_none,
):
    """
    For PUT success case:
    1. Patches get_accessible_project to return a project (user has access).
    2. Overrides DB to return None for the duplicate name check (name is unique).
    """
    async def override_get_current_user():
        return mock_current_user

    async def override_get_db():
        yield mock_db_execute_none

    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_db] = override_get_db

    with patch(
        'routers.projects.get_accessible_project',
        new_callable=AsyncMock,
        return_value=mock_accessible_project,
    ):
        yield client

    app.dependency_overrides.clear()


@pytest.fixture()
def mock_db_execute_duplicate_name():
    """
    Mocked DB that returns an existing project when checking for duplicate names.
    """
    db = MagicMock()

    existing_project = MagicMock()
    existing_project.project_id = 99

    result = MagicMock()
    result.scalar_one_or_none.return_value = existing_project

    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.delete = AsyncMock()

    return db


@pytest.fixture()
def client_with_accessible_project_and_duplicate_name(
    client,
    mock_current_user,
    mock_accessible_project,
    mock_db_execute_duplicate_name,
):
    """
    For PUT duplicate name case:
    1. Patches get_accessible_project to return a project (user has access).
    2. Overrides DB to return an existing project (duplicate name found).
    """
    async def override_get_current_user():
        return mock_current_user

    async def override_get_db():
        yield mock_db_execute_duplicate_name

    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_db] = override_get_db

    with patch(
        'routers.projects.get_accessible_project',
        new_callable=AsyncMock,
        return_value=mock_accessible_project,
    ):
        yield client

    app.dependency_overrides.clear()

class FakeS3Context:
    """Simulates `async with get_s3_client() as s3_client:`"""
    def __init__(self, mock_s3):
        self.mock_s3 = mock_s3

    async def __aenter__(self):
        return self.mock_s3

    async def __aexit__(self, *args):
        pass

@pytest.fixture()
def get_fake_s3_context_class():
    return FakeS3Context

@pytest.fixture()
def mock_db_execute_with_documents():
    """
    Mocked DB that returns a list of documents when queried.
    """
    db = MagicMock()

    doc1 = MagicMock()
    doc1.document_id = 10
    doc1.document_url = "https://test-bucket.s3.us-east-1.amazonaws.com/projects/1/doc1.pdf"

    doc2 = MagicMock()
    doc2.document_id = 20
    doc2.document_url = "https://test-bucket.s3.us-east-1.amazonaws.com/projects/1/doc2.pdf"

    result = MagicMock()
    result.scalars.return_value.all.return_value = [doc1, doc2]

    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.delete = AsyncMock()

    return db

@pytest.fixture()
def client_with_accessible_project_and_documents(
    client,
    mock_current_user,
    mock_accessible_project,
    mock_db_execute_with_documents,
):
    """
    For GET documents success case:
    1. Patches get_accessible_project to return a project (user has access).
    2. Overrides DB to return 2 mock documents.
    """
    async def override_get_current_user():
        return mock_current_user

    async def override_get_db():
        yield mock_db_execute_with_documents

    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_db] = override_get_db

    with patch(
        'routers.projects.get_accessible_project',
        new_callable=AsyncMock,
        return_value=mock_accessible_project,
    ):
        yield client

    app.dependency_overrides.clear()

@pytest.fixture()
def mock_db_execute_invite_success():
    """
    DB mock for successful invite:
    1. First query (find user) returns a user object.
    2. Second query (check shared project) returns None.
    """
    db = MagicMock()

    invited_user = MagicMock()
    invited_user.user_id = 2
    invited_user.username = 'inviteduser'

    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = invited_user

    shared_result = MagicMock()
    shared_result.scalar_one_or_none.return_value = None

    # side_effect makes db.execute return user_result first, then shared_result
    db.execute = AsyncMock(side_effect=[user_result, shared_result])
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.delete = AsyncMock()

    return db

@pytest.fixture()
def client_with_invite_success_db(
    client, mock_current_user, mock_accessible_project, mock_db_execute_invite_success
):
    async def override_get_current_user(): return mock_current_user
    async def override_get_db(): yield mock_db_execute_invite_success

    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_db] = override_get_db

    with patch('routers.projects.get_accessible_project', new_callable=AsyncMock, return_value=mock_accessible_project):
        yield client
    app.dependency_overrides.clear()


@pytest.fixture()
def mock_db_execute_invite_self():
    """
    DB mock for inviting yourself:
    First query returns a user with the SAME user_id as the current user.
    """
    db = MagicMock()
    self_user = MagicMock()
    self_user.user_id = 1  # Matches mock_current_user.user_id
    self_user.username = 'existinguser'
    
    result = MagicMock()
    result.scalar_one_or_none.return_value = self_user
    
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.delete = AsyncMock()
    return db

@pytest.fixture()
def client_with_invite_self_db(
    client, mock_current_user, mock_accessible_project, mock_db_execute_invite_self
):
    async def override_get_current_user(): return mock_current_user
    async def override_get_db(): yield mock_db_execute_invite_self

    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_db] = override_get_db

    with patch('routers.projects.get_accessible_project', new_callable=AsyncMock, return_value=mock_accessible_project):
        yield client
    app.dependency_overrides.clear()


@pytest.fixture()
def mock_db_execute_user_already_shared():
    """
    DB mock for already shared user:
    1. First query (find user) returns a user.
    2. Second query (check shared) returns a SharedProject object.
    """
    db = MagicMock()

    invited_user = MagicMock()
    invited_user.user_id = 2

    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = invited_user

    shared_project = MagicMock()
    shared_result = MagicMock()
    shared_result.scalar_one_or_none.return_value = shared_project

    db.execute = AsyncMock(side_effect=[user_result, shared_result])
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.delete = AsyncMock()

    return db

@pytest.fixture()
def client_with_already_shared_db(
    client, mock_current_user, mock_accessible_project, mock_db_execute_user_already_shared
):
    async def override_get_current_user(): return mock_current_user
    async def override_get_db(): yield mock_db_execute_user_already_shared

    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_db] = override_get_db

    with patch('routers.projects.get_accessible_project', new_callable=AsyncMock, return_value=mock_accessible_project):
        yield client
    app.dependency_overrides.clear()

@pytest.fixture()
def mock_db_execute_document_present():
    """
    Mocked DB that returns a document when queried by document_id.
    """
    db = MagicMock()

    document = MagicMock()
    document.document_id = 10
    document.project_id = 1  # Matches mock_accessible_project.project_id
    document.document_url = "https://test-bucket.s3.us-east-1.amazonaws.com/projects/1/doc1.pdf"

    result = MagicMock()
    result.scalar_one_or_none.return_value = document

    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.delete = AsyncMock()

    return db