async def test_create_project_success(
    client,
    register_user,
    login_user,
    create_project,
):
    await register_user(username="owner")
    token = await login_user(username="owner")

    project = await create_project(token)

    assert project["message"] == "Project created successfully"
    assert project["name"] == "Test Project"
    assert project["owner_username"] == "owner"
    assert "project_id" in project


async def test_create_project_short_name(
    client,
    register_user,
    login_user,
    auth_headers,
):
    await register_user(username="owner")
    token = await login_user(username="owner")

    response = await client.post(
        "/project",
        json={
            "name": "ab",
            "description": "This is a valid description",
        },
        headers=auth_headers(token),
    )

    assert response.status_code == 400
    assert "at least 3 characters" in response.json()["detail"]


async def test_create_project_short_description(
    client,
    register_user,
    login_user,
    auth_headers,
):
    await register_user(username="owner")
    token = await login_user(username="owner")

    response = await client.post(
        "/project",
        json={
            "name": "Valid Name",
            "description": "short",
        },
        headers=auth_headers(token),
    )

    assert response.status_code == 400
    assert "at least 10 characters" in response.json()["detail"]


async def test_get_projects_returns_owned_project(
    client,
    register_user,
    login_user,
    auth_headers,
    create_project,
):
    await register_user(username="owner")
    token = await login_user(username="owner")

    created_project = await create_project(token)

    response = await client.get(
        "/projects",
        headers=auth_headers(token),
    )

    assert response.status_code == 200

    data = response.json()

    assert data["count"] == 1
    assert data["projects"][0]["project_id"] == created_project["project_id"]


async def test_get_project_info_owner_success(
    client,
    register_user,
    login_user,
    auth_headers,
    create_project,
):
    await register_user(username="owner")
    token = await login_user(username="owner")

    project = await create_project(token)

    response = await client.get(
        f"/project/{project['project_id']}/info",
        headers=auth_headers(token),
    )

    assert response.status_code == 200

    data = response.json()

    assert data["project_id"] == project["project_id"]
    assert data["name"] == project["name"]
    assert data["owner_username"] == "owner"


async def test_get_project_info_without_access_denied(
    client,
    register_user,
    login_user,
    auth_headers,
    create_project,
):
    await register_user(username="owner")
    owner_token = await login_user(username="owner")

    project = await create_project(owner_token)

    await register_user(username="stranger")
    stranger_token = await login_user(username="stranger")

    response = await client.get(
        f"/project/{project['project_id']}/info",
        headers=auth_headers(stranger_token),
    )

    assert response.status_code == 403


async def test_invite_user_success_and_participant_can_access_project(
    client,
    register_user,
    login_user,
    auth_headers,
    create_project,
    invite_user,
):
    await register_user(username="owner")
    owner_token = await login_user(username="owner")

    await register_user(username="participant")

    project = await create_project(owner_token)

    await invite_user(
        owner_token=owner_token,
        project_id=project["project_id"],
        username="participant",
        expected_status=200,
    )

    participant_token = await login_user(username="participant")

    response = await client.get(
        f"/project/{project['project_id']}/info",
        headers=auth_headers(participant_token),
    )

    assert response.status_code == 200
    assert response.json()["project_id"] == project["project_id"]


async def test_participant_can_update_project_info(
    client,
    register_user,
    login_user,
    auth_headers,
    create_project,
    invite_user,
):
    await register_user(username="owner")
    owner_token = await login_user(username="owner")

    await register_user(username="participant")

    project = await create_project(owner_token)

    await invite_user(
        owner_token=owner_token,
        project_id=project["project_id"],
        username="participant",
        expected_status=200,
    )

    participant_token = await login_user(username="participant")

    response = await client.put(
        f"/project/{project['project_id']}/info",
        json={
            "name": "Updated By Participant",
            "description": "Participant updated this project",
        },
        headers=auth_headers(participant_token),
    )

    assert response.status_code == 200

    data = response.json()

    assert data["name"] == "Updated By Participant"
    assert data["description"] == "Participant updated this project"


async def test_participant_cannot_delete_project(
    client,
    register_user,
    login_user,
    auth_headers,
    create_project,
    invite_user,
):
    await register_user(username="owner")
    owner_token = await login_user(username="owner")

    await register_user(username="participant")

    project = await create_project(owner_token)

    await invite_user(
        owner_token=owner_token,
        project_id=project["project_id"],
        username="participant",
        expected_status=200,
    )

    participant_token = await login_user(username="participant")

    response = await client.delete(
        f"/project/{project['project_id']}",
        headers=auth_headers(participant_token),
    )

    assert response.status_code == 403


async def test_participant_cannot_invite_users(
    client,
    register_user,
    login_user,
    auth_headers,
    create_project,
    invite_user,
):
    await register_user(username="owner")
    owner_token = await login_user(username="owner")

    await register_user(username="participant")
    await register_user(username="thirduser")

    project = await create_project(owner_token)

    await invite_user(
        owner_token=owner_token,
        project_id=project["project_id"],
        username="participant",
        expected_status=200,
    )

    participant_token = await login_user(username="participant")

    response = await client.post(
        f"/project/{project['project_id']}/invite",
        params={"user": "thirduser"},
        headers=auth_headers(participant_token),
    )

    assert response.status_code == 403


async def test_invite_unknown_user(
    client,
    register_user,
    login_user,
    create_project,
    invite_user,
):
    await register_user(username="owner")
    owner_token = await login_user(username="owner")

    project = await create_project(owner_token)

    response = await invite_user(
        owner_token=owner_token,
        project_id=project["project_id"],
        username="does-not-exist",
        expected_status=404,
    )

    assert "User not found" in response.json()["detail"]


async def test_invite_self(
    client,
    register_user,
    login_user,
    create_project,
    invite_user,
):
    await register_user(username="owner")
    owner_token = await login_user(username="owner")

    project = await create_project(owner_token)

    response = await invite_user(
        owner_token=owner_token,
        project_id=project["project_id"],
        username="owner",
        expected_status=400,
    )

    assert "cannot invite yourself" in response.json()["detail"]


async def test_invite_duplicate_user(
    client,
    register_user,
    login_user,
    create_project,
    invite_user,
):
    await register_user(username="owner")
    owner_token = await login_user(username="owner")

    await register_user(username="participant")

    project = await create_project(owner_token)

    await invite_user(
        owner_token=owner_token,
        project_id=project["project_id"],
        username="participant",
        expected_status=200,
    )

    response = await invite_user(
        owner_token=owner_token,
        project_id=project["project_id"],
        username="participant",
        expected_status=400,
    )

    assert "already has access" in response.json()["detail"]


async def test_delete_project_deletes_s3_documents(
    client,
    register_user,
    login_user,
    auth_headers,
    create_project,
    upload_documents,
    fake_s3,
):
    await register_user(username="owner")
    token = await login_user(username="owner")

    project = await create_project(token)

    await upload_documents(
        token=token,
        project_id=project["project_id"],
    )

    response = await client.delete(
        f"/project/{project['project_id']}",
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    assert fake_s3.delete_object.called