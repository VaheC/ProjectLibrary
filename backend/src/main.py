from fastapi import FastAPI, HTTPException, Depends, status, UploadFile, File
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import StreamingResponse
from .db import Base, User, Project, SharedProject, Document
from dotenv import load_dotenv
import os
import shutil
import uuid
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
import aioboto3
from botocore.exceptions import ClientError
import io

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

class ProjectUpdateRequest(BaseModel):
    name: str
    description: str

@app.put("/project/{project_id}/info", response_model=ProjectDetailResponse)
async def update_project_info(
    project_id: int,
    update_data: ProjectUpdateRequest,
    current_user: TokenData = Depends(get_current_user)
):
    """
    Update project details (name and description).
    Only the project owner can update the project.
    Returns the updated project information.
    """
    # Validate project name (minimum 3 characters)
    if len(update_data.name.strip()) < 3:
        raise HTTPException(
            status_code=400,
            detail="Project name must be at least 3 characters long"
        )
    
    # Validate description (minimum 10 characters)
    if len(update_data.description.strip()) < 10:
        raise HTTPException(
            status_code=400,
            detail="Project description must be at least 10 characters long"
        )
    
    async with AsyncSessionLocal() as db:
        try:
            # Get the project with eager loading
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
            
            # Check if current user is the owner
            if project.user_id != current_user.user_id:
                raise HTTPException(
                    status_code=403,
                    detail="Only the project owner can update this project"
                )
            
            # Check if new name conflicts with existing project (excluding current project)
            name_check_stmt = (
                select(Project)
                .where(
                    Project.name.ilike(update_data.name.strip()),
                    Project.project_id != project_id
                )
            )
            name_check_result = await db.execute(name_check_stmt)
            existing_project = name_check_result.scalar_one_or_none()
            
            if existing_project:
                raise HTTPException(
                    status_code=400,
                    detail="A project with this name already exists"
                )
            
            # Update project details
            project.name = update_data.name.strip()
            project.description = update_data.description.strip()
            
            await db.commit()
            await db.refresh(project)
            
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
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"An error occurred while updating the project: {str(e)}"
            )

@app.delete("/project/{project_id}")
async def delete_project(
    project_id: int,
    current_user: TokenData = Depends(get_current_user)
):
    """
    Delete a project and all associated documents.
    Only the project owner can delete the project.
    """
    async with AsyncSessionLocal() as db:
        try:
            # Get the project
            stmt = select(Project).where(Project.project_id == project_id)
            result = await db.execute(stmt)
            project = result.scalar_one_or_none()
            
            if not project:
                raise HTTPException(
                    status_code=404,
                    detail="Project not found"
                )
            
            # Check if current user is the owner
            if project.user_id != current_user.user_id:
                raise HTTPException(
                    status_code=403,
                    detail="Only the project owner can delete this project"
                )
            
            # Delete the project (cascade will handle documents and shared_projects)
            await db.delete(project)
            await db.commit()
            
            return {
                "message": f"Project '{project.name}' deleted successfully",
                "project_id": project_id
            }
            
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"An error occurred while deleting the project: {str(e)}"
            )

@app.get("/project/{project_id}/documents", response_model=List[DocumentResponse])
async def get_project_documents(
    project_id: int,
    current_user: TokenData = Depends(get_current_user)
):
    """
    Get all documents associated with a specific project.
    Access is granted if user owns the project or the project is shared with them.
    """
    async with AsyncSessionLocal() as db:
        try:
            # First, check if the project exists and user has access
            project_stmt = select(Project).where(Project.project_id == project_id)
            project_result = await db.execute(project_stmt)
            project = project_result.scalar_one_or_none()
            
            if not project:
                raise HTTPException(
                    status_code=404,
                    detail="Project not found"
                )
            
            # Check if user has access (owns the project or project is shared with them)
            has_access = project.user_id == current_user.user_id
            
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
            
            # Get all documents for the project
            doc_stmt = (
                select(Document)
                .where(Document.project_id == project_id)
                .order_by(Document.document_id)
            )
            doc_result = await db.execute(doc_stmt)
            documents = doc_result.scalars().all()
            
            return [
                DocumentResponse(
                    document_id=doc.document_id,
                    document_url=doc.document_url
                )
                for doc in documents
            ]
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"An error occurred while retrieving documents: {str(e)}"
            )

