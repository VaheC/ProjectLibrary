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

