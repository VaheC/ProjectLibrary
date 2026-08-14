import pytest
from sqlalchemy.exc import IntegrityError

############# post-auth router #############
@pytest.mark.parametrize(
    "auth_data",
    (
        {
            "login": "testuser1",
            "password": "testpassword1",
            "repeat_password": "testpassword1",
        },
    ),
)
def test_post_auth_success(
    client_with_mock_db_execute_none,
    mock_db_execute_none,
    auth_data,
):
    created_objects = []

    def add_side_effect(obj):
        created_objects.append(obj)

    async def flush_side_effect():
        for obj in created_objects:
            if hasattr(obj, "user_id"):
                obj.user_id = 1

    mock_db_execute_none.add.side_effect = add_side_effect
    mock_db_execute_none.flush.side_effect = flush_side_effect

    response = client_with_mock_db_execute_none.post(
        "/auth",
        json=auth_data,
    )

    assert response.status_code == 200

    data = response.json()

    assert data["message"] == "User created successfully"
    assert data["user_id"] == 1
    assert data["username"] == auth_data["login"]

    mock_db_execute_none.add.assert_called_once()
    mock_db_execute_none.flush.assert_awaited_once()

@pytest.mark.parametrize(
    'auth_data',
    [
        {"password": "testpassword1", "repeat_password": "testpassword1"}, 
        {"login": "testuser1", "password": "testpassword1"}
    ]
)
def test_post_auth_missing_required_fields(client, auth_data):
    response = client.post("/auth", json=auth_data)
    assert response.status_code == 422

@pytest.mark.parametrize(
    'auth_data',
    [
        {
            "login": "testuser1", 
            "password": "testpassword1", 
            "repeat_password": "differentpassword"
        },
        {
            "login": "testuser1", 
            "password": "short", 
            "repeat_password": "short"
        },
        {
            "login": "",
            "password": "testpassword1",
            "repeat_password": "testpassword1",
        },
        {
            "login": " ",
            "password": "testpassword1",
            "repeat_password": "testpassword1",
        },
        {
            "login": "     ",
            "password": "testpassword1",
            "repeat_password": "testpassword1",
        }
    ]
)
def test_post_auth_invalid_data_logic(
    client_with_mock_db_execute_none,
    auth_data
):
    response = client_with_mock_db_execute_none.post("/auth", json=auth_data)
    assert response.status_code == 400

def test_post_auth_user_already_exists(
    client_with_mock_db_execute_present,
    mock_db_execute_present
):
    auth_data = {
        "login": "existinguser",
        "password": "testpassword1",
        "repeat_password": "testpassword1"
    }
    
    response = client_with_mock_db_execute_present.post("/auth", json=auth_data)
    
    assert response.status_code == 400
    assert "Username already exists" in response.json()["detail"]

    mock_db_execute_present.execute.assert_awaited_once()
    mock_db_execute_present.add.assert_not_called()

def test_post_auth_integrity_failure(
    client_with_mock_db_execute_none,
    mock_db_execute_none
):
    auth_data = {
        "login": "testuser1",
        "password": "testpassword1",
        "repeat_password": "testpassword1",
    }

    mock_db_execute_none.flush.side_effect = IntegrityError(
        statement="INSERT INTO users ...",
        params={},
        orig=Exception("duplicate key value violates unique constraint"),
    )

    response = client_with_mock_db_execute_none.post(
        "/auth",
        json=auth_data,
    )

    assert response.status_code == 400
    assert "Username already exists" in response.json()["detail"]

    mock_db_execute_none.flush.assert_awaited_once()
    mock_db_execute_none.add.assert_called_once()

############# post-login router #############

@pytest.mark.parametrize(
    'login_data',
    (
        {
            'login': 'existinguser',
            'password': 'testpassword1'
        },
    )
)
def test_post_login_success(
    client_with_mock_db_execute_present,
    mock_db_execute_present,
    login_data,
):
    response = client_with_mock_db_execute_present.post(
        "/login",
        json=login_data,
    )

    assert response.status_code == 200

    data = response.json()

    assert data["message"] == "Login successful"
    assert data["user_id"] == 1
    assert data["username"] == login_data["login"]
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == 3600
    
    mock_db_execute_present.execute.assert_awaited_once()

@pytest.mark.parametrize(
    'login_data',
    [
        {"login": "testpassword1"}, 
        {"password": "testpassword1"}
    ]
)
def test_post_login_missing_required_fields(client, login_data):
    response = client.post("/login", json=login_data)
    assert response.status_code == 422