import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from botocore.exceptions import ClientError
from fastapi import HTTPException

from main import app
from db.db_session import get_db
from dependencies.auth import get_current_user


#################### get-document/{document_id} ####################
def test_download_document_success(
    client,
    mock_current_user,
    mock_accessible_project,
    mock_db_execute_document_present,
    get_fake_s3_context_class,
    get_fake_s3_body_class
):
    async def override_get_current_user():
        return mock_current_user
    async def override_get_db():
        yield mock_db_execute_document_present

    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_db] = override_get_db

    mock_s3 = AsyncMock()
    fake_body = get_fake_s3_body_class(b"fake pdf content bytes")
    mock_s3.get_object.return_value = {
        "Body": fake_body,
        "ContentType": "application/pdf"
    }
    
    fake_s3 = get_fake_s3_context_class(mock_s3)

    with patch('routers.documents.get_accessible_project', new_callable=AsyncMock, return_value=mock_accessible_project), \
         patch('routers.documents.get_s3_client', return_value=fake_s3):
        
        response = client.get("/document/10")

    assert response.status_code == 200
    assert b"fake pdf content bytes" in response.content
    
    mock_s3.get_object.assert_awaited_once()
    
    app.dependency_overrides.clear()

def test_download_document_not_found(
    client,
    mock_current_user,
    mock_db_execute_none,
):
    """
    Uses mock_db_execute_none which returns None for scalar_one_or_none().
    The route should immediately return 404 before checking access or S3.
    """
    async def override_get_current_user():
        return mock_current_user
    async def override_get_db():
        yield mock_db_execute_none

    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_db] = override_get_db

    response = client.get("/document/999")

    assert response.status_code == 404
    assert "Document not found" in response.json()["detail"]
    
    app.dependency_overrides.clear()

def test_download_document_forbidden(
    client,
    mock_current_user,
    mock_db_execute_document_present,
):
    """
    The document exists in the DB, but the user is a Participant 
    and the route requires Owner (or the user has no access at all).
    """
    async def override_get_current_user():
        return mock_current_user
    async def override_get_db():
        yield mock_db_execute_document_present

    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_db] = override_get_db

    with patch(
        'routers.documents.get_accessible_project', 
        new_callable=AsyncMock, 
        side_effect=HTTPException(
            status_code=403, 
            detail="You do not have access to this project"
        )
    ):
        response = client.get("/document/10")

    assert response.status_code == 403
    assert "do not have access" in response.json()["detail"]
    
    app.dependency_overrides.clear()