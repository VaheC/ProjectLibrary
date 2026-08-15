import pytest
import os
from unittest.mock import patch, AsyncMock, MagicMock
from botocore.exceptions import ClientError
from fastapi import HTTPException
from main import app
from db.db_session import get_db
from dependencies.auth import get_current_user


#################### post-project ####################
@pytest.mark.parametrize(
    'project_data',
    [
        {
            'name': 'project1',
            'description': 'The project relates to finance.'
        }
    ]
)
def test_post_project_success(
    client_with_project_db_and_auth_with_unique_project,
    mock_db_execute_none,
    project_data
):
    created_objects = []

    def add_side_effect(obj):
        created_objects.append(obj)

    async def flush_side_effect():
        for obj in created_objects:
            if hasattr(obj, "project_id"):
                obj.project_id = 1
            if hasattr(obj, "shared_project_id"):
                obj.shared_project_id = 1

    mock_db_execute_none.add.side_effect = add_side_effect
    mock_db_execute_none.flush.side_effect = flush_side_effect

    response = client_with_project_db_and_auth_with_unique_project.post(
        "/project",
        json=project_data,
    )

    assert response.status_code == 200

    data = response.json()
    assert data["message"] == "Project created successfully"
    assert data["project_id"] == 1
    assert data["name"] == "project1"
    assert data["description"] == "The project relates to finance."
    assert data["owner_id"] == 1
    assert data["owner_username"] == "existinguser"
    
@pytest.mark.parametrize(
    'project_data',
    [
        {
            'name': 'fi',
            'description': 'The project relates to finance.'
        },
        {
            'name': '     ',
            'description': 'The project relates to art.'
        },
        {
            'name': '',
            'description': 'The project relates to art.'
        }
    ]
)
def test_post_project_short_name(
    client_with_project_db_and_auth_with_unique_project,
    project_data
):
    response = client_with_project_db_and_auth_with_unique_project.post(
        "/project",
        json=project_data,
    )

    assert response.status_code == 400
    assert "Project name must be at least 3 characters long" in response.json()["detail"]

@pytest.mark.parametrize(
    'project_data',
    [
        {
            'name': 'project1',
            'description': 'The pro.'
        },
        {
            'name': 'project1',
            'description': ''
        },
        {
            'name': 'project1',
            'description': '                        '
        }
    ]
)
def test_post_project_short_description(
    client_with_project_db_and_auth_with_unique_project,
    project_data
):
    response = client_with_project_db_and_auth_with_unique_project.post(
        "/project",
        json=project_data,
    )

    assert response.status_code == 400
    assert (
        "Project description must be at least 10 characters long" 
        in response.json()["detail"]
    )

@pytest.mark.parametrize(
    'project_data',
    [
        {
            'name': 'project',
            'description': 'The project relates to construction.'
        }
    ]
)
def test_post_project_existing_project(
    client_with_project_db_and_auth,
    project_data
):
    response = client_with_project_db_and_auth.post(
        "/project",
        json=project_data,
    )

    assert response.status_code == 400
    assert (
        "A project with this name already exists"
        in response.json()["detail"]
    )

#################### post-projects ####################

def test_get_projects_success(
    client_with_all_projects_db_and_auth,
):
    response = client_with_all_projects_db_and_auth.get(
        "/projects"
    )

    assert response.status_code == 200

    data = response.json()
    assert "message" in data
    assert data["count"] == 3
    assert len(data["projects"]) == 3

def test_get_projects_no_project(
    client_with_empty_projects_db_and_auth
):
    response = client_with_empty_projects_db_and_auth.get(
        "/projects"
    )

    assert response.status_code == 200

    data = response.json()
    assert "message" in data
    assert data["count"] == 0
    assert len(data["projects"]) == 0

#################### get-project/{project_id}/info ####################

def test_get_project_info_success(
    client_with_accessible_project,
):
    response = client_with_accessible_project.get(
        "/project/1/info"
    )

    assert response.status_code == 200

    data = response.json()
    assert data["project_id"] == 1
    assert data["name"] == "Test Project"
    assert data["description"] == "A test project description."
    assert data["owner_id"] == 1
    assert data["owner_username"] == "existinguser"
    assert len(data["documents"]) == 2

def test_get_project_info_not_found(
    client_with_inaccessible_project,
):
    response = client_with_inaccessible_project.get(
        "/project/999/info"
    )

    assert response.status_code == 404

