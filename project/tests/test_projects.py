import pytest

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