class DocumentUploadResponse(BaseModel):
    message: str
    uploaded_count: int
    documents: List[DocumentResponse]

# Add these environment variables
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_S3_BUCKET = os.getenv("AWS_S3_BUCKET")
# AWS_SESSION_TOKEN = os.getenv("AWS_SESSION_TOKEN")

# Create async S3 client
# async def get_s3_client():
#     """Get async S3 client using aioboto3."""
#     session = aioboto3.Session()
#     return await session.client(
#         's3',
#         aws_access_key_id=AWS_ACCESS_KEY_ID,
#         aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
#         region_name=AWS_REGION
#     )

def get_s3_client():
    session = aioboto3.Session()
    return session.client(
        's3',
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=AWS_REGION,
        # aws_session_token=AWS_SESSION_TOKEN
    )

# @app.post("/project/{project_id}/documents", response_model=DocumentUploadResponse)
# async def upload_documents(
#     project_id: int,
#     files: List[UploadFile] = File(...),
#     current_user: TokenData = Depends(get_current_user)
# ):
#     """
#     Upload one or more documents for a specific project to AWS S3 using aioboto3.
#     Access is granted if user owns the project or the project is shared with them.
#     """
#     async with AsyncSessionLocal() as db:
#         try:
#             # Check if project exists and user has access
#             project_stmt = select(Project).where(Project.project_id == project_id)
#             project_result = await db.execute(project_stmt)
#             project = project_result.scalar_one_or_none()
            
#             if not project:
#                 raise HTTPException(
#                     status_code=404,
#                     detail="Project not found"
#                 )
            
#             # Check if user has access
#             has_access = project.user_id == current_user.user_id
            
#             if not has_access:
#                 share_stmt = (
#                     select(SharedProject)
#                     .where(
#                         SharedProject.project_id == project_id,
#                         SharedProject.shared_with_user_id == current_user.user_id
#                     )
#                 )
#                 share_result = await db.execute(share_stmt)
#                 shared_project = share_result.scalar_one_or_none()
#                 has_access = shared_project is not None
            
#             if not has_access:
#                 raise HTTPException(
#                     status_code=403,
#                     detail="You do not have access to this project"
#                 )
            
#             uploaded_documents = []
            
#             # Get async S3 client
#             # async with await get_s3_client() as s3_client:
#             async with get_s3_client() as s3_client:
#                 for file in files:
#                     # Generate unique filename
#                     file_extension = os.path.splitext(file.filename)[1]
#                     unique_filename = f"projects/{project_id}/{uuid.uuid4()}{file_extension}"
                    
#                     # Read file content
#                     file_content = await file.read()
                    
#                     try:
#                         # Upload to S3 asynchronously
#                         await s3_client.put_object(
#                             Bucket=AWS_S3_BUCKET,
#                             Key=unique_filename,
#                             Body=file_content,
#                             ContentType=file.content_type or 'application/octet-stream'
#                         )
                        
#                         # Generate S3 URL
#                         document_url = f"https://{AWS_S3_BUCKET}.s3.{AWS_REGION}.amazonaws.com/{unique_filename}"
                        
#                         # Create document record in database
#                         new_document = Document(
#                             project_id=project_id,
#                             document_url=document_url
#                         )
                        
#                         db.add(new_document)
#                         await db.flush()
#                         await db.refresh(new_document)
                        
#                         uploaded_documents.append(
#                             DocumentResponse(
#                                 document_id=new_document.document_id,
#                                 document_url=new_document.document_url
#                             )
#                         )
                        
#                     except ClientError as e:
#                         raise HTTPException(
#                             status_code=500,
#                             detail=f"Failed to upload file '{file.filename}' to S3: {str(e)}"
#                         )
#                     finally:
#                         # Reset file position for potential reuse
#                         await file.seek(0)
            
#             await db.commit()
            
#             return DocumentUploadResponse(
#                 message=f"Successfully uploaded {len(uploaded_documents)} document(s) to S3",
#                 uploaded_count=len(uploaded_documents),
#                 documents=uploaded_documents
#             )
            
#         except HTTPException:
#             await db.rollback()
#             raise
#         except Exception as e:
#             await db.rollback()
#             raise HTTPException(
#                 status_code=500,
#                 detail=f"An error occurred while uploading documents: {str(e)}"
#             )