def test_get_project_info_forbidden(
    client_with_forbidden_project,
):
    response = client_with_forbidden_project.get(
        "/project/1/info"
    )

    assert response.status_code == 403
    assert "You do not have access to this project" in response.json()["detail"]

#################### put-project/{project_id}/info ####################

def test_put_project_info_success(
    client_with_accessible_project_and_mock_db,
):
    payload = {
        "name": "Updated Project Name",
        "description": "This is a long enough description for the test."
    }
    
    response = client_with_accessible_project_and_mock_db.put(
        "/project/1/info",
        json=payload,
    )

    assert response.status_code == 200
    
    data = response.json()
    assert data["name"] == "Updated Project Name"
    assert data["description"] == "This is a long enough description for the test."
    assert data["project_id"] == 1

@pytest.mark.parametrize(
    'payload',
    [
        {"name": "ab", "description": "This is a valid description."},
        {"name": "   ", "description": "This is a valid description."},
    ]
)
def test_put_project_info_short_name(
    client_with_accessible_project_and_mock_db,
    payload,
):
    response = client_with_accessible_project_and_mock_db.put(
        "/project/1/info",
        json=payload,
    )
    assert response.status_code == 400
    assert "at least 3 characters" in response.json()["detail"]

@pytest.mark.parametrize(
    'payload',
    [
        {"name": "Valid Name", "description": "short"},
        {"name": "Valid Name", "description": "          "}
    ]
)
def test_put_project_info_short_description(
    client_with_accessible_project_and_mock_db,
    payload,
):
    response = client_with_accessible_project_and_mock_db.put(
        "/project/1/info",
        json=payload,
    )
    assert response.status_code == 400
    assert "at least 10 characters" in response.json()["detail"]

def test_put_project_info_not_found(
    client_with_inaccessible_project
):
    valid_payload = {
        "name": "Valid Name",
        "description": "This is a valid description."
    }
    response = client_with_inaccessible_project.put(
        "/project/999/info",
        json=valid_payload
    )
    assert response.status_code == 404
    assert "Project not found" in response.json()["detail"]

def test_put_project_info_forbidden(
    client_with_forbidden_project
):
    valid_payload = {
        "name": "Valid Name",
        "description": "This is a valid description."
    }
    response = client_with_forbidden_project.put(
        "/project/1/info",
        json=valid_payload
    )
    assert response.status_code == 403
    assert "do not have access" in response.json()["detail"]

def test_put_project_info_duplicate_name(
    client_with_accessible_project_and_duplicate_name,
):
    payload = {
        "name": "Existing Name",
        "description": "This is a valid description."
    }
    
    response = client_with_accessible_project_and_duplicate_name.put(
        "/project/1/info",
        json=payload,
    )

    assert response.status_code == 400
    assert "A project with this name already exists" in response.json()["detail"]

#################### delete-/project/{project_id} ####################

def test_delete_project_success_with_documents(
    client,
    mock_current_user,
    mock_accessible_project,
    get_fake_s3_context_class
):
    """
    Owner deletes a project that has documents.
    S3 files should be deleted, and the DB row should be deleted.
    """
    async def override_get_current_user():
        return mock_current_user

    app.dependency_overrides[get_current_user] = override_get_current_user

    mock_db = MagicMock()
    doc1 = MagicMock()
    doc1.document_url = f"https://{os.environ['AWS_S3_BUCKET']}.s3.{os.environ['AWS_REGION']}.amazonaws.com/projects/1/doc1.pdf"
    
    result = MagicMock()
    result.scalars.return_value.all.return_value = [doc1]
    mock_db.execute = AsyncMock(return_value=result)
    mock_db.delete = AsyncMock()

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db

    mock_s3 = AsyncMock()

    fake_s3 = get_fake_s3_context_class(mock_s3)
    with patch(
        'routers.projects.get_accessible_project', 
        new_callable=AsyncMock, 
        return_value=mock_accessible_project
    ), patch('routers.projects.get_s3_client', return_value=fake_s3):
        
        response = client.delete("/project/1")

    assert response.status_code == 200
    assert "deleted successfully" in response.json()["message"]

    mock_s3.delete_object.assert_awaited_once()
    mock_db.delete.assert_awaited_once()
    app.dependency_overrides.clear()

