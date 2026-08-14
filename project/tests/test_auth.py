import pytest


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
        """
        Simulates SQLAlchemy assigning a primary key after flush().
        """
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