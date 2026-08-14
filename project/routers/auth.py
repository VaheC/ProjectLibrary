from fastapi import APIRouter, HTTPException, Depends

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

import bcrypt

from db.db import User
from db.db_session import get_db

from models.auth import (
    AuthRequest,
    LoginRequest,
    AuthResponse,
    LoginResponse,
)

from dependencies.jwt import create_access_token

from config.config import settings


router = APIRouter(prefix="", tags=["Authentication"])


@router.post("/auth", response_model=AuthResponse)
async def create_user(
    auth_data: AuthRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new user.
    """

    login = auth_data.login.strip()

    if not login:
        raise HTTPException(
            status_code=400,
            detail="Login must not be empty",
        )

    if auth_data.password != auth_data.repeat_password:
        raise HTTPException(
            status_code=400,
            detail="Passwords do not match",
        )

    if len(auth_data.password) < 8:
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 8 characters long",
        )

    user_query = select(User).where(User.username == login)
    result = await db.execute(user_query)
    existing_user = result.scalar_one_or_none()

    if existing_user:
        raise HTTPException(
            status_code=400,
            detail="Username already exists",
        )

    password_hash = bcrypt.hashpw(
        auth_data.password.encode("utf-8"),
        bcrypt.gensalt(),
    )

    new_user = User(
        username=login,
        password_hash=password_hash.decode("utf-8"),
    )

    db.add(new_user)

    try:
        await db.flush()
    except IntegrityError:
        raise HTTPException(
            status_code=400,
            detail="Username already exists",
        )

    return AuthResponse(
        message="User created successfully",
        user_id=new_user.user_id,
        username=new_user.username,
    )


@router.post("/login", response_model=LoginResponse)
async def login_user(
    login_data: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Login user and return JWT access token.
    """

    login = login_data.login.strip()
    password = login_data.password.strip()

    if not login or not password:
        raise HTTPException(
            status_code=400,
            detail="Login and password must be provided",
        )

    user_query = select(User).where(User.username == login)
    result = await db.execute(user_query)
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password",
        )

    stored_password_hash = user.password_hash.encode("utf-8")
    provided_password = login_data.password.encode("utf-8")

    if not bcrypt.checkpw(provided_password, stored_password_hash):
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password",
        )

    access_token = create_access_token(
        data={
            "user_id": user.user_id,
            "username": user.username,
        }
    )

    return LoginResponse(
        message="Login successful",
        user_id=user.user_id,
        username=user.username,
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )