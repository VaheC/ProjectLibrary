from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from .db import Base, User, Project, SharedProject, Document
from dotenv import load_dotenv
import os
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession
)
from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload
from contextlib import asynccontextmanager
from pydantic import BaseModel
import bcrypt
import jwt
from datetime import datetime, timedelta, timezone
from typing import Optional, List

_ = load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

# Create async engine
engine = create_async_engine(DATABASE_URL)

# Create async session factory
AsyncSessionLocal = async_sessionmaker(bind=engine)

# Create database tables during application startup
async def create_db_and_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# FastAPI lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_db_and_tables()
    yield

app = FastAPI(lifespan=lifespan)
security = HTTPBearer()

# Pydantic models for request/response
class AuthRequest(BaseModel):
    login: str
    password: str
    repeat_password: str

class LoginRequest(BaseModel):
    login: str
    password: str

class AuthResponse(BaseModel):
    message: str
    user_id: int
    username: str

class LoginResponse(BaseModel):
    message: str
    user_id: int
    username: str
    access_token: str
    token_type: str
    expires_in: int

class TokenData(BaseModel):
    user_id: int
    username: str

class ProjectCreateRequest(BaseModel):
    name: str
    description: str

class ProjectResponse(BaseModel):
    message: str
    project_id: int
    name: str
    description: str
    created_at: datetime
    owner_id: int
    owner_username: str

# JWT helper functions
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(token: str) -> TokenData:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("user_id")
        username: str = payload.get("username")
        if user_id is None or username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return TokenData(user_id=user_id, username=username)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

# Dependency to get current user from token
async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    token_data = verify_token(token)
    return token_data

@app.post("/auth", response_model=AuthResponse)
async def create_user(auth_data: AuthRequest):
    # Check if passwords match
    if auth_data.password != auth_data.repeat_password:
        raise HTTPException(
            status_code=400,
            detail="Passwords do not match"
        )
    
    # Check password length (minimum 8 characters for security)
    if len(auth_data.password) < 8:
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 8 characters long"
        )
    
    # Create an async database session
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
            
            # Hash the password using bcrypt
            salt = bcrypt.gensalt()
            password_hash = bcrypt.hashpw(auth_data.password.encode('utf-8'), salt)
            
            # Create new user
            new_user = User(
                username=auth_data.login,
                password_hash=password_hash.decode('utf-8')  # Store as string
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

@app.post("/login", response_model=LoginResponse)
async def login_user(login_data: LoginRequest):
    # Create an async database session
    async with AsyncSessionLocal() as db:
        try:
            # Find user by username - ASYNC
            stmt = select(User).where(User.username == login_data.login)
            result = await db.execute(stmt)
            user = result.scalar_one_or_none()
            
            # Check if user exists
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
            access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
            access_token = create_access_token(
                data={
                    "user_id": user.user_id,
                    "username": user.username
                },
                expires_delta=access_token_expires
            )
            
            # Login successful
            return LoginResponse(
                message="Login successful",
                user_id=user.user_id,
                username=user.username,
                access_token=access_token,
                token_type="bearer",
                expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60  # Convert to seconds
            )
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"An error occurred: {str(e)}"
            )

@app.post("/projects", response_model=ProjectResponse)
async def create_project(
    project_data: ProjectCreateRequest,
    current_user: TokenData = Depends(get_current_user)
):
    # Validate project name (minimum 3 characters)
    if len(project_data.name.strip()) < 3:
        raise HTTPException(
            status_code=400,
            detail="Project name must be at least 3 characters long"
        )
    
    # Validate description (minimum 10 characters)
    if len(project_data.description.strip()) < 10:
        raise HTTPException(
            status_code=400,
            detail="Project description must be at least 10 characters long"
        )
    
    # Create an async database session
    async with AsyncSessionLocal() as db:
        try:
            # Check if project name already exists (case-insensitive) - ASYNC
            stmt = select(Project).where(Project.name.ilike(project_data.name.strip()))
            result = await db.execute(stmt)
            existing_project = result.scalar_one_or_none()
            
            if existing_project:
                raise HTTPException(
                    status_code=400,
                    detail="A project with this name already exists"
                )
            
            # Create the project
            new_project = Project(
                name=project_data.name.strip(),
                description=project_data.description.strip(),
                user_id=current_user.user_id,  # Set the creator as the owner
                created_at=datetime.now(timezone.utc)
            )
            
            db.add(new_project)
            await db.flush()  # Flush to get the project_id before creating SharedProject
            
            # Automatically give the creator access as owner/admin
            shared_project = SharedProject(
                project_id=new_project.project_id,
                shared_with_user_id=current_user.user_id
            )
            
            db.add(shared_project)
            await db.commit()
            await db.refresh(new_project)
            
            return ProjectResponse(
                message="Project created successfully",
                project_id=new_project.project_id,
                name=new_project.name,
                description=new_project.description,
                created_at=new_project.created_at,
                owner_id=current_user.user_id,
                owner_username=current_user.username
            )
            
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"An error occurred while creating the project: {str(e)}"
            )



