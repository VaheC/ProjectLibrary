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

class DocumentResponse(BaseModel):
    document_id: int
    document_url: str

class ProjectDetailResponse(BaseModel):
    project_id: int
    name: str
    description: str
    created_at: datetime
    owner_id: int
    owner_username: str
    documents: List[DocumentResponse] = []

class ProjectsListResponse(BaseModel):
    message: str
    count: int
    projects: List[ProjectDetailResponse]

@app.get("/projects", response_model=ProjectsListResponse)
async def get_user_projects(current_user: TokenData = Depends(get_current_user)):
    """
    Get all projects accessible to the current user.
    Returns full project details including their documents.
    """
    async with AsyncSessionLocal() as db:
        try:
            # Query projects where user is either the owner OR project is shared with them
            stmt = (
                select(Project)
                .options(
                    selectinload(Project.documents),  # Eager load documents
                    selectinload(Project.user)       # Eager load user (owner)
                )
                .join(User, Project.user)  # Join with User to get owner info
                .outerjoin(SharedProject, SharedProject.project_id == Project.project_id)
                .where(
                    or_(
                        Project.user_id == current_user.user_id,  # User owns the project
                        SharedProject.shared_with_user_id == current_user.user_id  # Project is shared with user
                    )
                )
                .distinct()  # Remove duplicates if a user both owns and is shared
                .order_by(Project.created_at.desc())  # Most recent first
            )
            
            result = await db.execute(stmt)
            projects = result.scalars().all()
            
            # Build response with owner usernames
            projects_response = []
            for project in projects:
                # Now project.user is already loaded, no lazy load needed
                owner_username = project.user.username if project.user else None
                
                # Convert documents to response model
                documents = [
                    DocumentResponse(
                        document_id=doc.document_id,
                        document_url=doc.document_url
                    )
                    for doc in project.documents
                ]
                
                projects_response.append(
                    ProjectDetailResponse(
                        project_id=project.project_id,
                        name=project.name,
                        description=project.description,
                        created_at=project.created_at,
                        owner_id=project.user_id,
                        owner_username=owner_username or "Unknown",
                        documents=documents
                    )
                )
            
            return ProjectsListResponse(
                message=f"Found {len(projects_response)} projects accessible to user",
                count=len(projects_response),
                projects=projects_response
            )
            
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"An error occurred while retrieving projects: {str(e)}"
            )

@app.get("/project/{project_id}/info", response_model=ProjectDetailResponse)
async def get_project_info(
    project_id: int,
    current_user: TokenData = Depends(get_current_user)
):
    """
    Get detailed information about a specific project.
    Returns full project details including its documents.
    Access is granted if user owns the project or the project is shared with them.
    """
    async with AsyncSessionLocal() as db:
        try:
            # Query project with eager loading of documents and owner
            stmt = (
                select(Project)
                .options(
                    selectinload(Project.documents),
                    selectinload(Project.user)
                )
                .where(Project.project_id == project_id)
            )
            
            result = await db.execute(stmt)
            project = result.scalar_one_or_none()
            
            if not project:
                raise HTTPException(
                    status_code=404,
                    detail="Project not found"
                )
            
            # Check if user has access (owns the project or project is shared with them)
            # First check if user is the owner
            has_access = project.user_id == current_user.user_id
            
            # If not owner, check if project is shared with the user
            if not has_access:
                share_stmt = (
                    select(SharedProject)
                    .where(
                        SharedProject.project_id == project_id,
                        SharedProject.shared_with_user_id == current_user.user_id
                    )
                )
                share_result = await db.execute(share_stmt)
                shared_project = share_result.scalar_one_or_none()
                has_access = shared_project is not None
            
            if not has_access:
                raise HTTPException(
                    status_code=403,
                    detail="You do not have access to this project"
                )
            
            # Build response
            owner_username = project.user.username if project.user else "Unknown"
            
            documents = [
                DocumentResponse(
                    document_id=doc.document_id,
                    document_url=doc.document_url
                )
                for doc in project.documents
            ]
            
            return ProjectDetailResponse(
                project_id=project.project_id,
                name=project.name,
                description=project.description,
                created_at=project.created_at,
                owner_id=project.user_id,
                owner_username=owner_username,
                documents=documents
            )
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"An error occurred while retrieving the project: {str(e)}"
            )