def test_delete_project_success_without_documents(
    client_with_accessible_project_and_mock_db,
    get_fake_s3_context_class
):
    """
    Owner deletes a project with no documents.
    S3 client should NOT be called, but DB delete should happen.
    """
    
    mock_s3 = AsyncMock()

    fake_s3 = get_fake_s3_context_class(mock_s3)
    with patch('routers.projects.get_s3_client', return_value=fake_s3):
        response = client_with_accessible_project_and_mock_db.delete("/project/1")

    assert response.status_code == 200
    assert "deleted successfully" in response.json()["message"]
    
    mock_s3.delete_object.assert_not_awaited()

def test_delete_project_forbidden(
    client_with_forbidden_project,
):
    """
    A participant tries to delete the project.
    get_accessible_project(require_owner=True) raises 403.
    """
    response = client_with_forbidden_project.delete("/project/1")

    assert response.status_code == 403
    assert "do not have access" in response.json()["detail"]

def test_delete_project_not_found(
    client_with_inaccessible_project,
):
    """
    User tries to delete a project that doesn't exist.
    get_accessible_project raises 404.
    """
    response = client_with_inaccessible_project.delete("/project/999")

    assert response.status_code == 404
    assert "Project not found" in response.json()["detail"]

def test_delete_project_s3_generic_error(
    client,
    mock_current_user,
    mock_accessible_project,
    get_fake_s3_context_class
):
    """
    S3 deletion fails with a generic error (e.g., AccessDenied).
    The route should catch it and return 500.
    """
    async def override_get_current_user():
        return mock_current_user

    app.dependency_overrides[get_current_user] = override_get_current_user

    mock_db = MagicMock()
    doc1 = MagicMock()
    doc1.document_url = "https://test.com/doc.pdf"
    result = MagicMock()
    result.scalars.return_value.all.return_value = [doc1]
    mock_db.execute = AsyncMock(return_value=result)
    mock_db.delete = AsyncMock()

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db

    mock_s3 = AsyncMock()
    mock_s3.delete_object.side_effect = ClientError(
        error_response={"Error": {"Code": "AccessDenied", "Message": "Access Denied"}},
        operation_name="DeleteObject"
    )

    fake_s3 = get_fake_s3_context_class(mock_s3)
    with patch('routers.projects.get_accessible_project', new_callable=AsyncMock, return_value=mock_accessible_project), \
         patch('routers.projects.get_s3_client', return_value=fake_s3):
        
        response = client.delete("/project/1")

    assert response.status_code == 500
    assert "Failed to delete project files from S3" in response.json()["detail"]
    
    mock_db.delete.assert_not_awaited()

    app.dependency_overrides.clear()

def test_delete_project_s3_nosuchkey_error(
    client,
    mock_current_user,
    mock_accessible_project,
    get_fake_s3_context_class
):
    """
    S3 deletion fails because the file is already gone (NoSuchKey).
    The route should ignore this specific error and successfully delete the DB row.
    """
    async def override_get_current_user():
        return mock_current_user

    app.dependency_overrides[get_current_user] = override_get_current_user

    mock_db = MagicMock()
    doc1 = MagicMock()
    doc1.document_url = "https://test.com/doc.pdf"
    result = MagicMock()
    result.scalars.return_value.all.return_value = [doc1]
    mock_db.execute = AsyncMock(return_value=result)
    mock_db.delete = AsyncMock()

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db

    mock_s3 = AsyncMock()
    mock_s3.delete_object.side_effect = ClientError(
        error_response={"Error": {"Code": "NoSuchKey", "Message": "Not Found"}},
        operation_name="DeleteObject"
    )

    fake_s3 = get_fake_s3_context_class(mock_s3)
    with patch('routers.projects.get_accessible_project', new_callable=AsyncMock, return_value=mock_accessible_project), \
         patch('routers.projects.get_s3_client', return_value=fake_s3):
        
        response = client.delete("/project/1")

    assert response.status_code == 200
    assert "deleted successfully" in response.json()["message"]
    
    mock_db.delete.assert_awaited_once()

    app.dependency_overrides.clear()

#################### get-/project/{project_id}/documents ####################

def test_get_project_documents_success(
    client_with_accessible_project_and_documents,
):
    response = client_with_accessible_project_and_documents.get(
        "/project/1/documents"
    )

    assert response.status_code == 200
    
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 2
    
    assert data[0]["document_id"] == 10
    assert "doc1.pdf" in data[0]["document_url"]

    assert data[1]["document_id"] == 20
    assert "doc2.pdf" in data[1]["document_url"]

