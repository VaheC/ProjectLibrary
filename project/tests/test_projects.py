import pytest


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

#################### project/{project_id}/info ####################

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