@app.post("/project/{project_id}/documents", response_model=DocumentUploadResponse)
async def upload_document(
    project_id: int,
    file: UploadFile = File(...),
    current_user: TokenData = Depends(get_current_user)
):
    """
    Upload one or more documents for a specific project to AWS S3 using aioboto3.
    Access is granted if user owns the project or the project is shared with them.
    """
    async with AsyncSessionLocal() as db:
        try:
            # Check if project exists and user has access
            project_stmt = select(Project).where(Project.project_id == project_id)
            project_result = await db.execute(project_stmt)
            project = project_result.scalar_one_or_none()
            
            if not project:
                raise HTTPException(
                    status_code=404,
                    detail="Project not found"
                )
            
            # Check if user has access
            has_access = project.user_id == current_user.user_id
            
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
            
            uploaded_documents = []
            
            # Get async S3 client
            # async with await get_s3_client() as s3_client:
            async with get_s3_client() as s3_client:

                # Generate unique filename
                file_extension = os.path.splitext(file.filename)[1]
                unique_filename = f"projects/{project_id}/{uuid.uuid4()}{file_extension}"
                
                # Read file content
                file_content = await file.read()
                
                try:
                    # Upload to S3 asynchronously
                    await s3_client.put_object(
                        Bucket=AWS_S3_BUCKET,
                        Key=unique_filename,
                        Body=file_content,
                        ContentType=file.content_type or 'application/octet-stream'
                    )
                    
                    # Generate S3 URL
                    document_url = f"https://{AWS_S3_BUCKET}.s3.{AWS_REGION}.amazonaws.com/{unique_filename}"
                    
                    # Create document record in database
                    new_document = Document(
                        project_id=project_id,
                        document_url=document_url
                    )
                    
                    db.add(new_document)
                    await db.flush()
                    await db.refresh(new_document)
                    
                    uploaded_documents.append(
                        DocumentResponse(
                            document_id=new_document.document_id,
                            document_url=new_document.document_url
                        )
                    )
                    
                except ClientError as e:
                    raise HTTPException(
                        status_code=500,
                        detail=f"Failed to upload file '{file.filename}' to S3: {str(e)}"
                    )
                finally:
                    # Reset file position for potential reuse
                    await file.seek(0)
            
            await db.commit()
            
            return DocumentUploadResponse(
                message=f"Successfully uploaded {len(uploaded_documents)} document(s) to S3",
                uploaded_count=len(uploaded_documents),
                documents=uploaded_documents
            )
            
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"An error occurred while uploading documents: {str(e)}"
            )

# Initialize aioboto3 session (add this at the top of your file with other globals)
# Note: You don't need to create a client here, we'll create it inside the function

@app.get("/document/{document_id}")
async def download_document(
    document_id: int,
    current_user: TokenData = Depends(get_current_user)
):
    """
    Download a specific document from S3.
    Access is granted if user has access to the project containing this document.
    """
    async with AsyncSessionLocal() as db:
        try:
            # Get the document with project info
            doc_stmt = (
                select(Document)
                .where(Document.document_id == document_id)
            )
            doc_result = await db.execute(doc_stmt)
            document = doc_result.scalar_one_or_none()
            
            if not document:
                raise HTTPException(
                    status_code=404,
                    detail="Document not found"
                )
            
            # Get the associated project
            project_stmt = select(Project).where(Project.project_id == document.project_id)
            project_result = await db.execute(project_stmt)
            project = project_result.scalar_one_or_none()
            
            if not project:
                raise HTTPException(
                    status_code=404,
                    detail="Associated project not found"
                )
            
            # Check if user has access (owns the project or project is shared with them)
            has_access = project.user_id == current_user.user_id
            
            if not has_access:
                share_stmt = (
                    select(SharedProject)
                    .where(
                        SharedProject.project_id == document.project_id,
                        SharedProject.shared_with_user_id == current_user.user_id
                    )
                )
                share_result = await db.execute(share_stmt)
                shared_project = share_result.scalar_one_or_none()
                has_access = shared_project is not None
            
            if not has_access:
                raise HTTPException(
                    status_code=403,
                    detail="You do not have access to this document"
                )
            
            # Extract S3 key from URL
            # URL format: https://bucket.s3.region.amazonaws.com/projects/{project_id}/{filename}
            s3_key = document.document_url.split(f"{AWS_S3_BUCKET}.s3.{AWS_REGION}.amazonaws.com/")[-1]
            
            try:
                # Create async S3 session and client
                session = aioboto3.Session()
                async with session.client(
                    's3',
                    aws_access_key_id=AWS_ACCESS_KEY_ID,
                    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
                    region_name=AWS_REGION
                ) as s3_client:
                    # Get file from S3 asynchronously
                    response = await s3_client.get_object(
                        Bucket=AWS_S3_BUCKET,
                        Key=s3_key
                    )
                    
                    # Read file content asynchronously
                    file_content = await response['Body'].read()
                    content_type = response.get('ContentType', 'application/octet-stream')
                    
                    # Extract filename from S3 key
                    filename = s3_key.split('/')[-1]
                    
                    # Return file as streaming response
                    return StreamingResponse(
                        io.BytesIO(file_content),
                        media_type=content_type,
                        headers={
                            "Content-Disposition": f"attachment; filename={filename}"
                        }
                    )
                
            except ClientError as e:
                if e.response['Error']['Code'] == 'NoSuchKey':
                    raise HTTPException(
                        status_code=404,
                        detail="File not found in S3 storage"
                    )
                else:
                    raise HTTPException(
                        status_code=500,
                        detail=f"Error retrieving file from S3: {str(e)}"
                    )
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"An error occurred while downloading the document: {str(e)}"
            )