def test_get_project_documents_empty(
    client_with_accessible_project_and_mock_db,
):
    """
    The client_with_accessible_project_and_mock_db fixture uses 
    mock_db_execute_none, which returns [] for scalars().all().
    """
    response = client_with_accessible_project_and_mock_db.get(
        "/project/1/documents"
    )

    assert response.status_code == 200
    
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 0

def test_get_project_documents_not_found(
    client_with_inaccessible_project,
):
    response = client_with_inaccessible_project.get(
        "/project/999/documents"
    )

    assert response.status_code == 404
    assert "Project not found" in response.json()["detail"]

def test_get_project_documents_forbidden(
    client_with_forbidden_project,
):
    response = client_with_forbidden_project.get(
        "/project/1/documents"
    )

    assert response.status_code == 403
    assert "do not have access" in response.json()["detail"]

#################### post-/project/{project_id}/documents ####################

def setup_document_flush(mock_db):
    """Helper to simulate SQLAlchemy assigning IDs after flush()."""
    created_objects = []
    def add_side_effect(obj):
        created_objects.append(obj)
    async def flush_side_effect():
        for i, obj in enumerate(created_objects):
            if hasattr(obj, "document_id"):
                obj.document_id = i + 1
    mock_db.add.side_effect = add_side_effect
    mock_db.flush.side_effect = flush_side_effect

def test_upload_single_document_success(
    client,
    mock_current_user,
    mock_accessible_project,
    mock_db_execute_none,
    get_fake_s3_context_class,
):
    async def override_get_current_user():
        return mock_current_user
    async def override_get_db():
        yield mock_db_execute_none

    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_db] = override_get_db
    setup_document_flush(mock_db_execute_none)

    mock_s3 = AsyncMock()
    fake_s3 = get_fake_s3_context_class(mock_s3)

    with patch(
        'routers.projects.get_accessible_project', 
        new_callable=AsyncMock, 
        return_value=mock_accessible_project
    ), patch('routers.projects.get_s3_client', return_value=fake_s3):

        response = client.post(
            "/project/1/documents",
            files=[("files", ("test.txt", b"hello world", "text/plain"))]
        )

    assert response.status_code == 200
    data = response.json()
    
    assert data["uploaded_count"] == 1
    assert data["documents"][0]["document_id"] == 1
    assert "test-bucket" in data["documents"][0]["document_url"]
    
    mock_s3.put_object.assert_awaited_once()
    mock_db_execute_none.add.assert_called_once()
    
    app.dependency_overrides.clear()

def test_upload_multiple_documents_success(
    client,
    mock_current_user,
    mock_accessible_project,
    mock_db_execute_none,
    get_fake_s3_context_class,
):
    async def override_get_current_user():
        return mock_current_user
    async def override_get_db():
        yield mock_db_execute_none

    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_db] = override_get_db
    setup_document_flush(mock_db_execute_none)

    mock_s3 = AsyncMock()
    fake_s3 = get_fake_s3_context_class(mock_s3)

    with patch(
        'routers.projects.get_accessible_project', 
        new_callable=AsyncMock, 
        return_value=mock_accessible_project
    ), patch('routers.projects.get_s3_client', return_value=fake_s3):
        
        response = client.post(
            "/project/1/documents",
            files=[
                ("files", ("file1.txt", b"content1", "text/plain")),
                ("files", ("file2.pdf", b"content2", "application/pdf"))
            ]
        )

    assert response.status_code == 200
    data = response.json()
    
    assert data["uploaded_count"] == 2
    assert len(data["documents"]) == 2
    assert data["documents"][0]["document_id"] == 1
    assert data["documents"][1]["document_id"] == 2

    assert mock_s3.put_object.await_count == 2
    assert mock_db_execute_none.add.call_count == 2
    
    app.dependency_overrides.clear()

def test_upload_documents_forbidden(
    client_with_forbidden_project,
):
    response = client_with_forbidden_project.post(
        "/project/1/documents",
        files=[("files", ("test.txt", b"data", "text/plain"))]
    )

    assert response.status_code == 403
    assert "do not have access" in response.json()["detail"]

