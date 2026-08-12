import pytest
import jwt

from fastapi import HTTPException

from dependencies.jwt import create_access_token
from dependencies.auth import verify_token
from dependencies.bucket_client import get_s3_key_from_url

from config.config import settings


def test_create_access_token():
    token = create_access_token(
        data={
            "user_id": 1,
            "username": "testuser",
        }
    )

    payload = jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[settings.ALGORITHM],
    )

    assert payload["user_id"] == 1
    assert payload["username"] == "testuser"
    assert "exp" in payload


def test_verify_token_success():
    token = create_access_token(
        data={
            "user_id": 10,
            "username": "validuser",
        }
    )

    token_data = verify_token(token)

    assert token_data.user_id == 10
    assert token_data.username == "validuser"


def test_verify_token_invalid():
    with pytest.raises(HTTPException) as exc:
        verify_token("invalid-token")

    assert exc.value.status_code == 401


def test_get_s3_key_from_url():
    url = (
        f"https://{settings.AWS_S3_BUCKET}"
        f".s3.{settings.AWS_REGION}.amazonaws.com/"
        f"projects/1/file.txt"
    )

    key = get_s3_key_from_url(url)

    assert key == "projects/1/file.txt"