# @app.put("/document/{document_id}", response_model=DocumentResponse)
# async def update_document(
#     document_id: int,
#     file: UploadFile = File(...),
#     current_user: TokenData = Depends(get_current_user)
# ):
#     """
#     Update an existing document by replacing it with a new file in S3.
#     Access is granted if user owns the project containing this document.
#     """
#     async with AsyncSessionLocal() as db:
#         try:
#             # Get the document with project info
#             doc_stmt = (
#                 select(Document)
#                 .where(Document.document_id == document_id)
#             )
#             doc_result = await db.execute(doc_stmt)
#             document = doc_result.scalar_one_or_none()
            
#             if not document:
#                 raise HTTPException(
#                     status_code=404,
#                     detail="Document not found"
#                 )
            
#             # Get the associated project
#             project_stmt = select(Project).where(Project.project_id == document.project_id)
#             project_result = await db.execute(project_stmt)
#             project = project_result.scalar_one_or_none()
            
#             if not project:
#                 raise HTTPException(
#                     status_code=404,
#                     detail="Associated project not found"
#                 )
            
#             # Check if user is the owner (only owner can update documents)
#             if project.user_id != current_user.user_id:
#                 raise HTTPException(
#                     status_code=403,
#                     detail="Only the project owner can update documents"
#                 )
            
#             # Extract old S3 key from URL
#             old_s3_key = document.document_url.split(f"{AWS_S3_BUCKET}.s3.{AWS_REGION}.amazonaws.com/")[-1]
            
#             # Generate new unique filename
#             file_extension = os.path.splitext(file.filename)[1]
#             new_s3_key = f"projects/{document.project_id}/{uuid.uuid4()}{file_extension}"
            
#             # Read file content
#             file_content = await file.read()
            
#             try:
#                 # Upload new file to S3
#                 s3_client.put_object(
#                     Bucket=AWS_S3_BUCKET,
#                     Key=new_s3_key,
#                     Body=file_content,
#                     ContentType=file.content_type or 'application/octet-stream'
#                 )
                
#                 # Delete old file from S3
#                 s3_client.delete_object(
#                     Bucket=AWS_S3_BUCKET,
#                     Key=old_s3_key
#                 )
                
#                 # Generate new S3 URL
#                 new_document_url = f"https://{AWS_S3_BUCKET}.s3.{AWS_REGION}.amazonaws.com/{new_s3_key}"
                
#                 # Update document in database
#                 document.document_url = new_document_url
                
#                 await db.commit()
#                 await db.refresh(document)
                
#                 return DocumentResponse(
#                     document_id=document.document_id,
#                     document_url=document.document_url
#                 )
                
#             except ClientError as e:
#                 await db.rollback()
#                 raise HTTPException(
#                     status_code=500,
#                     detail=f"Failed to update file in S3: {str(e)}"
#                 )
#             finally:
#                 await file.seek(0)
            
#         except HTTPException:
#             await db.rollback()
#             raise
#         except Exception as e:
#             await db.rollback()
#             raise HTTPException(
#                 status_code=500,
#                 detail=f"An error occurred while updating the document: {str(e)}"
#             )