def test_upload_documents_not_found(
    client_with_inaccessible_project,
):
    response = client_with_inaccessible_project.post(
        "/project/999/documents",
        files=[("files", ("test.txt", b"data", "text/plain"))]
    )

    assert response.status_code == 404
    assert "Project not found" in response.json()["detail"]

def test_upload_documents_missing_files_field(
    client_with_accessible_project_and_mock_db,
):
    response = client_with_accessible_project_and_mock_db.post(
        "/project/1/documents",
        data={} 
    )

    assert response.status_code == 422

def test_upload_documents_s3_error_returns_500(
    client,
    mock_current_user,
    mock_accessible_project,
    mock_db_execute_none,
    get_fake_s3_context_class,
):
    async def override_get_current_user():
        return mock_current_user
    
    async def override_get_db():
        yield mock_db_execute_none

    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_db] = override_get_db

    mock_s3 = AsyncMock()
    # Simulate S3 failing immediately
    mock_s3.put_object.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}}, 
        "PutObject"
    )
    fake_s3 = get_fake_s3_context_class(mock_s3)

    with patch(
        'routers.projects.get_accessible_project', 
        new_callable=AsyncMock, 
        return_value=mock_accessible_project
    ), patch('routers.projects.get_s3_client', return_value=fake_s3):
        
        response = client.post(
            "/project/1/documents",
            files=[("files", ("test.txt", b"data", "text/plain"))]
        )

    assert response.status_code == 500
    assert "Failed to upload file to S3" in response.json()["detail"]
    
    # DB operations should not happen if S3 fails
    mock_db_execute_none.add.assert_not_called()
    
    app.dependency_overrides.clear()

def test_upload_documents_s3_error_triggers_cleanup(
    client,
    mock_current_user,
    mock_accessible_project,
    mock_db_execute_none,
    get_fake_s3_context_class,
):
    async def override_get_current_user():
        return mock_current_user
    async def override_get_db():
        yield mock_db_execute_none

    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_db] = override_get_db
    setup_document_flush(mock_db_execute_none)

    mock_s3 = AsyncMock()
    mock_s3.put_object.side_effect = [
        None, 
        ClientError({"Error": {"Code": "500", "Message": "Internal Error"}}, "PutObject")
    ]

    fake_s3 = get_fake_s3_context_class(mock_s3)
    with patch('routers.projects.get_accessible_project', new_callable=AsyncMock, return_value=mock_accessible_project), \
         patch('routers.projects.get_s3_client', return_value=fake_s3):
        
        response = client.post(
            "/project/1/documents",
            files=[
                ("files", ("file1.txt", b"content1", "text/plain")),
                ("files", ("file2.txt", b"content2", "text/plain"))
            ]
        )

    assert response.status_code == 500
    assert "Failed to upload file to S3" in response.json()["detail"]
    
    mock_s3.delete_object.assert_awaited_once()
    
    app.dependency_overrides.clear()

#################### post-/project/{project_id}/invite ####################

def test_invite_user_success(
    client_with_invite_success_db,
    mock_db_execute_invite_success,
):
    response = client_with_invite_success_db.post(
        "/project/1/invite",
        params={"user": "inviteduser"}
    )

    assert response.status_code == 200
    
    mock_db_execute_invite_success.add.assert_called_once()

def test_invite_user_forbidden(
    client_with_forbidden_project,
):
    # Participants are not allowed to invite others (require_owner=True)
    response = client_with_forbidden_project.post(
        "/project/1/invite",
        params={"user": "someuser"}
    )

    assert response.status_code == 403
    assert "do not have access" in response.json()["detail"]

def test_invite_user_project_not_found(
    client_with_inaccessible_project,
):
    response = client_with_inaccessible_project.post(
        "/project/999/invite",
        params={"user": "someuser"}
    )

    assert response.status_code == 404
    assert "Project not found" in response.json()["detail"]

def test_invite_user_not_found_in_db(
    client_with_accessible_project_and_mock_db,
):
    response = client_with_accessible_project_and_mock_db.post(
        "/project/1/invite",
        params={"user": "ghost_user"}
    )

    assert response.status_code == 404
    assert "User not found" in response.json()["detail"]

def test_invite_self(
    client_with_invite_self_db,
):
    response = client_with_invite_self_db.post(
        "/project/1/invite",
        params={"user": "existinguser"}
    )

    assert response.status_code == 400
    assert "cannot invite yourself" in response.json()["detail"]
