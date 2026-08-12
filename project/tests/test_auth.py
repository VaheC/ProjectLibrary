async def test_register_success(client):
    response = await client.post(
        "/auth",
        json={
            "login": "newuser",
            "password": "password123",
            "repeat_password": "password123",
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["message"] == "User created successfully"
    assert data["username"] == "newuser"
    assert "user_id" in data


async def test_register_password_mismatch(client):
    response = await client.post(
        "/auth",
        json={
            "login": "newuser",
            "password": "password123",
            "repeat_password": "differentpassword",
        },
    )

    assert response.status_code == 400
    assert "Passwords do not match" in response.json()["detail"]


async def test_register_short_password(client):
    response = await client.post(
        "/auth",
        json={
            "login": "newuser",
            "password": "short",
            "repeat_password": "short",
        },
    )

    assert response.status_code == 400
    assert "at least 8 characters" in response.json()["detail"]


async def test_register_duplicate_user(client, register_user):
    await register_user(username="duplicateuser")

    response = await client.post(
        "/auth",
        json={
            "login": "duplicateuser",
            "password": "password123",
            "repeat_password": "password123",
        },
    )

    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]


async def test_login_success(client, register_user):
    await register_user(username="loginuser")

    response = await client.post(
        "/login",
        json={
            "login": "loginuser",
            "password": "password123",
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["message"] == "Login successful"
    assert data["username"] == "loginuser"
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == 3600
    assert "access_token" in data


async def test_login_wrong_password(client, register_user):
    await register_user(username="loginuser")

    response = await client.post(
        "/login",
        json={
            "login": "loginuser",
            "password": "wrongpassword",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid username or password"


async def test_login_unknown_user(client):
    response = await client.post(
        "/login",
        json={
            "login": "unknownuser",
            "password": "password123",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid username or password"