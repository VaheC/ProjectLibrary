async def test_upload_single_document(
    client,
    register_user,
    login_user,
    create_project,
    upload_documents,
    fake_s3,
):
    await register_user(username="owner")
    token = await login_user(username="owner")

    project = await create_project(token)

    result = await upload_documents(
        token=token,
        project_id=project["project_id"],
    )

    assert result["uploaded_count"] == 1
    assert len(result["documents"]) == 1
    assert result["documents"][0]["document_url"].startswith("https://")

    fake_s3.put_object.assert_called_once()


async def test_upload_multiple_documents(
    client,
    register_user,
    login_user,
    create_project,
    upload_documents,
    fake_s3,
):
    await register_user(username="owner")
    token = await login_user(username="owner")

    project = await create_project(token)

    files = [
        (
            "files",
            (
                "file1.txt",
                b"content one",
                "text/plain",
            ),
        ),
        (
            "files",
            (
                "file2.txt",
                b"content two",
                "text/plain",
            ),
        ),
    ]

    result = await upload_documents(
        token=token,
        project_id=project["project_id"],
        files=files,
    )

    assert result["uploaded_count"] == 2
    assert len(result["documents"]) == 2
    assert fake_s3.put_object.call_count == 2


async def test_get_project_documents(
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

    upload_result = await upload_documents(
        token=token,
        project_id=project["project_id"],
    )

    response = await client.get(
        f"/project/{project['project_id']}/documents",
        headers=auth_headers(token),
    )

    assert response.status_code == 200

    documents = response.json()

    assert len(documents) == 1
    assert documents[0]["document_id"] == upload_result["documents"][0]["document_id"]


async def test_download_document(
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

    upload_result = await upload_documents(
        token=token,
        project_id=project["project_id"],
    )

    document_id = upload_result["documents"][0]["document_id"]

    response = await client.get(
        f"/document/{document_id}",
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    assert response.content == b"test-file-content"
    assert fake_s3.get_object.called


async def test_user_without_access_cannot_download_document(
    client,
    register_user,
    login_user,
    auth_headers,
    create_project,
    upload_documents,
    fake_s3,
):
    await register_user(username="owner")
    owner_token = await login_user(username="owner")

    project = await create_project(owner_token)

    upload_result = await upload_documents(
        token=owner_token,
        project_id=project["project_id"],
    )

    await register_user(username="stranger")
    stranger_token = await login_user(username="stranger")

    document_id = upload_result["documents"][0]["document_id"]

    response = await client.get(
        f"/document/{document_id}",
        headers=auth_headers(stranger_token),
    )

    assert response.status_code == 403
    assert not fake_s3.get_object.called


async def test_participant_can_update_document(
    client,
    register_user,
    login_user,
    auth_headers,
    create_project,
    invite_user,
    upload_documents,
    fake_s3,
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

    upload_result = await upload_documents(
        token=owner_token,
        project_id=project["project_id"],
    )

    participant_token = await login_user(username="participant")

    document_id = upload_result["documents"][0]["document_id"]

    fake_s3.put_object.reset_mock()

    response = await client.put(
        f"/document/{document_id}",
        headers=auth_headers(participant_token),
        files={
            "file": (
                "updated.txt",
                b"updated content",
                "text/plain",
            )
        },
    )

    assert response.status_code == 200
    assert fake_s3.put_object.called


async def test_participant_cannot_delete_document(
    client,
    register_user,
    login_user,
    auth_headers,
    create_project,
    invite_user,
    upload_documents,
    fake_s3,
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

    upload_result = await upload_documents(
        token=owner_token,
        project_id=project["project_id"],
    )

    participant_token = await login_user(username="participant")

    document_id = upload_result["documents"][0]["document_id"]

    response = await client.delete(
        f"/document/{document_id}",
        headers=auth_headers(participant_token),
    )

    assert response.status_code == 403
    assert not fake_s3.delete_object.called


async def test_owner_can_delete_document(
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

    upload_result = await upload_documents(
        token=token,
        project_id=project["project_id"],
    )

    document_id = upload_result["documents"][0]["document_id"]

    response = await client.delete(
        f"/document/{document_id}",
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    assert fake_s3.delete_object.called