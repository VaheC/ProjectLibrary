from fastapi import APIRouter, HTTPException
from sqlalchemy import select
import bcrypt
from datetime import timedelta

from db.db import User
from db.db_session import AsyncSessionLocal
from models.auth import AuthRequest, LoginRequest, AuthResponse, LoginResponse, TokenData
from dependencies.auth import get_current_user
from dependencies.jwt import create_access_token

router = APIRouter(prefix="", tags=["Authentication"])

@router.post("/auth", response_model=AuthResponse)
async def create_user(auth_data: AuthRequest):
    # Check if passwords match
    if auth_data.password != auth_data.repeat_password:
        raise HTTPException(
            status_code=400,
            detail="Passwords do not match"
        )
    
    # Check password length
    if len(auth_data.password) < 8:
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 8 characters long"
        )
    
    async with AsyncSessionLocal() as db:
        try:
            # Check if username already exists
            stmt = select(User).where(User.username == auth_data.login)
            result = await db.execute(stmt)
            existing_user = result.scalar_one_or_none()
            
            if existing_user:
                raise HTTPException(
                    status_code=400,
                    detail="Username already exists"
                )
            
            # Hash the password
            salt = bcrypt.gensalt()
            password_hash = bcrypt.hashpw(auth_data.password.encode('utf-8'), salt)
            
            # Create new user
            new_user = User(
                username=auth_data.login,
                password_hash=password_hash.decode('utf-8')
            )
            
            db.add(new_user)
            await db.commit()
            await db.refresh(new_user)
            
            return AuthResponse(
                message="User created successfully",
                user_id=new_user.user_id,
                username=new_user.username
            )
            
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"An error occurred: {str(e)}"
            )

@router.post("/login", response_model=LoginResponse)
async def login_user(login_data: LoginRequest):
    async with AsyncSessionLocal() as db:
        try:
            # Find user by username
            stmt = select(User).where(User.username == login_data.login)
            result = await db.execute(stmt)
            user = result.scalar_one_or_none()
            
            if not user:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid username or password"
                )
            
            # Verify password
            stored_password_hash = user.password_hash.encode('utf-8')
            provided_password = login_data.password.encode('utf-8')
            
            if not bcrypt.checkpw(provided_password, stored_password_hash):
                raise HTTPException(
                    status_code=401,
                    detail="Invalid username or password"
                )
            
            # Create access token
            access_token_expires = timedelta(minutes=60)
            access_token = create_access_token(
                data={
                    "user_id": user.user_id,
                    "username": user.username
                },
                expires_delta=access_token_expires
            )
            
            return LoginResponse(
                message="Login successful",
                user_id=user.user_id,
                username=user.username,
                access_token=access_token,
                token_type="bearer",
                expires_in=60 * 60
            )
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"An error occurred: {str(e)}"
            )