# @app.delete("/document/{document_id}")
# async def delete_document(
#     document_id: int,
#     current_user: TokenData = Depends(get_current_user)
# ):
#     """
#     Delete a specific document from both S3 and the database.
#     Only the project owner can delete documents.
#     """
#     async with AsyncSessionLocal() as db:
#         try:
#             # Get the document with project info
#             doc_stmt = (
#                 select(Document)
#                 .where(Document.document_id == document_id)
#             )
#             doc_result = await db.execute(doc_stmt)
#             document = doc_result.scalar_one_or_none()
            
#             if not document:
#                 raise HTTPException(
#                     status_code=404,
#                     detail="Document not found"
#                 )
            
#             # Get the associated project
#             project_stmt = select(Project).where(Project.project_id == document.project_id)
#             project_result = await db.execute(project_stmt)
#             project = project_result.scalar_one_or_none()
            
#             if not project:
#                 raise HTTPException(
#                     status_code=404,
#                     detail="Associated project not found"
#                 )
            
#             # Check if user is the owner (only owner can delete documents)
#             if project.user_id != current_user.user_id:
#                 raise HTTPException(
#                     status_code=403,
#                     detail="Only the project owner can delete documents"
#                 )
            
#             # Extract S3 key from URL
#             s3_key = document.document_url.split(f"{AWS_S3_BUCKET}.s3.{AWS_REGION}.amazonaws.com/")[-1]
            
#             try:
#                 # Delete file from S3
#                 s3_client.delete_object(
#                     Bucket=AWS_S3_BUCKET,
#                     Key=s3_key
#                 )
#             except ClientError as e:
#                 # Log error but continue with database deletion
#                 print(f"Warning: Failed to delete file from S3: {str(e)}")
            
#             # Delete document from database
#             await db.delete(document)
#             await db.commit()
            
#             return {
#                 "message": f"Document {document_id} deleted successfully",
#                 "document_id": document_id
#             }
            
#         except HTTPException:
#             await db.rollback()
#             raise
#         except Exception as e:
#             await db.rollback()
#             raise HTTPException(
#                 status_code=500,
#                 detail=f"An error occurred while deleting the document: {str(e)}"
#             )

@app.post("/project/{project_id}/invite")
async def invite_user_to_project(
    project_id: int,
    login: str,
    current_user: TokenData = Depends(get_current_user)
):
    """
    Grant access to a project for a specific user.
    Only the project owner can invite users.
    """
    async with AsyncSessionLocal() as db:
        try:
            # Get the project
            project_stmt = select(Project).where(Project.project_id == project_id)
            project_result = await db.execute(project_stmt)
            project = project_result.scalar_one_or_none()
            
            if not project:
                raise HTTPException(
                    status_code=404,
                    detail="Project not found"
                )
            
            # Check if current user is the owner
            if project.user_id != current_user.user_id:
                raise HTTPException(
                    status_code=403,
                    detail="Only the project owner can invite users"
                )
            
            # Find the user to invite
            user_stmt = select(User).where(User.username == login)
            user_result = await db.execute(user_stmt)
            invited_user = user_result.scalar_one_or_none()
            
            if not invited_user:
                raise HTTPException(
                    status_code=404,
                    detail="User not found"
                )
            
            # Check if user is the owner (can't invite themselves)
            if invited_user.user_id == current_user.user_id:
                raise HTTPException(
                    status_code=400,
                    detail="You cannot invite yourself to your own project"
                )
            
            # Check if user already has access
            existing_share_stmt = (
                select(SharedProject)
                .where(
                    SharedProject.project_id == project_id,
                    SharedProject.shared_with_user_id == invited_user.user_id
                )
            )
            existing_share_result = await db.execute(existing_share_stmt)
            existing_share = existing_share_result.scalar_one_or_none()
            
            if existing_share:
                raise HTTPException(
                    status_code=400,
                    detail="User already has access to this project"
                )
            
            # Grant access
            shared_project = SharedProject(
                project_id=project_id,
                shared_with_user_id=invited_user.user_id
            )
            
            db.add(shared_project)
            await db.commit()
            
            return {
                "message": f"User '{login}' has been granted access to project '{project.name}'",
                "project_id": project_id,
                "project_name": project.name,
                "user_id": invited_user.user_id,
                "username": invited_user.username
            }
            
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"An error occurred while inviting user: {str(e)}"
            )
